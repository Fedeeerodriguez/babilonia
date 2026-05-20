"""Orquestador determinístico del sub-agente bases_datos.

Reemplaza el sub-agente LLM-based de n8n. Recibe un mensaje libre o listas
explícitas, extrae emails/pólizas/clientes con regex, y consulta Notion en batch.

Sin LLM en el medio. Sin variabilidad.
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from app.services.tomi import notion_client as nc
from app.services.tomi import validaciones as val

log = logging.getLogger("tomi.bases_datos")

# Regex
RX_EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
# Pólizas tipo "Plus3-403328", "Vida-12345", "Auto-9876543", "PLU3-408444"
RX_POLIZA = re.compile(r"\b[A-Za-z][A-Za-z0-9]*-\d{3,}\b")

# Nombres precedidos por marcador semántico — conservador para evitar falsos positivos.
# Captura 1-3 palabras capitalizadas (incluye acentos/ñ) tras "cliente|asesor|asesora|de|para|del|señor|señora".
# Inline flag (?i:...) hace case-insensitive SOLO el marcador, manteniendo el name
# strict uppercase para evitar capturar "la asesora Jimena con sus" como nombre.
RX_NOMBRE_CLIENTE = re.compile(
    r"(?i:\bcliente|\bsr|\bsra|\bseñor|\bseñora|\bpara|\bdel?)\b\s+"
    r"([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){0,2})"
)
RX_NOMBRE_ASESOR = re.compile(
    r"(?i:\basesor|\basesora)\b\s+"
    r"([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){0,2})"
)

KEYWORDS_TICKETS = (
    "siniestro", "denuncia", "tramite", "trámite", "queja", "reclamo",
    "endoso", "modificación", "modificacion", "renovación", "renovacion",
)
KEYWORDS_CALENDLY = ("turno", "agenda", "agendar", "reunión", "reunion", "cita", "calendly")
KEYWORDS_COBRANZA = ("cobranza", "pago", "saldo", "cuota", "vencimiento", "pagar", "debo")


def _extraer(mensaje: str) -> Tuple[List[str], List[str], List[str], List[str]]:
    """Devuelve (emails, polizas, nombres_clientes, nombres_asesores)."""
    if not mensaje:
        return [], [], [], []
    emails = sorted({m.group(0).lower() for m in RX_EMAIL.finditer(mensaje)})
    polizas = sorted({m.group(0) for m in RX_POLIZA.finditer(mensaje)})
    nombres_cli = sorted({m.group(1).strip() for m in RX_NOMBRE_CLIENTE.finditer(mensaje)})
    nombres_ase = sorted({m.group(1).strip() for m in RX_NOMBRE_ASESOR.finditer(mensaje)})
    # No duplicar: si el mismo nombre quedó marcado como ambos, prevalece asesor
    nombres_cli = [n for n in nombres_cli if n not in nombres_ase]
    return emails, polizas, nombres_cli, nombres_ase


def _detectar_intents(mensaje: str) -> Dict[str, bool]:
    if not mensaje:
        return {"tickets": False, "calendly": False, "cobranza": False}
    m = mensaje.lower()
    return {
        "tickets": any(k in m for k in KEYWORDS_TICKETS),
        "calendly": any(k in m for k in KEYWORDS_CALENDLY),
        "cobranza": any(k in m for k in KEYWORDS_COBRANZA),
    }


MODOS_VALIDOS = ("perfil", "polizas", "clientes", "cobranzas", "eventos", "completo", "cartera")

# Orden de relevancia de estados — usado para elegir la mejor emisión cuando hay duplicados
_ESTADO_PRIORIDAD = {
    "Activa": 0,
    "Pagada – Pendiente de Emisión": 1,
    "Aprobada – Pendiente de Pago": 2,
    "Cliente Firmando": 3,
    "Cliente en Biométrico": 4,
    "Por subir a Portal": 5,
    "En Autorización": 6,
    "Documentos Faltantes": 7,
    "Cancelada": 8,
    "Cancelación Pre-Emisión": 9,
}


def _prioridad_estado(estado: Optional[str]) -> int:
    return _ESTADO_PRIORIDAD.get(estado or "", 99)


def cartera_de_asesor(email_asesor: str) -> Dict[str, Any]:
    """Construye la cartera deduplicada de un asesor.

    Algoritmo:
    1. Query Emisiones por Correo Asesor (case-insensitive).
    2. Bucket por Correo Cliente (lowercase). Si no hay correo, fallback nombre+teléfono.
    3. Dentro de cada cliente, dedupe pólizas por Número de Póliza (o Solicitud si vacío).
       Si hay duplicados, prevalece el mejor estado (Activa > Pendiente > Cancelada).
    4. Resuelve Portafolios relation de cada póliza a nombres de fondos.
    5. Devuelve cartera estructurada.
    """
    if not email_asesor:
        return {"asesor_email": None, "total_clientes_unicos": 0, "total_polizas": 0, "clientes": []}

    emisiones = nc.emisiones_por_correo_asesor(email_asesor, page_size=200)

    # 1. Bucket por correo cliente
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    sin_correo: List[Dict[str, Any]] = []
    for e in emisiones:
        correo = (e.get("Correo Cliente") or "").strip().lower()
        if correo:
            buckets.setdefault(correo, []).append(e)
        else:
            # Fallback: agrupar por (nombre normalizado + teléfono)
            nombre = (e.get("Nombre Cliente") or e.get("_title") or "").strip().lower()
            tel = (e.get("Teléfono Cliente") or "").strip()
            key = f"_sin_correo::{nombre}::{tel}"
            buckets.setdefault(key, []).append(e)

    # 2. Recolectar todos los IDs de portafolios para resolver en una sola pasada
    portafolio_ids: set = set()
    for emisiones_list in buckets.values():
        for e in emisiones_list:
            for pid in (e.get("Portafolios") or []):
                if isinstance(pid, str) and len(pid) >= 32:
                    portafolio_ids.add(pid)

    portafolios_map: Dict[str, str] = {}
    if portafolio_ids:
        try:
            portafolios_map = nc.resolver_portafolios(list(portafolio_ids))
        except Exception as e:
            log.error("resolver_portafolios falló: %s", e)

    # 3. Construir lista de clientes
    clientes_out: List[Dict[str, Any]] = []
    total_polizas = 0

    for key, emis_cliente in buckets.items():
        # Datos del cliente — tomar de la emisión más reciente (mejor estado)
        emis_cliente_sorted = sorted(
            emis_cliente,
            key=lambda x: (_prioridad_estado(x.get("Estado")), -(int(((x.get("Fecha de Emisión") or {}).get("start") or "0000-00-00").replace("-", "")[:8]) if isinstance(x.get("Fecha de Emisión"), dict) else 0))
        )
        primera = emis_cliente_sorted[0]
        nombre = primera.get("Nombre Cliente") or "(sin nombre)"
        email_cli = primera.get("Correo Cliente") or ""
        tel_cli = primera.get("Teléfono Cliente") or ""

        # 3a. Dedupe pólizas dentro del cliente
        polizas_unicas: Dict[str, Dict[str, Any]] = {}
        for e in emis_cliente:
            num = (e.get("Número de Póliza") or "").strip()
            sol = (e.get("Solicitud") or "").strip()
            poliza_key = num if num else f"_sol::{sol}"
            actual = polizas_unicas.get(poliza_key)
            if not actual:
                polizas_unicas[poliza_key] = e
            else:
                # Reemplazar si la nueva tiene mejor estado
                if _prioridad_estado(e.get("Estado")) < _prioridad_estado(actual.get("Estado")):
                    polizas_unicas[poliza_key] = e

        # 3b. Construir lista de pólizas con fondos resueltos
        polizas_list: List[Dict[str, Any]] = []
        fondos_consolidados: set = set()
        for e in polizas_unicas.values():
            fondos_ids = [p for p in (e.get("Portafolios") or []) if isinstance(p, str)]
            fondos_nombres = [portafolios_map.get(pid, "(no resuelto)") for pid in fondos_ids]
            for f in fondos_nombres:
                if f and f != "(no resuelto)":
                    fondos_consolidados.add(f)
            polizas_list.append({
                "numero": e.get("Número de Póliza") or None,
                "solicitud": e.get("Solicitud"),
                "producto": e.get("Producto (nombre)"),
                "prima": e.get("Prima"),
                "periodicidad": e.get("Periodicidad"),
                "valor_plan": e.get("Valor Plan"),
                "plazo": e.get("Plazo Comprometido"),
                "estado": e.get("Estado"),
                "fecha_emision": (e.get("Fecha de Emisión") or {}).get("start") if isinstance(e.get("Fecha de Emisión"), dict) else None,
                "fecha_cobro_original": (e.get("Fecha de Cobro Original") or {}).get("start") if isinstance(e.get("Fecha de Cobro Original"), dict) else None,
                "conducto_cobro": e.get("Conducto de cobro"),
                "fondos": fondos_nombres,
                "url": e.get("_url"),
            })
        # Sort pólizas por (prioridad estado, fecha emisión DESC)
        polizas_list.sort(key=lambda p: (_prioridad_estado(p.get("estado")), -(int((p.get("fecha_emision") or "0000-00-00").replace("-", "")[:8]) if p.get("fecha_emision") else 0)))

        total_polizas += len(polizas_list)
        clientes_out.append({
            "email": email_cli or None,
            "nombre": nombre,
            "telefono": tel_cli or None,
            "polizas": polizas_list,
            "total_polizas": len(polizas_list),
            "fondos_consolidados": sorted(fondos_consolidados),
            "_key": key,
        })

    # 4. Ordenar clientes por cantidad de pólizas DESC, luego por nombre
    clientes_out.sort(key=lambda c: (-c["total_polizas"], (c["nombre"] or "").lower()))

    return {
        "asesor_email": email_asesor,
        "total_clientes_unicos": len(clientes_out),
        "total_polizas": total_polizas,
        "total_fondos_distintos": len({f for c in clientes_out for f in c["fondos_consolidados"]}),
        "clientes": clientes_out,
        "stats": {
            "emisiones_crudas_recuperadas": len(emisiones),
            "buckets_creados": len(buckets),
            "portafolios_resueltos": len(portafolios_map),
        },
    }


def consultar(
    mensaje: str = "",
    emails: Optional[List[str]] = None,
    polizas: Optional[List[str]] = None,
    clientes: Optional[List[str]] = None,
    asesores: Optional[List[str]] = None,
    incluir: Optional[List[str]] = None,
    # nuevos params
    modo: str = "completo",
    email_asesor: Optional[str] = None,
    email_cliente: Optional[str] = None,
    solo_activas: bool = False,
    limite: int = 100,
) -> Dict[str, Any]:
    """Orquesta las búsquedas en paralelo y devuelve el JSON estructurado.

    Args:
        modo: "perfil" (solo datos básicos del usuario sin expandido pesado),
              "polizas" (foco en emisiones del cliente/asesor),
              "clientes" (lista de clientes del asesor, sin emisiones),
              "cobranzas" (solo cobranzas por póliza),
              "eventos" (solo calendly),
              "completo" (todo, comportamiento legacy — usar solo si necesitás panorama total).
        email_asesor: email que SABÉS que pertenece a un asesor. Acelera y evita auto-clasificar.
        email_cliente: email que SABÉS que pertenece a un cliente.
        solo_activas: si True, filtra emisiones con Estado == "Activa".
        limite: cap superior por categoría (default 100).
    """
    t0 = time.time()

    if modo not in MODOS_VALIDOS:
        modo = "completo"

    # ATAJO especial: si modo=cartera y tenemos email_asesor, ejecutar la pipeline
    # dedicada y retornar directo (no pasa por la maquinaria de búsqueda general).
    if modo == "cartera" and email_asesor:
        t_c0 = time.time()
        cartera = cartera_de_asesor(email_asesor)
        cartera["modo"] = "cartera"
        cartera["stats"]["tiempo_ms"] = int((time.time() - t_c0) * 1000)
        return cartera

    # 1. Combinar listas explícitas + extracción regex + email_asesor/cliente
    emails_in = list(emails or [])
    if email_asesor:
        emails_in.append(email_asesor)
    if email_cliente:
        emails_in.append(email_cliente)
    polizas_in = list(polizas or [])
    clientes_in = list(clientes or [])
    asesores_in = list(asesores or [])
    if mensaje:
        e_rx, p_rx, cli_rx, ase_rx = _extraer(mensaje)
        emails_in.extend(e_rx)
        polizas_in.extend(p_rx)
        clientes_in.extend(cli_rx)
        asesores_in.extend(ase_rx)

    emails_uniq = sorted({e.strip().lower() for e in emails_in if e})
    polizas_uniq = sorted({p.strip() for p in polizas_in if p})
    clientes_uniq = sorted({c.strip() for c in clientes_in if c})
    asesores_uniq = sorted({a.strip() for a in asesores_in if a})

    intents = _detectar_intents(mensaje)

    # 2. Definir incluir_set según modo
    if incluir is not None:
        # Si el caller mandó incluir explícito, lo respetamos
        incluir_set = set(incluir)
    else:
        if modo == "perfil":
            incluir_set = {"usuarios"}
        elif modo == "polizas":
            incluir_set = {"usuarios", "emisiones"}
            if polizas_uniq:
                incluir_set.add("cobranzas")
        elif modo == "clientes":
            incluir_set = {"usuarios"}  # los clientes se expanden en usuarios.expandido si es asesor
        elif modo == "cobranzas":
            incluir_set = {"cobranzas"}
            if emails_uniq or asesores_uniq:
                incluir_set.add("usuarios")
        elif modo == "eventos":
            incluir_set = {"usuarios", "calendly"}
        else:  # completo
            incluir_set = {"usuarios", "emisiones"}
            if clientes_uniq:
                incluir_set.add("clientes_por_nombre")
            if asesores_uniq:
                incluir_set.add("asesores_por_nombre")
                incluir_set.add("calendly")
            if polizas_uniq or intents["cobranza"]:
                incluir_set.add("cobranzas")
            if intents["tickets"]:
                incluir_set.add("tickets_allianz")
            if intents["calendly"]:
                incluir_set.add("calendly")

    # 2. Primera ola de queries (sin dependencias)
    tasks: Dict[str, Any] = {}
    queries_count = 0

    def submit(executor: ThreadPoolExecutor, name: str, fn, *args, **kwargs):
        nonlocal queries_count
        queries_count += 1
        tasks[name] = executor.submit(fn, *args, **kwargs)

    with ThreadPoolExecutor(max_workers=6) as ex:
        if "usuarios" in incluir_set and emails_uniq:
            submit(ex, "usuarios", nc.clasificar_usuarios_batch, emails_uniq)
            queries_count += 2  # son 3 totales (asesor/estud/cliente)
        if "emisiones" in incluir_set and (polizas_uniq or clientes_uniq or emails_uniq):
            submit(ex, "emisiones", nc.buscar_emisiones_batch, polizas_uniq, clientes_uniq, emails_uniq)
        if "cobranzas" in incluir_set and polizas_uniq:
            submit(ex, "cobranzas", nc.buscar_cobranzas_batch, polizas_uniq)
        if "tickets_allianz" in incluir_set:
            submit(ex, "tickets_allianz", nc.buscar_tickets_allianz_batch, None)
        if "clientes_por_nombre" in incluir_set and clientes_uniq:
            submit(ex, "clientes_por_nombre", nc.buscar_clientes_por_nombre_batch, clientes_uniq)
        if "asesores_por_nombre" in incluir_set and asesores_uniq:
            submit(ex, "asesores_por_nombre", nc.buscar_asesores_por_nombre_batch, asesores_uniq)

        results: Dict[str, Any] = {}
        for name, fut in tasks.items():
            try:
                results[name] = fut.result(timeout=120)
            except Exception as e:
                log.error("consulta %s falló: %s", name, e)
                results[name] = [] if name != "usuarios" else {}

    # 3. Segunda ola: Calendly depende de IDs de asesores
    asesor_ids: List[str] = []
    for a in (results.get("asesores_por_nombre") or []):
        if a.get("_id"):
            asesor_ids.append(a["_id"])

    # 3a. FALLBACK: si pidieron asesor pero no se encontró, intentar via Clientes
    # (la DB Clientes tiene la relation Asesor — buscamos al cliente y miramos su asesor)
    if asesores_uniq and not asesor_ids and clientes_uniq:
        try:
            queries_count += 1
            clientes_rows = nc.buscar_clientes_por_nombre_batch(clientes_uniq)
            for c in clientes_rows:
                rel = c.get("Asesor") or c.get("CRM Asesores") or []
                if isinstance(rel, list):
                    asesor_ids.extend([v for v in rel if isinstance(v, str) and len(v) >= 32])
            # también traer info de esos asesores
            if asesor_ids and not results.get("asesores_por_nombre"):
                ids_uniq = list({a for a in asesor_ids})
                # resolver names via pages.retrieve (cacheado en resolver)
                results["asesores_por_nombre"] = []
                for aid in ids_uniq:
                    p = nc._resolve_page_id(aid)
                    queries_count += 1
                    results["asesores_por_nombre"].append({"_id": aid, "Nombre Completo": p.get("name"), "_url": p.get("url")})
        except Exception as e:
            log.error("fallback cliente->asesor falló: %s", e)

    if "calendly" in incluir_set:
        try:
            queries_count += 1
            results["calendly"] = nc.buscar_calendly_batch(
                clientes=clientes_uniq or None,
                asesor_ids=asesor_ids or None,
            )
        except Exception as e:
            log.error("calendly falló: %s", e)
            results["calendly"] = []

    # 4. EXPANSIÓN de entidades principales: si el usuario es asesor o cliente,
    # traer datos completos (correo + nombre) de sus relaciones clave SIN cap.
    expansiones: Dict[str, Dict[str, Any]] = {}
    if results.get("usuarios"):
        for email_k, u in results["usuarios"].items():
            if not isinstance(u, dict) or u.get("tipo") == "prospecto":
                continue
            data = u.get("data") or {}
            tipo = u.get("tipo")
            exp: Dict[str, Any] = {}

            uid = data.get("_id")
            if tipo == "asesor" and uid:
                # Decisión por modo: qué expansiones disparar
                expandir_clientes = modo in ("completo", "clientes")
                expandir_emisiones = modo in ("completo", "polizas")
                expandir_eventos = modo in ("completo", "eventos")

                if expandir_clientes:
                    try:
                        clientes_agg = nc.clientes_completos_de_asesor(data)
                        queries_count += 1
                        exp["clientes"] = clientes_agg["lista_completa"][:limite]
                        exp["total_clientes"] = clientes_agg["total_unico"]
                        exp["clientes_por_fuente"] = clientes_agg["por_fuente"]
                        if clientes_agg["total_unico"] > limite:
                            exp["_clientes_truncados"] = True
                    except Exception as e:
                        log.error("clientes_completos_de_asesor falló: %s", e)
                if expandir_emisiones:
                    try:
                        emis_agg = nc.emisiones_completas_de_asesor(data)
                        queries_count += 1
                        emisiones_data = emis_agg["lista_completa"]
                        if solo_activas:
                            emisiones_data = [e for e in emisiones_data if e.get("estado") == "Activa"]
                        exp["emisiones"] = emisiones_data[:limite]
                        exp["total_emisiones"] = len(emisiones_data)
                    except Exception as e:
                        log.error("emisiones_completas_de_asesor falló: %s", e)
                if expandir_eventos:
                    try:
                        eventos = nc.eventos_calendly_de_asesor(uid)
                        queries_count += 1
                        ev_list = [{
                            "evento": e_.get("Evento ") or e_.get("Tipo de Evento"),
                            "fecha": (e_.get("Fecha de Evento") or {}).get("start"),
                            "invitado": e_.get("Nombre del invitado"),
                            "correo_invitado": e_.get("Correo invitado"),
                            "estado": e_.get("Estado"),
                            "url": e_.get("_url"),
                        } for e_ in eventos]
                        exp["eventos_calendly"] = ev_list[:limite]
                        exp["total_eventos"] = len(ev_list)
                    except Exception as e:
                        log.error("eventos_de_asesor falló: %s", e)

            elif tipo == "cliente" and uid:
                # Su asesor: usar pages.retrieve sobre el ID de relation
                ids_asesor = [v for v in (data.get("Asesor") or data.get("CRM Asesores") or []) if isinstance(v, str)]
                # Filtrar IDs que apuntan al propio cliente (data Notion sucia)
                ids_asesor = [v for v in ids_asesor if v != uid]
                if ids_asesor:
                    try:
                        ases_full = nc.expandir_ids_full(
                            ids_asesor,
                            extract_props=["_id", "_url", "Nombre Completo", "Correo", "Teléfono"],
                            max_ids=3,
                            max_workers=3,
                        )
                        exp["asesor"] = ases_full[0] if ases_full else None
                        queries_count += len(ases_full)
                    except Exception as e:
                        log.error("expandir asesor falló: %s", e)
                # Emisiones del cliente: 1 query por relation
                try:
                    emis = nc.emisiones_de_cliente(uid)
                    queries_count += 1
                    exp["emisiones"] = [{
                        "solicitud": e_.get("Solicitud"),
                        "poliza": e_.get("Número de Póliza"),
                        "prima": e_.get("Prima"),
                        "estado": e_.get("Estado"),
                        "fecha_emision": (e_.get("Fecha de Emisión") or {}).get("start"),
                        "url": e_.get("_url"),
                        "asesor": (e_.get("Asesor") or [{}])[0].get("name") if e_.get("Asesor") else None,
                        "correo_asesor": e_.get("Correo Asesor"),
                        "telefono_cliente": e_.get("Teléfono Cliente"),
                        "producto": e_.get("Producto (nombre)"),
                        "valor_plan": e_.get("Valor Plan"),
                        "plazo": e_.get("Plazo Comprometido"),
                        "conducto_cobro": e_.get("Conducto de cobro"),
                        "fecha_cobro_original": (e_.get("Fecha de Cobro Original") or {}).get("start"),
                        "notas": e_.get("Notas de Emisión"),
                    } for e_ in emis]
                    exp["total_emisiones"] = len(exp["emisiones"])
                    # Fallback: si cliente.Asesor está vacío, tomar la primera asesora de sus emisiones
                    if not exp.get("asesor") and exp["emisiones"]:
                        primer = next((e_ for e_ in emis if e_.get("Asesor")), None)
                        if primer:
                            asesor_rel = (primer.get("Asesor") or [{}])[0]
                            exp["asesor"] = {
                                "_id": asesor_rel.get("id"),
                                "_url": asesor_rel.get("url"),
                                "Nombre Completo": asesor_rel.get("name"),
                                "Correo": primer.get("Correo Asesor"),
                                "_source": "from_emision",
                            }
                except Exception as e:
                    log.error("emisiones_de_cliente falló: %s", e)

            if exp:
                expansiones[email_k] = exp

    # 5. Resolver relations -> {id, name, url} en cada categoría (cap normal)
    RELATIONS_BY_TYPE: Dict[str, List[str]] = {
        "emisiones": ["Asesor", "Cerrador", "Clientes General", "Cobranza", "Tickets Allianz", "Lanzamientos", "Producto"],
        "cobranzas": ["Asesores ", "Cerradores", "Líderes", "Emisiones"],
        "tickets_allianz": ["Clientes General", "Asesores ", "Cerradores"],
        "calendly": ["Asesores", "Clientes General", "CRM Asesores", "Cerradores ", "Líderes ", "Lanzamientos"],
        "clientes_por_nombre": ["Asesor", "CRM Asesores", "Tickets Allianz", "Eventos Calendly", "Tickets Babilonia"],
        "asesores_por_nombre": ["Líder", "Clientes General", "Eventos Calendly", "Líder "],
    }
    try:
        for cat, rels in RELATIONS_BY_TYPE.items():
            rows = results.get(cat)
            if isinstance(rows, list) and rows:
                nc.resolver_relaciones(rows, rels)
        # Resolver también en usuarios (que vienen de clasificar — son dicts con .data)
        if results.get("usuarios"):
            datas = [u.get("data") for u in results["usuarios"].values() if isinstance(u, dict) and u.get("data")]
            if datas:
                nc.resolver_relaciones(datas, ["Asesor", "CRM Asesores", "Líder", "Clientes General"])
    except Exception as e:
        log.error("resolver_relaciones falló: %s", e)

    # 3. Armar respuesta
    usuarios_map: Dict[str, Dict[str, Any]] = results.get("usuarios", {})
    usuarios: List[Dict[str, Any]] = []
    no_emails: List[str] = []
    for e in emails_uniq:
        u = usuarios_map.get(e)
        if u is None:
            continue
        if u.get("tipo") == "prospecto":
            no_emails.append(e)
        d = u.get("data") or {}
        # Nombres por tipo de DB
        nombre = (
            d.get("Nombre Completo")          # asesores
            or d.get("Nombre completo")        # estudiantes
            or d.get("Nombre del Cliente")     # clientes general
            or " ".join(filter(None, [d.get("Primer Nombre"), d.get("Apellido Paterno")]))
            or " ".join(filter(None, [d.get("Nombre(s)"), d.get("Apellido(s)")]))
            or None
        )
        usuarios.append({
            "email": e,
            "tipo": u["tipo"],
            "nombre": nombre.strip() if nombre else None,
            "telefono": d.get("Teléfono"),
            "data": d,
        })

    emisiones = results.get("emisiones", []) or []
    cobranzas = results.get("cobranzas", []) or []
    # Aplicar filtros adicionales (solo_activas + límite)
    if solo_activas:
        emisiones = [e for e in emisiones if e.get("Estado") == "Activa"]
    emisiones = emisiones[:limite]
    cobranzas = cobranzas[:limite]

    # Pólizas no encontradas: las que se pidieron y no aparecen en emisiones+cobranzas
    pols_encontradas = set()
    for r in emisiones + cobranzas:
        p = r.get("Póliza") or r.get("Numero de Póliza") or r.get("Numero")
        if isinstance(p, str):
            pols_encontradas.add(p.strip())
    no_polizas = [p for p in polizas_uniq if not any(p in pe for pe in pols_encontradas)]

    # Adjuntar expansiones a cada usuario
    for u in usuarios:
        exp = expansiones.get(u["email"])
        if exp:
            u["expandido"] = exp

    # Validaciones cross-source — corre sobre el resultado completo
    advertencias: List[Dict[str, Any]] = []
    try:
        advertencias = val.detectar({
            "usuarios": usuarios,
            "emisiones": emisiones,
            "cobranzas": cobranzas,
            "tickets_allianz": results.get("tickets_allianz", []) or [],
        })
    except Exception as e:
        log.error("validaciones falló: %s", e)

    elapsed = int((time.time() - t0) * 1000)
    return {
        "usuarios": usuarios,
        "emisiones": emisiones,
        "cobranzas": cobranzas,
        "tickets_allianz": results.get("tickets_allianz", []) or [],
        "calendly": results.get("calendly", []) or [],
        "clientes_por_nombre": results.get("clientes_por_nombre", []) or [],
        "asesores_por_nombre": results.get("asesores_por_nombre", []) or [],
        "no_encontrados": {
            "emails": no_emails,
            "polizas": no_polizas,
        },
        "advertencias": advertencias,
        "stats": {
            "tiempo_ms": elapsed,
            "queries_notion": queries_count,
            "emails_consultados": len(emails_uniq),
            "polizas_consultadas": len(polizas_uniq),
            "nombres_clientes": len(clientes_uniq),
            "nombres_asesores": len(asesores_uniq),
            "advertencias_total": len(advertencias),
            "advertencias_por_severidad": val.resumen_severidades(advertencias),
        },
    }

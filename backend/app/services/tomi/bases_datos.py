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


def consultar(
    mensaje: str = "",
    emails: Optional[List[str]] = None,
    polizas: Optional[List[str]] = None,
    clientes: Optional[List[str]] = None,
    asesores: Optional[List[str]] = None,
    incluir: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Orquesta las búsquedas en paralelo y devuelve el JSON estructurado."""
    t0 = time.time()

    # 1. Combinar listas explícitas + extracción regex
    emails_in = list(emails or [])
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

    # Qué consultas correr: si viene "incluir", respetar; sino, inferir
    if incluir is None:
        incluir_set = {"usuarios", "emisiones"}
        if clientes_uniq:
            incluir_set.add("clientes_por_nombre")
        if asesores_uniq:
            incluir_set.add("asesores_por_nombre")
            incluir_set.add("calendly")  # si pregunta por asesor, traer sus eventos
        if polizas_uniq or intents["cobranza"]:
            incluir_set.add("cobranzas")
        if intents["tickets"]:
            incluir_set.add("tickets_allianz")
        if intents["calendly"]:
            incluir_set.add("calendly")
    else:
        incluir_set = set(incluir)

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
                # Agregación COMPLETA: union forward (record) + backward (queries)
                try:
                    clientes_agg = nc.clientes_completos_de_asesor(data)
                    queries_count += 1
                    exp["clientes"] = clientes_agg["lista_completa"]
                    exp["total_clientes"] = clientes_agg["total_unico"]
                    exp["clientes_por_fuente"] = clientes_agg["por_fuente"]
                except Exception as e:
                    log.error("clientes_completos_de_asesor falló: %s", e)
                try:
                    emis_agg = nc.emisiones_completas_de_asesor(data)
                    queries_count += 1
                    exp["emisiones"] = emis_agg["lista_completa"]
                    exp["total_emisiones"] = emis_agg["total_unico"]
                except Exception as e:
                    log.error("emisiones_completas_de_asesor falló: %s", e)
                try:
                    eventos = nc.eventos_calendly_de_asesor(uid)
                    queries_count += 1
                    exp["eventos_calendly"] = [{
                        "evento": e_.get("Evento ") or e_.get("Tipo de Evento"),
                        "fecha": (e_.get("Fecha de Evento") or {}).get("start"),
                        "invitado": e_.get("Nombre del invitado"),
                        "correo_invitado": e_.get("Correo invitado"),
                        "estado": e_.get("Estado"),
                        "url": e_.get("_url"),
                    } for e_ in eventos]
                    exp["total_eventos"] = len(exp["eventos_calendly"])
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
        "stats": {
            "tiempo_ms": elapsed,
            "queries_notion": queries_count,
            "emails_consultados": len(emails_uniq),
            "polizas_consultadas": len(polizas_uniq),
            "nombres_clientes": len(clientes_uniq),
            "nombres_asesores": len(asesores_uniq),
        },
    }

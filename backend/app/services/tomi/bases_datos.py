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
# Pólizas tipo "Plus3-403328", "Vida-12345", "Auto-9876543"
RX_POLIZA = re.compile(r"\b[A-Za-z][A-Za-z0-9]*-\d{3,}\b")

KEYWORDS_TICKETS = (
    "siniestro", "denuncia", "tramite", "trámite", "queja", "reclamo",
    "endoso", "modificación", "modificacion", "renovación", "renovacion",
)
KEYWORDS_CALENDLY = ("turno", "agenda", "agendar", "reunión", "reunion", "cita", "calendly")
KEYWORDS_COBRANZA = ("cobranza", "pago", "saldo", "cuota", "vencimiento", "pagar", "debo")


def _extraer(mensaje: str) -> Tuple[List[str], List[str]]:
    """Devuelve (emails, polizas) extraídos del texto libre."""
    if not mensaje:
        return [], []
    emails = sorted({m.group(0).lower() for m in RX_EMAIL.finditer(mensaje)})
    polizas = sorted({m.group(0) for m in RX_POLIZA.finditer(mensaje)})
    return emails, polizas


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
    incluir: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Orquesta las búsquedas en paralelo y devuelve el JSON estructurado."""
    t0 = time.time()

    # 1. Combinar listas explícitas + extracción regex
    emails_in = list(emails or [])
    polizas_in = list(polizas or [])
    if mensaje:
        e_rx, p_rx = _extraer(mensaje)
        emails_in.extend(e_rx)
        polizas_in.extend(p_rx)
    emails_uniq = sorted({e.strip().lower() for e in emails_in if e})
    polizas_uniq = sorted({p.strip() for p in polizas_in if p})
    clientes_uniq = sorted({c.strip() for c in (clientes or []) if c})

    intents = _detectar_intents(mensaje)

    # Qué consultas correr: si viene "incluir", respetar; sino, inferir
    if incluir is None:
        incluir_set = {"usuarios", "emisiones"}
        if polizas_uniq or intents["cobranza"]:
            incluir_set.add("cobranzas")
        if intents["tickets"]:
            incluir_set.add("tickets_allianz")
        if intents["calendly"]:
            incluir_set.add("calendly")
    else:
        incluir_set = set(incluir)

    # 2. Ejecutar en paralelo (Notion API admite ~3 req/s — 4 paralelas está fino)
    tasks: Dict[str, Any] = {}
    queries_count = 0

    def submit(executor: ThreadPoolExecutor, name: str, fn, *args, **kwargs):
        nonlocal queries_count
        queries_count += 1
        tasks[name] = executor.submit(fn, *args, **kwargs)

    with ThreadPoolExecutor(max_workers=6) as ex:
        if "usuarios" in incluir_set and emails_uniq:
            # clasificar_usuarios_batch hace 3 queries internas (asesor/estud/cliente)
            submit(ex, "usuarios", nc.clasificar_usuarios_batch, emails_uniq)
            queries_count += 2  # 3 totales contando la inicial
        if "emisiones" in incluir_set and (polizas_uniq or clientes_uniq):
            submit(ex, "emisiones", nc.buscar_emisiones_batch, polizas_uniq, clientes_uniq)
        if "cobranzas" in incluir_set and polizas_uniq:
            submit(ex, "cobranzas", nc.buscar_cobranzas_batch, polizas_uniq)
        if "tickets_allianz" in incluir_set:
            # si hay keywords pero no listamos trámites específicos, traer últimos
            submit(ex, "tickets_allianz", nc.buscar_tickets_allianz_batch, None)
        if "calendly" in incluir_set:
            submit(ex, "calendly", nc.buscar_calendly_batch, clientes_uniq or None)

        results: Dict[str, Any] = {}
        for name, fut in tasks.items():
            try:
                results[name] = fut.result(timeout=120)
            except Exception as e:
                log.error("consulta %s falló: %s", name, e)
                results[name] = [] if name != "usuarios" else {}

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

    elapsed = int((time.time() - t0) * 1000)
    return {
        "usuarios": usuarios,
        "emisiones": emisiones,
        "cobranzas": cobranzas,
        "tickets_allianz": results.get("tickets_allianz", []) or [],
        "calendly": results.get("calendly", []) or [],
        "no_encontrados": {
            "emails": no_emails,
            "polizas": no_polizas,
        },
        "stats": {
            "tiempo_ms": elapsed,
            "queries_notion": queries_count,
            "emails_consultados": len(emails_uniq),
            "polizas_consultadas": len(polizas_uniq),
        },
    }

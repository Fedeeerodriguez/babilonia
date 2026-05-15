"""Cliente Notion deterministico para el sub-agente bases_datos de Tomi.

Reemplaza la version LLM-based del sub-agente en n8n (que tenia fluctuaciones)
con queries directas y predecibles a la API de Notion.

DBs (IDs configurables por env var — fallback a los IDs actuales de Babilonia):
  - NOTION_DB_ASESORES
  - NOTION_DB_ESTUDIANTES
  - NOTION_DB_CLIENTES
  - NOTION_DB_EMISIONES
  - NOTION_DB_COBRANZAS
  - NOTION_DB_TICKETS_ALLIANZ
  - NOTION_DB_TICKETS_BABILONIA
  - NOTION_DB_EVENTOS_CALENDLY
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from notion_client import Client
from notion_client.errors import APIResponseError

log = logging.getLogger("tomi.notion")

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")

DB_ASESORES = os.getenv("NOTION_DB_ASESORES", "")
DB_ESTUDIANTES = os.getenv("NOTION_DB_ESTUDIANTES", "")
DB_CLIENTES = os.getenv("NOTION_DB_CLIENTES", "")
DB_EMISIONES = os.getenv("NOTION_DB_EMISIONES", "")
DB_COBRANZAS = os.getenv("NOTION_DB_COBRANZAS", "")
DB_TICKETS_ALLIANZ = os.getenv("NOTION_DB_TICKETS_ALLIANZ", "")
DB_TICKETS_BABILONIA = os.getenv("NOTION_DB_TICKETS_BABILONIA", "")
DB_EVENTOS_CALENDLY = os.getenv("NOTION_DB_EVENTOS_CALENDLY", "")


def _client() -> Client:
    if not NOTION_TOKEN:
        raise RuntimeError("NOTION_TOKEN no configurado")
    return Client(auth=NOTION_TOKEN, log_level=logging.WARNING)


def _flatten_props(page: Dict[str, Any]) -> Dict[str, Any]:
    """Aplana las propiedades de una page de Notion a un dict simple."""
    out: Dict[str, Any] = {"_id": page.get("id"), "_url": page.get("url")}
    props = page.get("properties", {}) or {}
    for name, val in props.items():
        t = val.get("type")
        v: Any = None
        try:
            if t == "title":
                v = "".join(x.get("plain_text", "") for x in val.get("title", []))
            elif t == "rich_text":
                v = "".join(x.get("plain_text", "") for x in val.get("rich_text", []))
            elif t == "email":
                v = val.get("email")
            elif t == "phone_number":
                v = val.get("phone_number")
            elif t == "url":
                v = val.get("url")
            elif t == "number":
                v = val.get("number")
            elif t == "checkbox":
                v = val.get("checkbox")
            elif t == "select":
                v = (val.get("select") or {}).get("name")
            elif t == "status":
                v = (val.get("status") or {}).get("name")
            elif t == "multi_select":
                v = [o.get("name") for o in (val.get("multi_select") or [])]
            elif t == "date":
                d = val.get("date") or {}
                v = {"start": d.get("start"), "end": d.get("end")}
            elif t == "people":
                v = [
                    {"id": p.get("id"), "name": p.get("name")}
                    for p in (val.get("people") or [])
                ]
            elif t == "relation":
                v = [r.get("id") for r in (val.get("relation") or [])]
            elif t == "formula":
                f = val.get("formula") or {}
                v = f.get(f.get("type"))
            elif t == "rollup":
                r = val.get("rollup") or {}
                v = r.get(r.get("type"))
            elif t == "files":
                v = [
                    (f.get("file") or f.get("external") or {}).get("url")
                    for f in (val.get("files") or [])
                ]
            elif t == "created_time":
                v = val.get("created_time")
            elif t == "last_edited_time":
                v = val.get("last_edited_time")
            else:
                v = val.get(t)
        except Exception as e:
            log.warning("flatten prop %s falló: %s", name, e)
            v = None
        out[name] = v
    return out


def _query(
    db_id: str,
    filt: Optional[Dict[str, Any]] = None,
    page_size: int = 25,
) -> List[Dict[str, Any]]:
    if not db_id:
        return []
    try:
        kwargs: Dict[str, Any] = {"database_id": db_id, "page_size": page_size}
        if filt:
            kwargs["filter"] = filt
        resp = _client().databases.query(**kwargs)
        return [_flatten_props(p) for p in resp.get("results", [])]
    except APIResponseError as e:
        log.error("Notion query falló db=%s: %s", db_id, e)
        return []


# ---------- Búsquedas ----------

def buscar_asesor_por_email(email: str) -> List[Dict[str, Any]]:
    if not email:
        return []
    return _query(
        DB_ASESORES,
        {"or": [
            {"property": "Correo", "rich_text": {"contains": email}},
            {"property": "Correo Hotmart", "rich_text": {"contains": email}},
        ]},
    )


def buscar_estudiante_por_email(email: str) -> List[Dict[str, Any]]:
    if not email:
        return []
    return _query(
        DB_ESTUDIANTES,
        {"or": [
            {"property": "Correo", "rich_text": {"contains": email}},
            {"property": "Correo Zoom", "rich_text": {"contains": email}},
        ]},
    )


def buscar_cliente_por_email(email: str) -> List[Dict[str, Any]]:
    if not email:
        return []
    return _query(
        DB_CLIENTES,
        {"property": "Correo", "rich_text": {"contains": email}},
    )


def buscar_emisiones(
    cliente: Optional[str] = None,
    poliza: Optional[str] = None,
) -> List[Dict[str, Any]]:
    # NOTA: Esta DB requiere que la integración esté compartida. Los nombres
    # de propiedad pueden variar — ajustar cuando esté accesible.
    conds: List[Dict[str, Any]] = []
    if cliente:
        conds.append({"property": "Cliente", "title": {"contains": cliente}})
    if poliza:
        conds.append({"property": "Póliza", "title": {"contains": poliza}})
    if not conds:
        return []
    filt = conds[0] if len(conds) == 1 else {"and": conds}
    return _query(DB_EMISIONES, filt)


# ---------- Búsquedas batch (or filter Notion, 1 query por N items) ----------

def _or_contains(prop: str, ptype: str, values: List[str]) -> Optional[Dict[str, Any]]:
    """Construye filtro OR con `contains` sobre múltiples props del mismo tipo."""
    values = [v for v in (values or []) if v]
    if not values:
        return None
    if len(values) == 1:
        return {"property": prop, ptype: {"contains": values[0]}}
    return {"or": [{"property": prop, ptype: {"contains": v}} for v in values]}


def buscar_emisiones_batch(
    polizas: Optional[List[str]] = None,
    clientes: Optional[List[str]] = None,
    page_size: int = 100,
) -> List[Dict[str, Any]]:
    polizas = [p for p in (polizas or []) if p]
    clientes = [c for c in (clientes or []) if c]
    if not polizas and not clientes:
        return []
    or_conds: List[Dict[str, Any]] = []
    or_conds += [{"property": "Póliza", "title": {"contains": p}} for p in polizas]
    or_conds += [{"property": "Cliente", "title": {"contains": c}} for c in clientes]
    filt = or_conds[0] if len(or_conds) == 1 else {"or": or_conds}
    return _query(DB_EMISIONES, filt, page_size=page_size)


def buscar_cobranzas_batch(
    polizas: List[str], page_size: int = 100,
) -> List[Dict[str, Any]]:
    f = _or_contains("Póliza", "title", polizas)
    if not f:
        return []
    return _query(DB_COBRANZAS, f, page_size=page_size)


def buscar_tickets_allianz_batch(
    tramites: Optional[List[str]] = None, page_size: int = 50,
) -> List[Dict[str, Any]]:
    f = _or_contains("Nombre del Trámite", "title", tramites or [])
    return _query(DB_TICKETS_ALLIANZ, f, page_size=page_size)


def buscar_calendly_batch(
    clientes: Optional[List[str]] = None, page_size: int = 50,
) -> List[Dict[str, Any]]:
    f = _or_contains("Nombre del invitado", "rich_text", clientes or [])
    return _query(DB_EVENTOS_CALENDLY, f, page_size=page_size)


# Mapeo de DB -> [(propiedad_email, tipo_propiedad)] para clasificar
EMAIL_PROPS: Dict[str, List[tuple]] = {
    "asesor": [("Correo", "rich_text"), ("Correo Hotmart", "rich_text")],
    "estudiante": [("Correo", "rich_text"), ("Correo Zoom", "rich_text")],
    "cliente": [("Correo", "rich_text")],
}


def _filtro_emails(emails: List[str], tipo: str) -> Optional[Dict[str, Any]]:
    """OR de contains sobre todas las props email de la DB para cada email a buscar."""
    if not emails:
        return None
    conds: List[Dict[str, Any]] = []
    for prop, ptype in EMAIL_PROPS[tipo]:
        for e in emails:
            conds.append({"property": prop, ptype: {"contains": e}})
    return conds[0] if len(conds) == 1 else {"or": conds}


def _email_de_row(row: Dict[str, Any], tipo: str) -> Optional[str]:
    """Extrae el primer email no vacío de las props email de la row."""
    for prop, _ in EMAIL_PROPS[tipo]:
        v = row.get(prop)
        if v and isinstance(v, str) and "@" in v:
            return v.strip().lower()
    return None


def clasificar_usuarios_batch(emails: List[str]) -> Dict[str, Dict[str, Any]]:
    """Para cada email devuelve {email: {tipo, data}}. 3 queries Notion totales."""
    emails = list({e.strip().lower() for e in (emails or []) if e and "@" in e})
    if not emails:
        return {}

    db_map = [
        ("asesor", DB_ASESORES),
        ("estudiante", DB_ESTUDIANTES),
        ("cliente", DB_CLIENTES),
    ]

    indices: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for tipo, db_id in db_map:
        rows = _query(db_id, _filtro_emails(emails, tipo))
        idx: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            row_email = _email_de_row(r, tipo)
            if row_email:
                idx[row_email] = {"tipo": tipo, "data": r}
        indices[tipo] = idx

    result: Dict[str, Dict[str, Any]] = {}
    for e in emails:
        if e in indices["asesor"]:
            result[e] = indices["asesor"][e]
        elif e in indices["estudiante"]:
            result[e] = indices["estudiante"][e]
        elif e in indices["cliente"]:
            result[e] = indices["cliente"][e]
        else:
            result[e] = {"tipo": "prospecto", "data": None}
    return result


def buscar_cobranzas_por_poliza(poliza: str) -> List[Dict[str, Any]]:
    if not poliza:
        return []
    return _query(
        DB_COBRANZAS,
        {"property": "Póliza", "title": {"contains": poliza}},
    )


def buscar_tickets_allianz(tramite: Optional[str] = None) -> List[Dict[str, Any]]:
    if tramite:
        filt = {"property": "Nombre del Trámite", "title": {"contains": tramite}}
    else:
        filt = None
    return _query(DB_TICKETS_ALLIANZ, filt, page_size=10)


def buscar_tickets_babilonia(limit: int = 10) -> List[Dict[str, Any]]:
    return _query(DB_TICKETS_BABILONIA, None, page_size=limit)


def buscar_eventos_calendly(
    cliente: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    filt = None
    if cliente:
        filt = {"or": [
            {"property": "Nombre del invitado", "rich_text": {"contains": cliente}},
            {"property": "Correo invitado", "rich_text": {"contains": cliente}},
        ]}
    return _query(DB_EVENTOS_CALENDLY, filt, page_size=limit)


def clasificar_usuario_por_email(email: str) -> Dict[str, Any]:
    """Devuelve {tipo, data} donde tipo ∈ asesor|estudiante|cliente|prospecto."""
    if not email:
        return {"tipo": "prospecto", "data": None}
    asesor = buscar_asesor_por_email(email)
    if asesor:
        return {"tipo": "asesor", "data": asesor[0]}
    estudiante = buscar_estudiante_por_email(email)
    if estudiante:
        return {"tipo": "estudiante", "data": estudiante[0]}
    cliente = buscar_cliente_por_email(email)
    if cliente:
        return {"tipo": "cliente", "data": cliente[0]}
    return {"tipo": "prospecto", "data": None}

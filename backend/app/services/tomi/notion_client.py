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
        {"property": "Correo electrónico", "email": {"equals": email}},
    )


def buscar_estudiante_por_email(email: str) -> List[Dict[str, Any]]:
    if not email:
        return []
    return _query(
        DB_ESTUDIANTES,
        {"property": "Correo electrónico", "email": {"equals": email}},
    )


def buscar_cliente_por_email(email: str) -> List[Dict[str, Any]]:
    if not email:
        return []
    return _query(
        DB_CLIENTES,
        {"property": "Correo electrónico", "email": {"equals": email}},
    )


def buscar_emisiones(
    cliente: Optional[str] = None,
    poliza: Optional[str] = None,
) -> List[Dict[str, Any]]:
    conds: List[Dict[str, Any]] = []
    if cliente:
        conds.append({"property": "Cliente", "title": {"contains": cliente}})
    if poliza:
        conds.append({"property": "Póliza", "rich_text": {"contains": poliza}})
    if not conds:
        return []
    filt = conds[0] if len(conds) == 1 else {"and": conds}
    return _query(DB_EMISIONES, filt)


def buscar_cobranzas_por_poliza(poliza: str) -> List[Dict[str, Any]]:
    if not poliza:
        return []
    return _query(
        DB_COBRANZAS,
        {"property": "Póliza", "rich_text": {"contains": poliza}},
    )


def buscar_tickets_allianz(tramite: Optional[str] = None) -> List[Dict[str, Any]]:
    if tramite:
        filt = {"property": "Trámite", "title": {"contains": tramite}}
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
        filt = {"property": "Nombre", "title": {"contains": cliente}}
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

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

from app.services.tomi.cache import notion_cache, hash_key

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

# Sub-DBs de clientes por producto
DB_CLIENTES_AUTO = os.getenv("NOTION_DB_CLIENTES_AUTO", "")
DB_CLIENTES_PATRIMONIAL = os.getenv("NOTION_DB_CLIENTES_PATRIMONIAL", "")
DB_CLIENTES_EDUCACIONAL = os.getenv("NOTION_DB_CLIENTES_EDUCACIONAL", "")
DB_CLIENTES_GMM = os.getenv("NOTION_DB_CLIENTES_GMM", "")
DB_CLIENTES_RENTAS_PRIVADAS = os.getenv("NOTION_DB_CLIENTES_RENTAS_PRIVADAS", "")
DB_CLIENTES_RESIDENCIAL = os.getenv("NOTION_DB_CLIENTES_RESIDENCIAL", "")
DB_CLIENTES_PROTECCION = os.getenv("NOTION_DB_CLIENTES_PROTECCION", "")
DB_CLIENTES_ELITE = os.getenv("NOTION_DB_CLIENTES_ELITE", "")
DB_CLIENTES_PLU3 = os.getenv("NOTION_DB_CLIENTES_PLU3", "")
DB_MIGRACION_CLIENTES = os.getenv("NOTION_DB_MIGRACION_CLIENTES", "")
DB_PORTAFOLIOS = os.getenv("NOTION_DB_PORTAFOLIOS", "")

# DBs adicionales (Allianz) descubiertas vía scan de relaciones
DB_RENOVACIONES = os.getenv("NOTION_DB_RENOVACIONES", "")
DB_SINIESTROS = os.getenv("NOTION_DB_SINIESTROS", "")
DB_COMISIONES_AGENTES = os.getenv("NOTION_DB_COMISIONES_AGENTES", "")
DB_BONOS_AGENTES = os.getenv("NOTION_DB_BONOS_AGENTES", "")
DB_BONOS_PROMOTORIA = os.getenv("NOTION_DB_BONOS_PROMOTORIA", "")
DB_MES_13_PLU3 = os.getenv("NOTION_DB_MES_13_PLU3", "")
DB_PUNTOS_CONVENCION = os.getenv("NOTION_DB_PUNTOS_CONVENCION", "")
DB_PRODUCTOS = os.getenv("NOTION_DB_PRODUCTOS", "")
DB_CLIENTES_PPR = os.getenv("NOTION_DB_CLIENTES_PPR", "")
DB_MIGRACION_CARTERA = os.getenv("NOTION_DB_MIGRACION_CARTERA", "")

# Mapeo nombre amigable -> DB ID, usado por endpoint debug y búsqueda multi-DB
SUB_DBS_CLIENTES: Dict[str, str] = {
    "clientes_general": DB_CLIENTES,
    "clientes_auto": DB_CLIENTES_AUTO,
    "clientes_patrimonial": DB_CLIENTES_PATRIMONIAL,
    "clientes_educacional": DB_CLIENTES_EDUCACIONAL,
    "clientes_gmm": DB_CLIENTES_GMM,
    "clientes_rentas_privadas": DB_CLIENTES_RENTAS_PRIVADAS,
    "clientes_residencial": DB_CLIENTES_RESIDENCIAL,
    "clientes_proteccion": DB_CLIENTES_PROTECCION,
    "clientes_elite": DB_CLIENTES_ELITE,
    "clientes_plu3": DB_CLIENTES_PLU3,
    "migracion_clientes": DB_MIGRACION_CLIENTES,
}


def _client() -> Client:
    if not NOTION_TOKEN:
        raise RuntimeError("NOTION_TOKEN no configurado")
    return Client(auth=NOTION_TOKEN, log_level=logging.WARNING)


def _retry_429(fn, *args, max_attempts: int = 4, **kwargs):
    """Wrapper con backoff exponencial ante rate-limit de Notion (429)."""
    import time as _t
    delay = 1.0
    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except APIResponseError as e:
            if getattr(e, "status", None) == 429 or "rate" in str(e).lower():
                log.warning("Notion 429 — retry %d/%d en %.1fs", attempt + 1, max_attempts, delay)
                _t.sleep(delay)
                delay *= 2
                continue
            raise
        except Exception as e:
            if "rate" in str(e).lower() or "429" in str(e):
                _t.sleep(delay)
                delay *= 2
                continue
            raise
    return fn(*args, **kwargs)  # último intento sin catch


def _flatten_props(page: Dict[str, Any]) -> Dict[str, Any]:
    """Aplana las propiedades de una page de Notion a un dict simple."""
    out: Dict[str, Any] = {"_id": page.get("id"), "_url": page.get("url"), "_title": None}
    props = page.get("properties", {}) or {}
    for name, val in props.items():
        t = val.get("type")
        v: Any = None
        try:
            if t == "title":
                v = "".join(x.get("plain_text", "") for x in val.get("title", []))
                out["_title"] = v  # siempre disponible bajo _title
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


def _page_title(page: Dict[str, Any]) -> Optional[str]:
    """Extrae el title de una page Notion."""
    for _, v in (page.get("properties") or {}).items():
        if v.get("type") == "title":
            return "".join(x.get("plain_text", "") for x in v.get("title", []))
    return None


def _resolve_page_id(page_id: str) -> Dict[str, Any]:
    """Devuelve {id, name, url} de una page por ID. Con retry 429 + caché."""
    cache_key = f"page_id:{page_id}"
    cached_val = notion_cache.get(cache_key)
    if cached_val is not None:
        return cached_val
    try:
        page = _retry_429(_client().pages.retrieve, page_id=page_id)
        result = {
            "id": page_id,
            "name": _page_title(page),
            "url": page.get("url"),
        }
        notion_cache.set(cache_key, result)
        return result
    except Exception as e:
        log.debug("resolve_page falló id=%s: %s", page_id, e)
        return {"id": page_id, "name": None, "url": None}


def _resolve_page_full(page_id: str, extract_props: Optional[List[str]] = None) -> Dict[str, Any]:
    """Devuelve la page completamente flattened + props seleccionadas si se piden."""
    # Cachear el page completo (sin filtrar props — el filtrado es trivial)
    cache_key = f"page_full:{page_id}"
    cached_full = notion_cache.get(cache_key)
    if cached_full is None:
        try:
            page = _retry_429(_client().pages.retrieve, page_id=page_id)
            cached_full = _flatten_props(page)
            notion_cache.set(cache_key, cached_full)
        except Exception as e:
            log.debug("resolve_page_full falló id=%s: %s", page_id, e)
            return {"_id": page_id, "name": None}
    if extract_props:
        return {k: v for k, v in cached_full.items() if k in extract_props or k.startswith("_")}
    return cached_full


def expandir_ids_full(
    ids: List[str],
    extract_props: Optional[List[str]] = None,
    max_ids: int = 100,
    max_workers: int = 15,
) -> List[Dict[str, Any]]:
    """Resuelve N IDs en paralelo con datos completos (subset de props si se pide)."""
    ids = [v for v in (ids or []) if isinstance(v, str) and len(v) >= 32]
    if not ids:
        return []
    ids = ids[:max_ids]
    from concurrent.futures import ThreadPoolExecutor
    out: List[Dict[str, Any]] = [None] * len(ids)  # type: ignore
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_resolve_page_full, pid, extract_props): i for i, pid in enumerate(ids)}
        for fut in futs:
            i = futs[fut]
            try:
                out[i] = fut.result(timeout=15)
            except Exception:
                out[i] = {"_id": ids[i], "name": None}
    return [r for r in out if r]


def resolver_relaciones(
    rows: List[Dict[str, Any]],
    relations: List[str],
    max_workers: int = 4,
    max_ids_total: int = 40,
    max_per_relation_per_row: int = 3,
) -> List[Dict[str, Any]]:
    """In-place: reemplaza los IDs de las relations indicadas por {id, name, url}.

    Eficiente: junta todos los IDs únicos de todas las rows, los resuelve en paralelo
    una sola vez, y rellena. Ignora props inexistentes.

    Limita:
      - max_per_relation_per_row: por row, solo resuelve los primeros N IDs de cada relation
        (los demás quedan como string ID — el LLM ya tiene los principales).
      - max_ids_total: cap absoluto en cantidad de page fetches (protege latencia).
    """
    if not rows:
        return rows
    all_ids: set = set()
    truncated: Dict[id, Dict[str, int]] = {}  # row_idx -> {prop: cant_truncada}
    for row in rows:
        for prop in relations:
            ids = row.get(prop)
            if isinstance(ids, list):
                head = ids[:max_per_relation_per_row]
                for v in head:
                    if isinstance(v, str) and len(v) >= 32:
                        all_ids.add(v)
                        if len(all_ids) >= max_ids_total:
                            break
            if len(all_ids) >= max_ids_total:
                break
        if len(all_ids) >= max_ids_total:
            break
    if not all_ids:
        return rows
    from concurrent.futures import ThreadPoolExecutor
    cache: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_resolve_page_id, pid): pid for pid in all_ids}
        for fut in futs:
            pid = futs[fut]
            try:
                cache[pid] = fut.result(timeout=15)
            except Exception:
                cache[pid] = {"id": pid, "name": None, "url": None}
    for row in rows:
        for prop in relations:
            ids = row.get(prop)
            if isinstance(ids, list):
                row[prop] = [
                    cache.get(v, {"id": v, "name": None, "url": None})
                    if isinstance(v, str) and len(v) >= 32 and v in cache
                    else (v if isinstance(v, dict) else {"id": v, "name": None, "url": None})
                    for v in ids[:max_per_relation_per_row]
                ]
                if len(ids) > max_per_relation_per_row:
                    row[f"_{prop}_total"] = len(ids)
    return rows


def _query(
    db_id: str,
    filt: Optional[Dict[str, Any]] = None,
    page_size: int = 25,
) -> List[Dict[str, Any]]:
    if not db_id:
        return []
    cache_key = f"query:{hash_key(db_id, filt, page_size)}"
    cached_val = notion_cache.get(cache_key)
    if cached_val is not None:
        return cached_val
    try:
        kwargs: Dict[str, Any] = {"database_id": db_id, "page_size": page_size}
        if filt:
            kwargs["filter"] = filt
        resp = _retry_429(_client().databases.query, **kwargs)
        result = [_flatten_props(p) for p in resp.get("results", [])]
        notion_cache.set(cache_key, result)
        return result
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
    conds: List[Dict[str, Any]] = []
    if cliente:
        conds.append({"property": "Nombre Cliente", "rich_text": {"contains": cliente}})
    if poliza:
        conds.append({"property": "Número de Póliza", "rich_text": {"contains": poliza}})
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
    emails: Optional[List[str]] = None,
    page_size: int = 100,
) -> List[Dict[str, Any]]:
    polizas = [p for p in (polizas or []) if p]
    clientes = [c for c in (clientes or []) if c]
    emails = [e for e in (emails or []) if e and "@" in e]
    if not polizas and not clientes and not emails:
        return []
    or_conds: List[Dict[str, Any]] = []
    or_conds += [{"property": "Número de Póliza", "rich_text": {"contains": p}} for p in polizas]
    or_conds += [{"property": "Nombre Cliente", "rich_text": {"contains": c}} for c in clientes]
    # buscar por email del cliente, asesor o cerrador
    for e in emails:
        or_conds.append({"property": "Correo Cliente", "rich_text": {"contains": e}})
        or_conds.append({"property": "Correo Asesor", "rich_text": {"contains": e}})
        or_conds.append({"property": "Correo Cerrador", "rich_text": {"contains": e}})
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
    clientes: Optional[List[str]] = None,
    asesor_ids: Optional[List[str]] = None,
    page_size: int = 50,
) -> List[Dict[str, Any]]:
    """Filtra Calendly por nombre/correo del invitado y/o por IDs de Asesor (relación)."""
    clientes = [c for c in (clientes or []) if c]
    asesor_ids = [a for a in (asesor_ids or []) if a]
    or_conds: List[Dict[str, Any]] = []
    for c in clientes:
        or_conds.append({"property": "Nombre del invitado", "rich_text": {"contains": c}})
        or_conds.append({"property": "Correo invitado", "rich_text": {"contains": c}})
    for aid in asesor_ids:
        # Asesores es relation - filtrar por contains de page id
        or_conds.append({"property": "Asesores", "relation": {"contains": aid}})
    if not or_conds:
        return _query(DB_EVENTOS_CALENDLY, None, page_size=page_size)
    filt = or_conds[0] if len(or_conds) == 1 else {"or": or_conds}
    return _query(DB_EVENTOS_CALENDLY, filt, page_size=page_size)


def buscar_asesores_por_nombre_batch(
    nombres: List[str], page_size: int = 50,
) -> List[Dict[str, Any]]:
    """Busca asesores por título Nombre Completo + Primer/Segundo/Apellidos."""
    nombres = [n for n in (nombres or []) if n and len(n.strip()) >= 2]
    if not nombres:
        return []
    or_conds: List[Dict[str, Any]] = []
    for n in nombres:
        or_conds.append({"property": "Nombre Completo", "title": {"contains": n}})
        or_conds.append({"property": "Primer Nombre", "rich_text": {"contains": n}})
        or_conds.append({"property": "Apellido Paterno", "rich_text": {"contains": n}})
        or_conds.append({"property": "Apellido Materno", "rich_text": {"contains": n}})
    filt = or_conds[0] if len(or_conds) == 1 else {"or": or_conds}
    return _query(DB_ASESORES, filt, page_size=page_size)


def buscar_clientes_por_nombre_batch(
    nombres: List[str], page_size: int = 50,
) -> List[Dict[str, Any]]:
    """Busca clientes por título Nombre del Cliente."""
    nombres = [n for n in (nombres or []) if n and len(n.strip()) >= 2]
    if not nombres:
        return []
    f = _or_contains("Nombre del Cliente", "title", nombres)
    return _query(DB_CLIENTES, f, page_size=page_size)


def clientes_de_asesor(asesor_id: str, page_size: int = 100) -> List[Dict[str, Any]]:
    """1 sola query: clientes donde Asesor.relation contiene asesor_id."""
    if not asesor_id:
        return []
    return _query(
        DB_CLIENTES,
        {"property": "Asesor", "relation": {"contains": asesor_id}},
        page_size=page_size,
    )


def emisiones_de_asesor(asesor_id: str, page_size: int = 100) -> List[Dict[str, Any]]:
    """Emisiones donde Asesor.relation contiene asesor_id."""
    if not asesor_id:
        return []
    return _query(
        DB_EMISIONES,
        {"property": "Asesor", "relation": {"contains": asesor_id}},
        page_size=page_size,
    )


def emisiones_de_cliente(cliente_id: str, page_size: int = 100) -> List[Dict[str, Any]]:
    """Emisiones donde Clientes General.relation contiene cliente_id."""
    if not cliente_id:
        return []
    return _query(
        DB_EMISIONES,
        {"property": "Clientes General", "relation": {"contains": cliente_id}},
        page_size=page_size,
    )


def eventos_calendly_de_asesor(asesor_id: str, page_size: int = 100) -> List[Dict[str, Any]]:
    """Calendly donde Asesores.relation contiene asesor_id."""
    if not asesor_id:
        return []
    return _query(
        DB_EVENTOS_CALENDLY,
        {"property": "Asesores", "relation": {"contains": asesor_id}},
        page_size=page_size,
    )


def emisiones_por_correo_asesor(email_asesor: str, page_size: int = 100) -> List[Dict[str, Any]]:
    """Emisiones (todos los productos: PLU3, VIPP, GMM, Auto, etc.) donde
    el campo Correo Asesor contiene el email indicado (case-insensitive)."""
    if not email_asesor:
        return []
    e_norm = email_asesor.strip().lower()
    # Buscamos contains case-insensitive haciendo 2 variantes (lower y upper).
    # Notion rich_text contains es case-insensitive en práctica pero algunos
    # registros guardan ZULEMAROMERO37@GMAIL.COM en mayúscula.
    return _query(
        DB_EMISIONES,
        {"property": "Correo Asesor", "rich_text": {"contains": e_norm}},
        page_size=page_size,
    )


def emisiones_por_correo_cliente(email_cliente: str, page_size: int = 100) -> List[Dict[str, Any]]:
    """Emisiones donde Correo Cliente contiene el email indicado."""
    if not email_cliente:
        return []
    return _query(
        DB_EMISIONES,
        {"property": "Correo Cliente", "rich_text": {"contains": email_cliente.strip().lower()}},
        page_size=page_size,
    )


def resolver_portafolios(portafolio_ids: List[str], max_workers: int = 4) -> Dict[str, str]:
    """Resuelve N IDs de portafolios a {id: nombre}. Usa el resolver con caché.

    Devuelve dict {page_id: nombre_fondo} (ej. {'abc...': 'Nasdaq 100'}).
    """
    portafolio_ids = [p for p in (portafolio_ids or []) if isinstance(p, str) and len(p) >= 32]
    if not portafolio_ids:
        return {}
    out: Dict[str, str] = {}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_resolve_page_id, pid): pid for pid in portafolio_ids}
        for fut in futs:
            pid = futs[fut]
            try:
                page = fut.result(timeout=15)
                out[pid] = page.get("name") or "(sin nombre)"
            except Exception:
                out[pid] = "(error)"
    return out


# ---------- Agregaciones cross-relacion (UNIÓN exacta, deduplicada) ----------

def _expandir_ids_a_clientes(ids: List[str]) -> List[Dict[str, Any]]:
    """Expande una lista de IDs (clientes pueden estar en distintas DBs:
    Clientes General, Clientes Auto, Clientes Patrimonial, etc.).
    No filtramos props — dejamos pasar todo y el renderer prioriza _title."""
    rows = expandir_ids_full(
        ids,
        extract_props=None,  # traer TODAS las propiedades
        max_ids=500,
        max_workers=4,
    )
    return rows


def clientes_completos_de_asesor(
    asesor_record: Dict[str, Any],
) -> Dict[str, Any]:
    """Une TODAS las relaciones que vinculan un asesor a clientes:
    - Forward: las relations en el record del asesor (Clientes General, etc.)
    - Backward: Clientes donde Asesor/CRM Asesores contiene su ID.

    Retorna: {total_unico, por_fuente, lista_completa, ids}. La lista_completa
    tiene cada cliente UNA SOLA VEZ con datos reales (no IDs).
    """
    asesor_id = asesor_record.get("_id")
    if not asesor_id:
        return {"total_unico": 0, "por_fuente": {}, "lista_completa": [], "ids": []}

    # 1. Forward: IDs en el record del asesor
    forward_props = [
        "Clientes General",
        "Clientes ",            # con espacio — existe en el schema
        "Clientes - Acompañados",
        "Migración de Clientes",
    ]
    forward_ids: List[str] = []
    by_field: Dict[str, int] = {}
    for prop in forward_props:
        ids = asesor_record.get(prop) or []
        if isinstance(ids, list):
            valid = [v for v in ids if isinstance(v, str) and len(v) >= 32]
            forward_ids.extend(valid)
            by_field[prop] = len(valid)

    # 2. Backward: query Clientes General donde Asesor/CRM Asesores contiene este asesor
    backward_rows: List[Dict[str, Any]] = []
    try:
        backward_rows = _query(
            DB_CLIENTES,
            {"or": [
                {"property": "Asesor", "relation": {"contains": asesor_id}},
                {"property": "CRM Asesores", "relation": {"contains": asesor_id}},
            ]},
            page_size=200,
        )
    except Exception as e:
        log.error("backward query clientes falló: %s", e)

    backward_ids = [r.get("_id") for r in backward_rows if r.get("_id")]

    # 3. Unir, dedupe, expandir los forward_ids que no aparezcan en backward
    backward_set = set(backward_ids)
    forward_set = set(forward_ids)
    union_ids = sorted(forward_set | backward_set)

    # Los backward ya vienen expandidos; los forward que no están en backward → expandir
    extra_ids = list(forward_set - backward_set)
    extra_rows = _expandir_ids_a_clientes(extra_ids) if extra_ids else []

    # Indexar por _id
    by_id: Dict[str, Dict[str, Any]] = {}
    for r in backward_rows + extra_rows:
        rid = r.get("_id")
        if rid:
            by_id[rid] = r

    lista_completa: List[Dict[str, Any]] = []
    for cid in union_ids:
        r = by_id.get(cid, {"_id": cid})
        # Nombre: priorizar Nombre del Cliente (Clientes General) y caer a _title (otras DBs)
        nombre = r.get("Nombre del Cliente") or r.get("Nombre Cliente") or r.get("Nombre completo") or r.get("_title")
        # DB de origen: la podemos inferir buscando qué propiedades únicas tiene
        db_origen = None
        if "Nombre del Cliente" in r:
            db_origen = "Clientes General"
        elif r.get("_title") is not None:
            db_origen = "Otra DB de clientes (Auto/Patrimonial/Migración/etc.)"
        lista_completa.append({
            "id": cid,
            "nombre": nombre,
            "correo": r.get("Correo") or r.get("Correo Cliente"),
            "telefono": r.get("Teléfono") or r.get("Teléfono Cliente"),
            "url": r.get("_url"),
            "tiene_asesor_asignado": cid in backward_set,
            "db_origen": db_origen,
        })

    return {
        "total_unico": len(union_ids),
        "por_fuente": {
            "forward_record_asesor": by_field,
            "backward_clientes_asesor": len(backward_ids),
            "total_forward_unico": len(forward_set),
            "total_backward_unico": len(backward_set),
            "interseccion": len(forward_set & backward_set),
            "solo_forward": len(forward_set - backward_set),
            "solo_backward": len(backward_set - forward_set),
        },
        "lista_completa": lista_completa,
        "ids": union_ids,
    }


def buscar_cliente_en_todas_dbs(
    email: Optional[str] = None,
    nombre: Optional[str] = None,
    max_per_db: int = 5,
) -> List[Dict[str, Any]]:
    """Busca en TODAS las sub-DBs de clientes (Auto, Patrimonial, etc.) en paralelo.
    Devuelve matches con `_db_origen` marcado para cada uno."""
    if not email and not nombre:
        return []
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def query_one(db_name: str, db_id: str) -> List[Dict[str, Any]]:
        if not db_id:
            return []
        # Construir filtro: probar Correo, Correo Cliente (rich_text) y title contains nombre
        or_conds: List[Dict[str, Any]] = []
        if email:
            or_conds.append({"property": "Correo", "rich_text": {"contains": email}})
            or_conds.append({"property": "Correo Cliente", "rich_text": {"contains": email}})
        if nombre:
            # title varía entre DBs — usamos el endpoint que no asume nombre fijo:
            # primero query genérica luego filtramos por _title
            pass
        filt: Optional[Dict[str, Any]] = None
        if or_conds:
            filt = or_conds[0] if len(or_conds) == 1 else {"or": or_conds}
        try:
            rows = _query(db_id, filt, page_size=max_per_db)
            # Si tenemos nombre y no email, filtrar por _title contains (case-insensitive)
            if nombre and not email:
                nlow = nombre.lower()
                rows = [r for r in rows if (r.get("_title") or "").lower().find(nlow) >= 0]
            for r in rows:
                r["_db_origen"] = db_name
            return rows
        except Exception as e:
            log.debug("query db %s falló (puede no estar compartida): %s", db_name, e)
            return []

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(query_one, n, d): n for n, d in SUB_DBS_CLIENTES.items() if d}
        for fut in as_completed(futs):
            try:
                results.extend(fut.result(timeout=30))
            except Exception:
                pass
    return results


def emisiones_completas_de_asesor(asesor_record: Dict[str, Any]) -> Dict[str, Any]:
    """Union de emisiones: forward (IDs en record) + backward (Asesor.contains)."""
    asesor_id = asesor_record.get("_id")
    if not asesor_id:
        return {"total_unico": 0, "lista_completa": []}
    # Backward
    backward = []
    try:
        backward = _query(
            DB_EMISIONES,
            {"property": "Asesor", "relation": {"contains": asesor_id}},
            page_size=200,
        )
    except Exception as e:
        log.error("emisiones backward falló: %s", e)
    backward_set = {r.get("_id") for r in backward if r.get("_id")}

    # Forward: Emisiones en el record + Emisiones 1
    forward_ids: List[str] = []
    for prop in ("Emisiones", "Emisiones 1"):
        ids = asesor_record.get(prop) or []
        if isinstance(ids, list):
            forward_ids.extend([v for v in ids if isinstance(v, str) and len(v) >= 32])
    forward_set = set(forward_ids)
    extra = forward_set - backward_set
    extra_rows = []
    if extra:
        extra_rows = expandir_ids_full(
            list(extra),
            extract_props=["_id", "_url", "Solicitud", "Número de Póliza", "Nombre Cliente",
                           "Correo Cliente", "Prima", "Estado", "Fecha de Emisión", "Producto (nombre)"],
            max_ids=200,
        )

    by_id: Dict[str, Dict[str, Any]] = {}
    for r in backward + extra_rows:
        rid = r.get("_id")
        if rid:
            by_id[rid] = r

    union = sorted(backward_set | forward_set)
    lista = []
    for eid in union:
        r = by_id.get(eid, {"_id": eid})
        lista.append({
            "id": eid,
            "solicitud": r.get("Solicitud"),
            "poliza": r.get("Número de Póliza"),
            "cliente": r.get("Nombre Cliente"),
            "correo_cliente": r.get("Correo Cliente"),
            "prima": r.get("Prima"),
            "estado": r.get("Estado"),
            "fecha_emision": (r.get("Fecha de Emisión") or {}).get("start") if isinstance(r.get("Fecha de Emisión"), dict) else None,
            "producto": r.get("Producto (nombre)"),
            "url": r.get("_url"),
        })
    return {"total_unico": len(union), "lista_completa": lista}


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


# ──────────── DBs Allianz adicionales (curadas) ────────────

def _query_simple(db_id: str, conditions: List[Dict[str, Any]], limit: int = 20,
                  sorts: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Helper genérico: arma filter AND con N condiciones y devuelve flattened."""
    if not db_id:
        return []
    kwargs: Dict[str, Any] = {"database_id": db_id, "page_size": min(limit, 100)}
    if conditions:
        kwargs["filter"] = conditions[0] if len(conditions) == 1 else {"and": conditions}
    if sorts:
        kwargs["sorts"] = sorts
    resp = _retry_429(_client().databases.query, **kwargs)
    return [_flatten_props(p) for p in resp.get("results", [])[:limit]]


def buscar_renovaciones(*, poliza: Optional[str] = None, email_asesor: Optional[str] = None,
                        estado: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """Renovaciones por póliza, asesor o estado.
    Si pasan email_asesor: resuelve el page_id del asesor y filtra la relation."""
    conds: List[Dict[str, Any]] = []
    if poliza:
        conds.append({"property": "Nombre", "title": {"contains": poliza}})
    if estado:
        conds.append({"property": "Estado de Renovación", "status": {"equals": estado}})
    if email_asesor:
        asesores = buscar_asesor_por_email(email_asesor)
        if asesores:
            conds.append({"property": "Asesores", "relation": {"contains": asesores[0]["_id"]}})
    return _query_simple(DB_RENOVACIONES, conds, limit)


def buscar_siniestros(*, poliza: Optional[str] = None, email_asesor: Optional[str] = None,
                      estado: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    conds: List[Dict[str, Any]] = []
    if poliza:
        conds.append({"property": "Siniestro", "title": {"contains": poliza}})
    if estado:
        conds.append({"property": "Estado", "status": {"equals": estado}})
    if email_asesor:
        asesores = buscar_asesor_por_email(email_asesor)
        if asesores:
            conds.append({"property": "Asesores ", "relation": {"contains": asesores[0]["_id"]}})
    return _query_simple(DB_SINIESTROS, conds, limit)


def buscar_comisiones(*, poliza: Optional[str] = None, tipo_pago: Optional[str] = None,
                      concepto: Optional[str] = None, desde: Optional[str] = None,
                      hasta: Optional[str] = None, limit: int = 30) -> List[Dict[str, Any]]:
    """Comisiones Agentes. tipo_pago ∈ {'Comisión Regular','ChargeBack','Bono','Mes 13 PLU3','Ajuste'}."""
    conds: List[Dict[str, Any]] = []
    if poliza:
        conds.append({"property": "Póliza", "rich_text": {"contains": poliza}})
    if tipo_pago:
        conds.append({"property": "Tipo de Pago", "select": {"equals": tipo_pago}})
    if concepto:
        conds.append({"property": "Concepto", "title": {"contains": concepto}})
    if desde:
        conds.append({"property": "Fecha de pago Allianz", "date": {"on_or_after": desde}})
    if hasta:
        conds.append({"property": "Fecha de pago Allianz", "date": {"on_or_before": hasta}})
    return _query_simple(DB_COMISIONES_AGENTES, conds, limit,
                         sorts=[{"property": "Fecha de pago Allianz", "direction": "descending"}])


def buscar_bonos_agentes(*, clave_agente: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """Bonos Allianz Agentes (title = Clave de Agente)."""
    conds: List[Dict[str, Any]] = []
    if clave_agente:
        conds.append({"property": "Clave de Agente", "title": {"contains": clave_agente}})
    return _query_simple(DB_BONOS_AGENTES, conds, limit)


def buscar_bonos_promotoria(*, nombre: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """Bonos Allianz Promotoría (title = Name)."""
    conds: List[Dict[str, Any]] = []
    if nombre:
        conds.append({"property": "Name", "title": {"contains": nombre}})
    return _query_simple(DB_BONOS_PROMOTORIA, conds, limit)


def buscar_mes_13_plu3(*, cliente: Optional[str] = None, limit: int = 30) -> List[Dict[str, Any]]:
    """Mes 13 PLU3 (title = Cliente)."""
    conds: List[Dict[str, Any]] = []
    if cliente:
        conds.append({"property": "Cliente", "title": {"contains": cliente}})
    return _query_simple(DB_MES_13_PLU3, conds, limit)


def buscar_puntos_convencion(*, clave_agente: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """Puntos Convención (title = Clave de Agente)."""
    conds: List[Dict[str, Any]] = []
    if clave_agente:
        conds.append({"property": "Clave de Agente", "title": {"contains": clave_agente}})
    return _query_simple(DB_PUNTOS_CONVENCION, conds, limit)


def buscar_productos(*, nombre: Optional[str] = None, tipo_producto: Optional[str] = None,
                     id_allianz: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """Catálogo de Productos.
    tipo_producto ∈ {'Producto de Ahorro','Producto de Inversión','Seguro de Auto',
                     'Seguro de Vida','Seguro de Gastos Médicos','Curso Digital',
                     'Seguro Residencial','Seguro de Alta Gama','Seguro'}."""
    conds: List[Dict[str, Any]] = []
    if nombre:
        conds.append({"property": "Nombre", "title": {"contains": nombre}})
    if tipo_producto:
        conds.append({"property": "Tipo de producto", "select": {"equals": tipo_producto}})
    if id_allianz:
        conds.append({"property": "ID Allianz", "rich_text": {"contains": id_allianz}})
    return _query_simple(DB_PRODUCTOS, conds, limit)


def buscar_clientes_ppr(*, email_cliente: Optional[str] = None, email_asesor: Optional[str] = None,
                        poliza: Optional[str] = None, estado: Optional[str] = None,
                        producto: Optional[str] = None, limit: int = 30) -> List[Dict[str, Any]]:
    """Clientes PPR Allianz. Filtros principales del flujo PLU3."""
    conds: List[Dict[str, Any]] = []
    if email_cliente:
        conds.append({"property": "Correo Electrónico", "rich_text": {"contains": email_cliente.lower()}})
    if email_asesor:
        conds.append({"property": "Correo Asesor", "rich_text": {"contains": email_asesor.lower()}})
    if poliza:
        conds.append({"property": "Póliza", "rich_text": {"contains": poliza}})
    if estado:
        conds.append({"property": "Estado ", "select": {"equals": estado}})
    if producto:
        conds.append({"property": "Producto", "select": {"equals": producto}})
    return _query_simple(DB_CLIENTES_PPR, conds, limit)


def buscar_migracion_cartera(*, emision: Optional[str] = None, migrado: Optional[bool] = None,
                             limit: int = 30) -> List[Dict[str, Any]]:
    conds: List[Dict[str, Any]] = []
    if emision:
        conds.append({"property": "Emisión", "title": {"contains": emision}})
    if migrado is not None:
        conds.append({"property": "Migrado", "checkbox": {"equals": bool(migrado)}})
    return _query_simple(DB_MIGRACION_CARTERA, conds, limit)

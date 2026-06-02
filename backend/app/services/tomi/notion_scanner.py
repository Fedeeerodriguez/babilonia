"""
Scanner de Notion para descubrir qué DBs y páginas tiene compartidas la
integración de Tomi, y exponerlas controladamente vía allowlist.

Flujo:
  1. discover_databases() → lista TODAS las DBs que la integración ve.
  2. Admin marca cuáles habilitar en `tomi_notion_allowlist`.
  3. Endpoints de query/lectura validan contra allowlist antes de ejecutar.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.tomi.notion_client import (
    _client,
    _retry_429,
    _flatten_props,
    _page_title,
)

log = logging.getLogger("tomi.notion_scanner")


# ───────────────────────── helpers ─────────────────────────

def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s_-]+", "_", s, flags=re.UNICODE)
    return s.strip("_") or "sin_titulo"


def _summarize_schema(db: Dict[str, Any]) -> List[Dict[str, str]]:
    """Devuelve [{name, type, options?}] de cada propiedad de la DB."""
    out = []
    for name, prop in (db.get("properties") or {}).items():
        t = prop.get("type")
        entry: Dict[str, Any] = {"name": name, "type": t}
        if t in ("select", "status"):
            opts = ((prop.get(t) or {}).get("options") or [])
            entry["options"] = [o.get("name") for o in opts][:30]
        elif t == "multi_select":
            opts = ((prop.get("multi_select") or {}).get("options") or [])
            entry["options"] = [o.get("name") for o in opts][:30]
        elif t == "relation":
            rel = prop.get("relation") or {}
            entry["related_db_id"] = rel.get("database_id")
        out.append(entry)
    return out


# ───────────────────────── discover ─────────────────────────

def discover_databases() -> List[Dict[str, Any]]:
    """Lista TODAS las databases que la integración de Notion tiene compartidas.

    Pagina automáticamente. Para cada DB también incluye su schema resumido.
    """
    client = _client()
    results: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        kwargs: Dict[str, Any] = {
            "filter": {"value": "database", "property": "object"},
            "page_size": 100,
        }
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = _retry_429(client.search, **kwargs)
        for db in resp.get("results", []):
            title_arr = db.get("title") or []
            title = "".join(t.get("plain_text", "") for t in title_arr) or "(sin título)"
            parent = db.get("parent") or {}
            results.append({
                "id": db.get("id"),
                "title": title,
                "slug": _slugify(title),
                "url": db.get("url"),
                "parent_type": parent.get("type"),
                "parent_id": parent.get(parent.get("type") or ""),
                "last_edited_time": db.get("last_edited_time"),
                "schema": _summarize_schema(db),
            })
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return results


def search_notion(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Búsqueda global tipo Cmd+K en Notion (páginas y databases)."""
    client = _client()
    resp = _retry_429(client.search, query=query, page_size=min(limit, 100))
    out = []
    for r in resp.get("results", [])[:limit]:
        obj = r.get("object")
        if obj == "database":
            title_arr = r.get("title") or []
            title = "".join(t.get("plain_text", "") for t in title_arr)
        else:
            title = _page_title(r) or "(sin título)"
        out.append({
            "id": r.get("id"),
            "object": obj,
            "title": title,
            "url": r.get("url"),
            "last_edited_time": r.get("last_edited_time"),
        })
    return out


# ───────────────────────── lectura de páginas ─────────────────────────

def _blocks_to_text(blocks: List[Dict[str, Any]], depth: int = 0) -> str:
    """Aplasta bloques de Notion a markdown simple."""
    out: List[str] = []
    prefix = "  " * depth
    for b in blocks:
        t = b.get("type")
        data = b.get(t) or {}
        rt = "".join(x.get("plain_text", "") for x in data.get("rich_text", []))
        if t == "heading_1":
            out.append(f"\n# {rt}")
        elif t == "heading_2":
            out.append(f"\n## {rt}")
        elif t == "heading_3":
            out.append(f"\n### {rt}")
        elif t == "bulleted_list_item":
            out.append(f"{prefix}- {rt}")
        elif t == "numbered_list_item":
            out.append(f"{prefix}1. {rt}")
        elif t == "to_do":
            chk = "x" if data.get("checked") else " "
            out.append(f"{prefix}- [{chk}] {rt}")
        elif t == "quote":
            out.append(f"> {rt}")
        elif t == "code":
            lang = data.get("language") or ""
            out.append(f"```{lang}\n{rt}\n```")
        elif t == "callout":
            out.append(f"💡 {rt}")
        elif t == "toggle":
            out.append(f"{prefix}▸ {rt}")
        elif t == "divider":
            out.append("---")
        elif t == "paragraph":
            if rt:
                out.append(f"{prefix}{rt}")
        else:
            if rt:
                out.append(f"{prefix}{rt}")
    return "\n".join(out)


def get_page_content(page_id: str, max_blocks: int = 200) -> Dict[str, Any]:
    """Devuelve metadata + contenido en markdown de una página de Notion."""
    client = _client()
    page = _retry_429(client.pages.retrieve, page_id=page_id)

    blocks: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while len(blocks) < max_blocks:
        kwargs: Dict[str, Any] = {"block_id": page_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = _retry_429(client.blocks.children.list, **kwargs)
        blocks.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")

    return {
        "id": page.get("id"),
        "url": page.get("url"),
        "title": _page_title(page),
        "properties": _flatten_props(page),
        "last_edited_time": page.get("last_edited_time"),
        "content_markdown": _blocks_to_text(blocks[:max_blocks]),
        "blocks_count": len(blocks),
    }


# ───────────────────────── allowlist ─────────────────────────

def _ensure_allowlist_table(db: Session) -> bool:
    try:
        db.execute(text("SELECT 1 FROM tomi_notion_allowlist LIMIT 1"))
        return True
    except Exception:
        db.rollback()
        return False


def listar_allowlist(db: Session) -> List[Dict[str, Any]]:
    if not _ensure_allowlist_table(db):
        return []
    rows = db.execute(text("""
        SELECT db_id, slug, title, enabled, descripcion, schema, updated_at
        FROM tomi_notion_allowlist ORDER BY enabled DESC, title
    """)).mappings().all()
    return [dict(r) for r in rows]


def upsert_allowlist(
    db: Session,
    db_id: str,
    slug: str,
    title: str,
    enabled: bool,
    descripcion: Optional[str] = None,
    schema: Optional[List[Dict[str, Any]]] = None,
) -> None:
    if not _ensure_allowlist_table(db):
        raise RuntimeError("tomi_notion_allowlist no existe — correr el SQL de setup")
    db.execute(text("""
        INSERT INTO tomi_notion_allowlist (db_id, slug, title, enabled, descripcion, schema, updated_at)
        VALUES (:db_id, :slug, :title, :enabled, :desc, CAST(:schema AS jsonb), now())
        ON CONFLICT (db_id) DO UPDATE SET
          slug = EXCLUDED.slug,
          title = EXCLUDED.title,
          enabled = EXCLUDED.enabled,
          descripcion = COALESCE(EXCLUDED.descripcion, tomi_notion_allowlist.descripcion),
          schema = EXCLUDED.schema,
          updated_at = now()
    """), {
        "db_id": db_id,
        "slug": slug,
        "title": title,
        "enabled": enabled,
        "desc": descripcion,
        "schema": json.dumps(schema or [], ensure_ascii=False),
    })
    db.commit()


def is_db_allowed(db: Session, db_id: str) -> bool:
    if not _ensure_allowlist_table(db):
        return False
    row = db.execute(text("""
        SELECT enabled FROM tomi_notion_allowlist WHERE db_id = :id
    """), {"id": db_id}).first()
    return bool(row and row[0])


def get_allowed_db(db: Session, slug_or_id: str) -> Optional[Dict[str, Any]]:
    if not _ensure_allowlist_table(db):
        return None
    row = db.execute(text("""
        SELECT db_id, slug, title, enabled, descripcion, schema
        FROM tomi_notion_allowlist
        WHERE (db_id = :k OR slug = :k) AND enabled = true
    """), {"k": slug_or_id}).mappings().first()
    return dict(row) if row else None


# ───────────────────────── query allowlist-gated ─────────────────────────

def mapear_relaciones_conocidas() -> Dict[str, Any]:
    """Recorre las DBs ya mapeadas en NOTION_DB_* y extrae todas las DBs
    referenciadas vía columnas de tipo `relation`.

    Devuelve:
      {
        "conocidas": { slug: {id, title} },
        "tablas": [
          { slug, id, title, relaciones: [
              { columna, target_id, target_title, conocida: bool, conocida_como }
          ]}
        ],
        "descubiertas": [ { id, title, llegada_desde: [(slug, columna)] } ]
      }
    """
    from app.services.tomi import notion_client as nc

    # Mapa de DBs ya conocidas: id -> slug
    conocidas_map: Dict[str, str] = {}
    conocidas_meta: Dict[str, Dict[str, str]] = {}

    candidatos = {
        "asesores": nc.DB_ASESORES,
        "estudiantes": nc.DB_ESTUDIANTES,
        "clientes_general": nc.DB_CLIENTES,
        "emisiones": nc.DB_EMISIONES,
        "cobranzas": nc.DB_COBRANZAS,
        "tickets_allianz": nc.DB_TICKETS_ALLIANZ,
        "tickets_babilonia": nc.DB_TICKETS_BABILONIA,
        "eventos_calendly": nc.DB_EVENTOS_CALENDLY,
        "portafolios": nc.DB_PORTAFOLIOS,
        **nc.SUB_DBS_CLIENTES,
    }
    candidatos = {k: v for k, v in candidatos.items() if v}

    client = _client()

    # Pre-cargar todos los retrieves para tener título y schema
    db_cache: Dict[str, Dict[str, Any]] = {}
    for slug, db_id in candidatos.items():
        try:
            meta = _retry_429(client.databases.retrieve, database_id=db_id)
            db_cache[db_id] = meta
            title_arr = meta.get("title") or []
            title = "".join(t.get("plain_text", "") for t in title_arr) or slug
            conocidas_map[db_id.replace("-", "")] = slug
            conocidas_map[db_id] = slug
            conocidas_meta[slug] = {"id": db_id, "title": title}
        except Exception as e:
            log.warning("retrieve %s (%s) falló: %s", slug, db_id, e)

    def _norm(s: str) -> str:
        return (s or "").replace("-", "")

    tablas: List[Dict[str, Any]] = []
    descubiertas: Dict[str, Dict[str, Any]] = {}

    for slug, db_id in candidatos.items():
        meta = db_cache.get(db_id)
        if not meta:
            continue
        rels = []
        for prop_name, prop in (meta.get("properties") or {}).items():
            if prop.get("type") != "relation":
                continue
            target_id = (prop.get("relation") or {}).get("database_id") or ""
            if not target_id:
                continue
            # Resolver título del target
            target_title = None
            try:
                tmeta = db_cache.get(target_id) or _retry_429(client.databases.retrieve, database_id=target_id)
                db_cache[target_id] = tmeta
                title_arr = tmeta.get("title") or []
                target_title = "".join(t.get("plain_text", "") for t in title_arr) or "(sin título)"
            except Exception as e:
                target_title = f"(error: {e})"

            es_conocida = _norm(target_id) in conocidas_map
            conocida_como = conocidas_map.get(_norm(target_id))

            rels.append({
                "columna": prop_name,
                "target_id": target_id,
                "target_title": target_title,
                "conocida": es_conocida,
                "conocida_como": conocida_como,
            })

            if not es_conocida:
                d = descubiertas.setdefault(target_id, {
                    "id": target_id,
                    "title": target_title,
                    "llegada_desde": [],
                    "schema": _summarize_schema(db_cache.get(target_id, {})),
                })
                d["llegada_desde"].append({"desde": slug, "columna": prop_name})

        tablas.append({
            "slug": slug,
            "id": db_id,
            "title": conocidas_meta.get(slug, {}).get("title"),
            "relaciones": rels,
        })

    return {
        "conocidas": conocidas_meta,
        "tablas": tablas,
        "descubiertas": list(descubiertas.values()),
    }


def query_db_filtered(
    db: Session,
    slug_or_id: str,
    filtros: Optional[Dict[str, Any]] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """Query a una DB previamente habilitada en la allowlist.

    `filtros` es opcional: { "Correo": "ana@x.com", "Estado": "Activa" }
    Detecta automáticamente el tipo de columna desde el schema cacheado.
    """
    entry = get_allowed_db(db, slug_or_id)
    if not entry:
        raise PermissionError(f"DB '{slug_or_id}' no está en la allowlist")

    schema = entry.get("schema") or []
    schema_by_name = {p["name"]: p for p in schema} if isinstance(schema, list) else {}

    conditions = []
    if filtros:
        for prop_name, value in filtros.items():
            prop = schema_by_name.get(prop_name)
            if not prop:
                continue
            t = prop.get("type")
            if t in ("rich_text", "title", "email", "phone_number", "url"):
                conditions.append({"property": prop_name, t: {"contains": str(value)}})
            elif t in ("select", "status"):
                conditions.append({"property": prop_name, t: {"equals": str(value)}})
            elif t == "multi_select":
                conditions.append({"property": prop_name, "multi_select": {"contains": str(value)}})
            elif t == "checkbox":
                conditions.append({"property": prop_name, "checkbox": {"equals": bool(value)}})
            elif t == "number":
                try:
                    conditions.append({"property": prop_name, "number": {"equals": float(value)}})
                except Exception:
                    pass

    client = _client()
    kwargs: Dict[str, Any] = {"database_id": entry["db_id"], "page_size": min(limit, 100)}
    if conditions:
        kwargs["filter"] = conditions[0] if len(conditions) == 1 else {"and": conditions}

    resp = _retry_429(client.databases.query, **kwargs)
    pages = [_flatten_props(p) for p in resp.get("results", [])[:limit]]
    return {
        "db": {"id": entry["db_id"], "slug": entry["slug"], "title": entry["title"]},
        "total": len(pages),
        "results": pages,
    }

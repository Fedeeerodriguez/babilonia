"""Búsqueda en el vector store Supabase (`documents` pgvector) — reemplazo determinista
del sub-agente memorias_supabase de n8n.

Usa OpenAI embeddings + similitud coseno (operador `<=>`) sobre la columna `embedding`.
Filtros opcionales por metadata (categoría, wa_id, source).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger("tomi.memorias")

EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")


def _client() -> OpenAI:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY no configurada")
    return OpenAI(api_key=key)


def _embed(q: str) -> List[float]:
    resp = _client().embeddings.create(model=EMBED_MODEL, input=q)
    return resp.data[0].embedding


def buscar_memorias(
    db: Session,
    query: str,
    categoria: Optional[str] = None,
    wa_id: Optional[str] = None,
    source: Optional[str] = None,
    k: int = 4,
) -> List[Dict[str, Any]]:
    """Top-k chunks por similitud coseno con filtros opcionales por metadata."""
    if not query or not query.strip():
        return []

    emb = _embed(query)
    where_clauses: List[str] = []
    params: Dict[str, Any] = {"emb": str(emb), "k": k}

    if categoria:
        where_clauses.append("metadata->>'categoria' = :categoria")
        params["categoria"] = categoria
    if wa_id:
        where_clauses.append("metadata->>'wa_id' = :wa_id")
        params["wa_id"] = wa_id
    if source:
        where_clauses.append("metadata->>'source' = :source")
        params["source"] = source

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    sql = f"""
        SELECT
            id,
            content,
            metadata,
            1 - (embedding <=> CAST(:emb AS vector)) AS similarity
        FROM documents
        {where_sql}
        ORDER BY embedding <=> CAST(:emb AS vector) ASC
        LIMIT :k
    """
    try:
        rows = db.execute(text(sql), params).mappings().all()
    except Exception as e:
        log.error("buscar_memorias falló: %s", e)
        return []

    out: List[Dict[str, Any]] = []
    for r in rows:
        meta = r["metadata"]
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        out.append({
            "id": str(r["id"]),
            "content": r["content"],
            "metadata": meta or {},
            "similarity": float(r["similarity"]) if r["similarity"] is not None else None,
        })
    return out

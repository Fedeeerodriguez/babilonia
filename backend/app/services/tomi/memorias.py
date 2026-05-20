"""Búsqueda determinística en el vector store Supabase (tabla `documents`).

Reemplaza el sub-agente `memorias_supabase` de n8n.

Esquema de Notion → Supabase:
    documents (id, content, metadata jsonb, embedding vector)

Las memorias están cargadas desde el endpoint /api/documents/upload con
`source` ∈ {plu3, patrimonial, proteccion, auto, educacion}.

Sin LLM intermedio. La clasificación de categoría se hace por keywords (determinístico).
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.tomi.cache import notion_cache, hash_key

log = logging.getLogger("tomi.memorias")

EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

# Tabla pgvector donde n8n almacena los chunks. Puede ser "documents",
# "sandbox.documents", "public.documents", etc.
DOCUMENTS_TABLE = os.getenv("DOCUMENTS_TABLE", "documents")

CATEGORIAS_VALIDAS = ("plu3", "patrimonial", "proteccion", "auto", "educacion")

# Keywords para clasificación determinística (sin LLM).
# Cada categoría tiene un set; el matcheo es case-insensitive y unicode-folded.
KEYWORDS: Dict[str, List[str]] = {
    "plu3": [
        "ppr", "plu3", "retiro", "jubilación", "jubilacion", "pensión", "pension",
        "plan privado de retiro", "ahorro para retiro", "optimaxx", "ahorro retiro",
        "fondo de retiro", "plan de retiro",
    ],
    "patrimonial": [
        "patrimonial", "inversión patrimonial", "inversion patrimonial",
        "programa patrimonial", "fondo patrimonial", "patrimonio",
    ],
    "proteccion": [
        "protección", "proteccion", "vida", "muerte", "invalidez", "fallecimiento",
        "beneficiario", "seguro de vida", "cobertura de vida", "indemnización",
        "indemnizacion", "deceso",
    ],
    "auto": [
        "auto", "automóvil", "automovil", "vehículo", "vehiculo", "coche", "carro",
        "moto", "motocicleta", "siniestro auto", "póliza auto", "poliza auto",
        "seguro auto", "seguro de auto", "seguro vehicular",
    ],
    "educacion": [
        "curso", "módulo", "modulo", "academia", "estudiante", "alumno", "alumna",
        "babilonia academia", "clase", "lección", "leccion", "tutoría", "tutoria",
        "membresía", "membresia", "discord", "xp", "rockstar",
    ],
}


def _normalizar(s: str) -> str:
    """Lowercase + sacar acentos para keyword matching robusto."""
    if not s:
        return ""
    s = s.lower()
    # mapping simple de acentos
    repl = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n"}
    for k, v in repl.items():
        s = s.replace(k, v)
    return s


def clasificar_por_keywords(query: str) -> List[str]:
    """Devuelve lista de categorías que matchean keywords en la query.
    Vacía si no matchea ninguna. Múltiples si la query toca varias."""
    if not query:
        return []
    q = _normalizar(query)
    matched: List[Tuple[str, int]] = []
    for cat, kws in KEYWORDS.items():
        count = 0
        for kw in kws:
            kw_norm = _normalizar(kw)
            # Match palabra completa cuando es 1 token; substring cuando es frase.
            if " " in kw_norm:
                if kw_norm in q:
                    count += 1
            else:
                # word boundary regex
                if re.search(rf"\b{re.escape(kw_norm)}\b", q):
                    count += 1
        if count > 0:
            matched.append((cat, count))
    # Ordenar por cantidad de matches DESC
    matched.sort(key=lambda x: -x[1])
    return [c for c, _ in matched]


def _openai_client() -> OpenAI:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY no configurada")
    return OpenAI(api_key=key)


def _embed(query: str) -> List[float]:
    cache_key = f"emb:{hash_key(EMBED_MODEL, query)}"
    cached_emb = notion_cache.get(cache_key)
    if cached_emb is not None:
        return cached_emb
    resp = _openai_client().embeddings.create(model=EMBED_MODEL, input=query)
    emb = resp.data[0].embedding
    notion_cache.set(cache_key, emb)
    return emb


def buscar_chunks(
    db: Session,
    query: str,
    categoria: Optional[str] = None,
    k: int = 5,
    min_similarity: float = 0.0,
) -> List[Dict[str, Any]]:
    """Top-k chunks por cosine similarity sobre `documents` con filtro opcional
    por metadata.source. Devuelve lista con id, content, metadata, similarity.
    """
    if not query or not query.strip():
        return []
    if categoria and categoria not in CATEGORIAS_VALIDAS:
        log.warning("categoria inválida: %s", categoria)
        return []

    cache_key = f"chunks:{hash_key(query, categoria, k)}"
    cached_val = notion_cache.get(cache_key)
    if cached_val is not None:
        return cached_val

    try:
        emb = _embed(query)
    except Exception as e:
        log.error("embed falló: %s", e)
        return []

    params: Dict[str, Any] = {"emb": str(emb), "k": k}
    where = ""
    if categoria:
        where = "WHERE metadata->>'source' = :categoria"
        params["categoria"] = categoria

    sql = f"""
        SELECT
            id,
            content,
            metadata,
            1 - (embedding <=> CAST(:emb AS vector)) AS similarity
        FROM {DOCUMENTS_TABLE}
        {where}
        ORDER BY embedding <=> CAST(:emb AS vector) ASC
        LIMIT :k
    """
    try:
        rows = db.execute(text(sql), params).mappings().all()
    except Exception as e:
        log.error("buscar_chunks SQL falló: %s", e)
        return []

    out: List[Dict[str, Any]] = []
    for r in rows:
        sim = float(r["similarity"]) if r["similarity"] is not None else 0.0
        if sim < min_similarity:
            continue
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
            "categoria": (meta or {}).get("source"),
            "chunk_index": (meta or {}).get("chunk_index"),
            "similarity": round(sim, 4),
        })
    notion_cache.set(cache_key, out)
    return out


def buscar_multi_categoria(
    db: Session,
    query: str,
    categorias: List[str],
    k_por_categoria: int = 3,
    min_similarity: float = 0.0,
) -> Dict[str, List[Dict[str, Any]]]:
    """Busca en múltiples categorías en serie (la BD del pool admite muchas
    queries SQL livianas; los embeddings ya están en caché si la query es la misma).
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    for cat in categorias:
        out[cat] = buscar_chunks(db, query, categoria=cat, k=k_por_categoria, min_similarity=min_similarity)
    return out


def listar_categorias_con_datos(db: Session) -> Dict[str, int]:
    """Útil para debug: cuántos chunks hay por categoría en Supabase."""
    sql = f"""
        SELECT metadata->>'source' AS categoria, COUNT(*) AS n
        FROM {DOCUMENTS_TABLE}
        GROUP BY metadata->>'source'
        ORDER BY n DESC
    """
    try:
        rows = db.execute(text(sql)).mappings().all()
        return {r["categoria"] or "(sin source)": int(r["n"]) for r in rows}
    except Exception as e:
        log.error("listar_categorias falló: %s", e)
        return {}

"""Orquestador determinístico del sub-agente memorias_supabase.

Pasos:
1. Clasifica la query por keywords (sin LLM).
2. Si hay 1 categoría clara → busca en esa.
3. Si hay 2-3 categorías → busca en cada una (paralelo en lo posible).
4. Si no hay match → busca SIN filtro (broad search across all sources).
5. Devuelve JSON estructurado con chunks + metadata + stats.

El LLM (en agente_memorias.py) puede pasar `categoria` explícita para skip la clasificación.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.services.tomi import memorias as mem

log = logging.getLogger("tomi.memorias_bd")

# Threshold de similarity por debajo del cual descartamos chunks irrelevantes
MIN_SIMILARITY_DEFAULT = 0.30


def consultar(
    db: Session,
    query: str,
    categoria: Optional[str] = None,
    k: int = 5,
    min_similarity: float = MIN_SIMILARITY_DEFAULT,
) -> Dict[str, Any]:
    """Orquesta búsqueda en pgvector. Devuelve JSON estructurado.

    Si `categoria` viene seteada, busca solo ahí. Si no, clasifica por keywords.
    """
    t0 = time.time()
    if not query or not query.strip():
        return {
            "query": query,
            "categoria_inferida": None,
            "categorias_consultadas": [],
            "chunks": [],
            "chunks_por_categoria": {},
            "advertencias": [{
                "severidad": "warning",
                "tipo": "query_vacia",
                "mensaje": "La query está vacía. No se ejecutó ninguna búsqueda.",
            }],
            "stats": {"tiempo_ms": 0, "queries_pgvector": 0, "embeddings": 0},
        }

    advertencias: List[Dict[str, Any]] = []

    # 1. Determinar qué categorías consultar
    if categoria:
        if categoria not in mem.CATEGORIAS_VALIDAS:
            advertencias.append({
                "severidad": "error",
                "tipo": "categoria_invalida",
                "mensaje": f"Categoría '{categoria}' no es válida. Válidas: {', '.join(mem.CATEGORIAS_VALIDAS)}.",
            })
            return {
                "query": query,
                "categoria_inferida": None,
                "categorias_consultadas": [],
                "chunks": [],
                "chunks_por_categoria": {},
                "advertencias": advertencias,
                "stats": {"tiempo_ms": 0, "queries_pgvector": 0, "embeddings": 0},
            }
        cats_a_consultar = [categoria]
        cat_inferida = categoria
    else:
        cats_detectadas = mem.clasificar_por_keywords(query)
        if cats_detectadas:
            # Si hay más de 1 con misma cantidad de matches, dejamos las top 2 para cubrir
            cats_a_consultar = cats_detectadas[:2]
            cat_inferida = cats_detectadas[0]
        else:
            # Sin clasificación clara: broad search (sin filtro)
            cats_a_consultar = [None]
            cat_inferida = None
            advertencias.append({
                "severidad": "info",
                "tipo": "sin_categoria_clara",
                "mensaje": "La query no matchea keywords de ninguna categoría — buscando en TODAS las memorias sin filtro.",
                "sugerencia": "Si conocés la categoría, pasala explícitamente para mejor recall.",
            })

    # 2. Ejecutar búsquedas (paralelo si son varias)
    chunks_por_cat: Dict[str, List[Dict[str, Any]]] = {}
    queries_count = 0
    embeddings_count = 0

    def _buscar(cat: Optional[str]) -> List[Dict[str, Any]]:
        return mem.buscar_chunks(db, query, categoria=cat, k=k, min_similarity=min_similarity)

    # Búsqueda secuencial. Son como mucho 2 categorías (rápido) y NO se puede
    # paralelizar compartiendo la misma Session de SQLAlchemy entre hilos:
    # tira "concurrent operations are not permitted" y se pierde una categoría.
    # El embedding queda cacheado entre llamadas, así que el costo extra es mínimo.
    for cat in cats_a_consultar:
        try:
            chunks_por_cat[cat or "todas"] = _buscar(cat)
            queries_count += 1
        except Exception as e:
            log.error("búsqueda %s falló: %s", cat, e)
            chunks_por_cat[cat or "todas"] = []

    embeddings_count = 1  # un solo embedding por query (cacheado entre categorías)

    # 2b. Fallback: si filtramos por categoría y NO trajo nada, reintentar broad (sin filtro).
    #     Evita responder "sin datos" cuando la info existe pero en otra categoría.
    total_encontrados = sum(len(v) for v in chunks_por_cat.values())
    if total_encontrados == 0 and cats_a_consultar != [None]:
        log.info("sin resultados en %s — fallback a búsqueda broad sin filtro", cats_a_consultar)
        try:
            chunks_por_cat["todas"] = _buscar(None)
            queries_count += 1
            advertencias.append({
                "severidad": "info",
                "tipo": "fallback_broad",
                "mensaje": (
                    f"No se encontró nada en {[c for c in cats_a_consultar if c]}; "
                    "se amplió la búsqueda a todas las memorias."
                ),
            })
        except Exception as e:
            log.error("fallback broad falló: %s", e)

    # 3. Unir todos los chunks ordenados por similarity DESC
    all_chunks: List[Dict[str, Any]] = []
    for cat, chunks in chunks_por_cat.items():
        for c in chunks:
            # marcar la categoría origen
            c2 = {**c, "_categoria_consultada": cat}
            all_chunks.append(c2)
    all_chunks.sort(key=lambda c: -c.get("similarity", 0))
    # Dedupe doble: por id y por content_hash (la DB tiene duplicados del mismo texto)
    import hashlib
    seen_ids: set = set()
    seen_content: set = set()
    chunks_unicos: List[Dict[str, Any]] = []
    duplicados_por_contenido = 0
    for c in all_chunks:
        if c["id"] in seen_ids:
            continue
        ch = hashlib.sha1((c.get("content") or "").strip().encode("utf-8")).hexdigest()
        if ch in seen_content:
            duplicados_por_contenido += 1
            continue
        seen_ids.add(c["id"])
        seen_content.add(ch)
        chunks_unicos.append(c)
    if duplicados_por_contenido > 0:
        advertencias.append({
            "severidad": "info",
            "tipo": "chunks_duplicados",
            "mensaje": f"Se filtraron {duplicados_por_contenido} chunk(s) con contenido idéntico (data sucia en Notion).",
            "sugerencia": "Considerar recargar las memorias con dedupe en el ingest para no tener repetidos.",
        })

    # 4. Advertencias si no hubo resultados → escalar a humano
    escalar_a_humano = not chunks_unicos
    if not chunks_unicos:
        advertencias.append({
            "severidad": "warning",
            "tipo": "sin_resultados",
            "mensaje": f"No se encontraron chunks relevantes (min_similarity={min_similarity}) ni siquiera ampliando la búsqueda a todas las memorias.",
            "sugerencia": "Escalar la consulta a un humano: la información no está cargada en las memorias.",
        })
    else:
        # Advertencia si similarity bajo
        max_sim = max(c.get("similarity", 0) for c in chunks_unicos)
        if max_sim < 0.55:
            advertencias.append({
                "severidad": "info",
                "tipo": "baja_similarity",
                "mensaje": f"Los chunks encontrados tienen similarity baja (max: {max_sim:.2f}). La información puede no ser muy relevante.",
            })

    elapsed = int((time.time() - t0) * 1000)
    return {
        "query": query,
        "categoria_inferida": cat_inferida,
        "categorias_consultadas": [c for c in cats_a_consultar if c],
        "chunks": chunks_unicos,
        "chunks_por_categoria": chunks_por_cat,
        "escalar_a_humano": escalar_a_humano,
        "advertencias": advertencias,
        "stats": {
            "tiempo_ms": elapsed,
            "queries_pgvector": queries_count,
            "embeddings": embeddings_count,
            "chunks_totales": len(chunks_unicos),
            "min_similarity_threshold": min_similarity,
        },
    }

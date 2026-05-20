"""Renderizador determinístico de informes de memorias.

Toma el resultado crudo de memorias_bd.consultar() y genera markdown verbatim.
Sin LLM. Cada chunk se muestra con su contenido completo, similarity y categoría.
"""
from __future__ import annotations

from typing import Any, Dict, List


def _safe(val, default="—"):
    if val is None or val == "":
        return default
    return str(val)


def renderizar(resultado: Dict[str, Any]) -> str:
    """Genera markdown determinístico desde el resultado de memorias_bd.consultar()."""
    lines: List[str] = ["# Informe de memorias técnicas — Tomi · Babilonia", ""]

    stats = resultado.get("stats") or {}
    lines.append("## Consulta procesada")
    lines.append(f"- Query: `{_safe(resultado.get('query'))}`")
    lines.append(f"- Categoría inferida: `{_safe(resultado.get('categoria_inferida'))}`")
    cats_consultadas = resultado.get("categorias_consultadas") or []
    lines.append(f"- Categorías consultadas: `{', '.join(cats_consultadas) if cats_consultadas else '(broad search sin filtro)'}`")
    lines.append(f"- Tiempo total: `{stats.get('tiempo_ms', 0)} ms` | Queries pgvector: `{stats.get('queries_pgvector', 0)}` | Embeddings: `{stats.get('embeddings', 0)}`")
    lines.append(f"- Chunks únicos encontrados: `{stats.get('chunks_totales', 0)}` (threshold similarity ≥ `{stats.get('min_similarity_threshold')}`)")
    lines.append("")

    chunks = resultado.get("chunks") or []
    if chunks:
        lines.append(f"## Chunks recuperados ({len(chunks)})")
        lines.append("")
        for i, c in enumerate(chunks, 1):
            sim = c.get("similarity", 0)
            cat = c.get("categoria") or c.get("_categoria_consultada") or "?"
            cidx = c.get("chunk_index")
            cidx_str = f" · chunk #{cidx}" if cidx is not None else ""
            lines.append(f"### {i}. Categoría: **{cat}** · Similarity: **{sim:.3f}**{cidx_str}")
            lines.append("")
            # Contenido VERBATIM (sin reformular). Lo encerramos en blockquote.
            content = (c.get("content") or "").strip()
            for ln in content.split("\n"):
                lines.append(f"> {ln}" if ln else ">")
            lines.append("")
            # Metadata cruda relevante (excluyendo source/chunk_index ya mostrados)
            meta = c.get("metadata") or {}
            meta_extra = {k: v for k, v in meta.items() if k not in ("source", "chunk_index")}
            if meta_extra:
                lines.append("**Metadata adicional:** " + ", ".join(f"`{k}={v}`" for k, v in meta_extra.items()))
                lines.append("")
            lines.append(f"_ID chunk: `{c.get('id')}`_")
            lines.append("")
            lines.append("---")
            lines.append("")
    else:
        lines.append("## ❌ Sin resultados")
        lines.append("")
        lines.append("No se encontraron chunks relevantes para esta consulta. Revisar:")
        lines.append("- Si la información existe en las memorias actuales (puede no estar cargada).")
        lines.append("- Si la categoría es la correcta.")
        lines.append("- Si el threshold de similarity está demasiado alto.")
        lines.append("")

    # Distribución por categoría
    chunks_por_cat = resultado.get("chunks_por_categoria") or {}
    if chunks_por_cat:
        lines.append("## Distribución por categoría consultada")
        for cat, cs in chunks_por_cat.items():
            lines.append(f"- `{cat}`: {len(cs)} chunk(s)")
        lines.append("")

    # Advertencias
    advs = resultado.get("advertencias") or []
    if advs:
        sev_order = {"error": 0, "warning": 1, "info": 2}
        advs_sorted = sorted(advs, key=lambda a: sev_order.get(a.get("severidad"), 9))
        lines.append(f"## ⚠️ Notas ({len(advs)})")
        for a in advs_sorted:
            sev = a.get("severidad", "info").upper()
            ico = {"ERROR": "🔴", "WARNING": "🟡", "INFO": "🔵"}.get(sev, "•")
            lines.append(f"- {ico} **{sev}** `{a.get('tipo')}`: {a.get('mensaje')}")
            if a.get("sugerencia"):
                lines.append(f"  - Sugerencia: {a['sugerencia']}")
        lines.append("")

    return "\n".join(lines)

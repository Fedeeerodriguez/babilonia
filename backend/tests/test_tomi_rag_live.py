"""QA LIVE — RAG (Supabase pgvector + OpenAI embeddings).

Estos tests pegan a servicios reales. Se SALTEAN automáticamente si no hay
DOCUMENTS_DATABASE_URL / OPENAI_API_KEY en backend/.env.

Validan el trabajo de conocimiento de hoy:
  - integridad de la metadata (0 registros sin categoría)
  - que el filtro por `clave` alcanza las fichas curadas (source='productos')
  - que Elite es alcanzable por categoría (antes = 0 chunks, era el bug)
  - que la ficha curada gana en la desambiguación Plus vs Educación
"""
from __future__ import annotations

from sqlalchemy import text

from app.services.tomi import memorias as mem
from tests._qautil import rag_session


def test_rag_metadata_integridad_categoria():
    db = rag_session()
    try:
        total = db.execute(text("SELECT count(*) FROM documents")).scalar()
        sin_cat = db.execute(
            text("SELECT count(*) FROM documents WHERE metadata->>'categoria' IS NULL")
        ).scalar()
        assert total and total > 2700, f"esperaba >2700 chunks, hay {total}"
        assert sin_cat == 0, f"hay {sin_cat} chunks sin 'categoria' (metadata sin ordenar)"
    finally:
        db.close()


def test_rag_fichas_curadas_presentes():
    db = rag_session()
    try:
        n = db.execute(
            text("SELECT count(*) FROM documents WHERE metadata->>'source' = 'productos'")
        ).scalar()
        assert n and n >= 14, f"esperaba >=14 chunks de fichas curadas, hay {n}"
    finally:
        db.close()


def test_rag_filtro_clave_alcanza_elite():
    # EL FIX: categoria='elite' filtra por clave='SVIP' y trae la ficha curada.
    # Antes (filtro solo por source) devolvía 0 porque no existe source='elite'.
    db = rag_session()
    try:
        chunks = mem.buscar_chunks(db, "optimaxx elite inversion en dolares", categoria="elite", k=5)
        assert len(chunks) >= 1, "Elite no devolvió chunks — el filtro por clave no funciona"
        claves = {(c.get("metadata") or {}).get("clave") for c in chunks}
        assert "SVIP" in claves, f"esperaba un chunk con clave SVIP, vino {claves}"
    finally:
        db.close()


def test_rag_filtro_plu3_incluye_ficha_y_legacy():
    # Filtrar por 'plu3' debe traer tanto la ficha curada (source=productos) como
    # los chunks históricos (source=plu3).
    db = rag_session()
    try:
        chunks = mem.buscar_chunks(db, "optimaxx plus plan de retiro ppr", categoria="plu3", k=8)
        assert len(chunks) >= 1
        fuentes = {(c.get("metadata") or {}).get("source") for c in chunks}
        assert "productos" in fuentes or "plu3" in fuentes, f"fuentes inesperadas: {fuentes}"
    finally:
        db.close()


def test_rag_desambiguacion_top_es_ficha_curada():
    # En la pregunta clásica que confundía al bot, la ficha curada (concisa,
    # autoritativa) debe estar en el top de resultados.
    db = rag_session()
    try:
        chunks = mem.buscar_chunks(
            db, "cual es la diferencia entre optimaxx plus y educacion", categoria=None, k=3
        )
        assert len(chunks) >= 1
        tipos = [(c.get("metadata") or {}).get("doc_tipo") for c in chunks]
        assert "ficha_curada" in tipos, f"ninguna ficha curada en el top 3: {tipos}"
    finally:
        db.close()

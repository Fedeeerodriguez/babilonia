"""Carga de documentos al vector store `documents` de Supabase.

Flujo: PDF/texto -> chunks -> embeddings OpenAI -> INSERT INTO documents (content, metadata, embedding).
La tabla `documents` ya existe (creada por LangChain/n8n) con columnas (id, content, metadata jsonb, embedding vector).
"""
import io
import os
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from openai import OpenAI
from pypdf import PdfReader
from app import models, schemas
from app.database import get_db, get_docs_db
from app.security import get_current_user

router = APIRouter(prefix="/api/documents", tags=["documents"])

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
# La tabla del vector store vive en DOCUMENTS_DATABASE_URL (la que consulta el bot),
# que puede ser un Postgres distinto al principal.
DOCS_TABLE = os.getenv("DOCUMENTS_TABLE", "documents")


def _client() -> OpenAI:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise HTTPException(500, "OPENAI_API_KEY no configurada")
    return OpenAI(
        api_key=key,
        timeout=float(os.getenv("OPENAI_TIMEOUT", "30")),
        max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "2")),
    )


def _chunk(text_in: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    text_in = text_in.strip()
    if not text_in:
        return []
    chunks, i = [], 0
    while i < len(text_in):
        chunks.append(text_in[i:i + size])
        i += size - overlap
    return chunks


def _embed_and_store(docs_db: Session, chunks: List[str], metadata_base: dict) -> int:
    """Embebe y persiste los chunks en el vector store (DB de `documents`).

    `docs_db` debe ser una sesión hacia DOCUMENTS_DATABASE_URL (get_docs_db),
    que es donde el bot de WATI consulta el conocimiento.
    """
    client = _client()
    resp = client.embeddings.create(model=EMBED_MODEL, input=chunks)
    inserted = 0
    for idx, (chunk, e) in enumerate(zip(chunks, resp.data)):
        meta = {**metadata_base, "chunk_index": idx}
        docs_db.execute(text(f"""
            INSERT INTO {DOCS_TABLE} (content, metadata, embedding)
            VALUES (:content, CAST(:meta AS jsonb), CAST(:emb AS vector))
        """), {
            "content": chunk,
            "meta": __import__("json").dumps(meta),
            "emb": str(e.embedding),
        })
        inserted += 1
    docs_db.commit()
    return inserted


@router.get("", response_model=List[schemas.DocumentOut])
def list_documents(
    source: Optional[str] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.DocumentMeta)
    if source:
        q = q.filter(models.DocumentMeta.source == source)
    return q.order_by(models.DocumentMeta.uploaded_at.desc()).all()


@router.post("/upload", response_model=schemas.DocumentOut)
async def upload_document(
    source: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    docs_db: Session = Depends(get_docs_db),
    user: models.User = Depends(get_current_user),
):
    raw = await file.read()
    if file.filename.lower().endswith(".pdf"):
        reader = PdfReader(io.BytesIO(raw))
        content = "\n\n".join((p.extract_text() or "") for p in reader.pages)
    else:
        content = raw.decode("utf-8", errors="ignore")

    chunks = _chunk(content)
    if not chunks:
        raise HTTPException(400, "No se pudo extraer texto")

    meta = models.DocumentMeta(
        file_name=file.filename, source=source, uploaded_by=user.email,
        size_bytes=len(raw), status="processing",
    )
    db.add(meta); db.commit(); db.refresh(meta)

    base_meta = {"source": source, "file_name": file.filename, "uploaded_by": user.email,
                 "uploaded_at": datetime.utcnow().isoformat(), "doc_id": str(meta.id)}
    n = _embed_and_store(docs_db, chunks, base_meta)

    meta.chunks = n; meta.status = "ready"
    db.commit(); db.refresh(meta)
    return meta


@router.post("/upload-text", response_model=schemas.DocumentOut)
def upload_text(
    payload: schemas.TextUploadIn,
    db: Session = Depends(get_db),
    docs_db: Session = Depends(get_docs_db),
    user: models.User = Depends(get_current_user),
):
    chunks = _chunk(payload.text)
    if not chunks:
        raise HTTPException(400, "Texto vacío")

    meta = models.DocumentMeta(
        file_name=payload.title, source=payload.source, uploaded_by=user.email,
        size_bytes=len(payload.text.encode()), status="processing",
    )
    db.add(meta); db.commit(); db.refresh(meta)

    base_meta = {"source": payload.source, "file_name": payload.title, "uploaded_by": user.email,
                 "uploaded_at": datetime.utcnow().isoformat(), "doc_id": str(meta.id)}
    n = _embed_and_store(docs_db, chunks, base_meta)

    meta.chunks = n; meta.status = "ready"
    db.commit(); db.refresh(meta)
    return meta

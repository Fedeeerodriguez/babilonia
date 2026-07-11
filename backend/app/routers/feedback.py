"""Loop de feedback del sandbox de Tomi.

Flujo de mejora continua:
  1. El sandbox / n8n registra cada interacción  ->  POST /api/feedback/log
  2. Un admin la califica y/o corrige             ->  POST /api/feedback/{id}/review
  3. Las correcciones aprobadas se promueven al    ->  POST /api/feedback/{id}/promote
     vector store `documents` (Tomi aprende)
  4. Métricas y export del dataset Q/A             ->  GET  /api/feedback/stats · /export

Las correcciones promovidas usan el mismo `source` que consume el bot de WATI,
así que lo aprendido queda disponible de inmediato.
"""
import os
from collections import Counter
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db, get_docs_db
from app.security import get_current_user, require_admin

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

INTERNAL_KEY = os.getenv("TOMI_INTERNAL_KEY", "")


def _auth_internal(x_tomi_key: Optional[str]) -> None:
    """Auth ligera para que el sandbox/n8n registre sin token de usuario."""
    if not INTERNAL_KEY:
        return
    if x_tomi_key != INTERNAL_KEY:
        raise HTTPException(status_code=401, detail="invalid key")


@router.post("/log")
def log_interaction(
    body: schemas.FeedbackLogIn,
    db: Session = Depends(get_db),
    x_tomi_key: Optional[str] = Header(default=None),
):
    """Registra una interacción de Tomi como pendiente de revisión.

    NO registra interacciones sin respuesta real de Tomi (mensajes salientes/template,
    o respuestas vacías cuando el agente decide no contestar a un emoji/ok): ensucian el
    sandbox y aparecen como 'bad' falsos. Devuelve 200 con {skipped:true} para que n8n
    no lo trate como error.
    """
    _auth_internal(x_tomi_key)
    if not (body.respuesta_tomi or "").strip() or not (body.pregunta or "").strip():
        return {"skipped": True, "reason": "sin respuesta_tomi o pregunta — no se registra"}
    fb = models.SandboxFeedback(
        pregunta=body.pregunta,
        respuesta_tomi=body.respuesta_tomi,
        canal=body.canal,
        source=body.source,
        publico=body.publico,
        user_email=body.user_email,
        status=models.FeedbackStatus.pending.value,
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return schemas.FeedbackOut.model_validate(fb)


@router.get("", response_model=List[schemas.FeedbackOut])
def list_feedback(
    status: Optional[str] = Query(None, description="pending | reviewed | promoted"),
    rating: Optional[str] = Query(None, description="good | mejorable | bad"),
    canal: Optional[str] = None,
    publico: Optional[str] = Query(None, description="cliente | asesor | prospecto | estudiante | otro"),
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    q = db.query(models.SandboxFeedback)
    if status:
        q = q.filter(models.SandboxFeedback.status == status)
    if rating:
        q = q.filter(models.SandboxFeedback.rating == rating)
    if canal:
        q = q.filter(models.SandboxFeedback.canal == canal)
    if publico:
        q = q.filter(models.SandboxFeedback.publico == publico)
    return (
        q.order_by(models.SandboxFeedback.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.post("/{fb_id}/review", response_model=schemas.FeedbackOut)
def review_feedback(
    fb_id: int,
    body: schemas.FeedbackReviewIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """El admin/asesor califica y/o corrige una interacción."""
    fb = db.get(models.SandboxFeedback, fb_id)
    if not fb:
        raise HTTPException(404, "Feedback no encontrado")
    if body.rating is not None:
        if body.rating not in ("good", "mejorable", "bad"):
            raise HTTPException(400, "rating debe ser 'good', 'mejorable' o 'bad'")
        fb.rating = body.rating
    if body.respuesta_corregida is not None:
        fb.respuesta_corregida = body.respuesta_corregida
    if body.tags is not None:
        fb.tags = body.tags
    if body.publico is not None:
        fb.publico = body.publico
    fb.status = models.FeedbackStatus.reviewed.value
    fb.reviewed_by = user.email
    fb.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(fb)
    return fb


@router.post("/{fb_id}/promote", response_model=schemas.FeedbackOut)
def promote_feedback(
    fb_id: int,
    source: Optional[str] = Query(None, description="source destino en el vector store"),
    db: Session = Depends(get_db),
    docs_db: Session = Depends(get_docs_db),
    _: models.User = Depends(require_admin),
):
    """Carga la corrección aprobada al vector store `documents` (Tomi aprende).

    Solo admin. Usa la respuesta corregida (o, si no hay, la de Tomi marcada como
    'good'). El chunk se embebe como un par Q/A consultable por el bot.
    """
    fb = db.get(models.SandboxFeedback, fb_id)
    if not fb:
        raise HTTPException(404, "Feedback no encontrado")

    respuesta = fb.respuesta_corregida or (
        fb.respuesta_tomi if fb.rating == "good" else None
    )
    if not respuesta:
        raise HTTPException(
            400,
            "No hay respuesta para promover (corregí la respuesta o marcala como 'good').",
        )

    dest_source = source or fb.source or "feedback"
    contenido = f"Pregunta: {fb.pregunta}\nRespuesta: {respuesta}"

    # Reutiliza el pipeline de embeddings de documents.py
    from app.routers.documents import _embed_and_store

    meta = {
        "source": dest_source,
        "origin": "sandbox_feedback",
        "feedback_id": fb.id,
        "title": f"Feedback #{fb.id}",
    }
    _embed_and_store(docs_db, [contenido], meta)

    fb.status = models.FeedbackStatus.promoted.value
    fb.promoted_doc_source = dest_source
    db.commit()
    db.refresh(fb)
    return fb


@router.get("/stats", response_model=schemas.FeedbackStats)
def feedback_stats(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    rows = db.query(models.SandboxFeedback).all()
    total = len(rows)
    pendientes = sum(1 for r in rows if r.status == models.FeedbackStatus.pending.value)
    revisadas = sum(1 for r in rows if r.status == models.FeedbackStatus.reviewed.value)
    promovidas = sum(1 for r in rows if r.status == models.FeedbackStatus.promoted.value)
    good = sum(1 for r in rows if r.rating == "good")
    mejorable = sum(1 for r in rows if r.rating == "mejorable")
    bad = sum(1 for r in rows if r.rating == "bad")
    # "Correctas a la primera" = good sobre el total de calificadas (la métrica de la Semana 1).
    calificadas = good + mejorable + bad
    tasa = round(good / calificadas, 3) if calificadas else 0.0

    tag_counter: Counter = Counter()
    for r in rows:
        if r.rating in ("bad", "mejorable") and isinstance(r.tags, list):
            tag_counter.update(r.tags)
    top_tags = [{"tag": t, "count": c} for t, c in tag_counter.most_common(10)]

    # Desglose por tipo de público (entregable del Martes / línea base del Viernes).
    pub_stats: dict = {}
    for r in rows:
        if r.rating not in ("good", "mejorable", "bad"):
            continue
        p = r.publico or "sin_clasificar"
        s = pub_stats.setdefault(p, {"good": 0, "mejorable": 0, "bad": 0})
        s[r.rating] += 1
    por_publico = []
    for p, s in sorted(pub_stats.items()):
        tot = s["good"] + s["mejorable"] + s["bad"]
        por_publico.append({
            "publico": p,
            "total": tot,
            "good": s["good"],
            "mejorable": s["mejorable"],
            "bad": s["bad"],
            "tasa": round(s["good"] / tot, 3) if tot else 0.0,
        })

    return schemas.FeedbackStats(
        total=total,
        pendientes=pendientes,
        revisadas=revisadas,
        promovidas=promovidas,
        good=good,
        mejorable=mejorable,
        bad=bad,
        tasa_aprobacion=tasa,
        top_tags_malos=top_tags,
        por_publico=por_publico,
    )


@router.get("/export")
def export_dataset(
    only_good: bool = Query(True, description="Solo pares aprobados (good o corregidos)"),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    """Exporta el dataset Q/A para fine-tuning o re-embedding offline."""
    q = db.query(models.SandboxFeedback)
    rows = q.order_by(models.SandboxFeedback.created_at.asc()).all()
    dataset = []
    for r in rows:
        respuesta = r.respuesta_corregida or (
            r.respuesta_tomi if r.rating == "good" else None
        )
        if only_good and not respuesta:
            continue
        dataset.append({
            "pregunta": r.pregunta,
            "respuesta": respuesta or r.respuesta_tomi,
            "source": r.source,
            "publico": r.publico,
            "rating": r.rating,
            "fue_corregida": bool(r.respuesta_corregida),
        })
    return {"count": len(dataset), "dataset": dataset}

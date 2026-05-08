from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, desc
from app import models, schemas
from app.database import get_db
from app.security import get_current_user

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=List[schemas.ConversationSummary])
def list_conversations(
    q: Optional[str] = None,
    asesor: Optional[str] = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    M = models.Message
    # Por waId: último mensaje + count. Usamos subquery sobre last per group.
    sub = (
        db.query(
            M.wa_id,
            func.max(M.created_at).label("last_at"),
            func.count(M.id).label("cnt"),
        )
        .group_by(M.wa_id)
    )
    if asesor:
        sub = sub.filter(M.operator_name == asesor)
    if q:
        like = f"%{q}%"
        sub = sub.filter(or_(M.wa_id.ilike(like), M.sender_name.ilike(like)))
    sub = sub.order_by(desc("last_at")).limit(limit).subquery()

    out = []
    for row in db.query(sub).all():
        last = (
            db.query(M)
            .filter(M.wa_id == row.wa_id, M.created_at == row.last_at)
            .first()
        )
        if not last:
            continue
        out.append({
            "wa_id": row.wa_id,
            "sender_name": last.sender_name,
            "last_message_at": last.created_at,
            "message_count": row.cnt,
            "last_direction": last.direction,
            "last_content": last.content,
        })
    return out


@router.get("/{wa_id}", response_model=List[schemas.MessageOut])
def conversation_detail(
    wa_id: str,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    msgs = db.query(models.Message).filter(models.Message.wa_id == wa_id).order_by(models.Message.created_at.asc()).all()
    if not msgs:
        raise HTTPException(404, "Conversación no encontrada")
    return msgs

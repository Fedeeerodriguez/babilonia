"""HUD endpoint — datos compactos para la barra superior."""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from app import models
from app.database import get_db
from app.security import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/hud")
def hud(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    M = models.Message
    base = db.query(M).filter(M.created_at >= since)

    sent = base.filter(M.direction.in_([models.MessageDirection.asesor, models.MessageDirection.bot, models.MessageDirection.template])).count()
    received = base.filter(M.direction == models.MessageDirection.cliente).count()
    open_convs = db.query(func.count(func.distinct(M.wa_id))).filter(M.created_at >= since).scalar() or 0

    return {
        "user": user.full_name or user.email,
        "sent_24h": sent,
        "received_24h": received,
        "open_conversations": open_convs,
        "ts": now.isoformat(),
    }

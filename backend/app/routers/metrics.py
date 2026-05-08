from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from app import models
from app.database import get_db, engine
from app.security import get_current_user

router = APIRouter(prefix="/api/metrics", tags=["metrics"])

D = models.MessageDirection
M = models.Message
IS_PG = engine.dialect.name in ("postgresql", "postgres")


def _range(from_: Optional[datetime], to: Optional[datetime]):
    to = to or datetime.now(timezone.utc)
    from_ = from_ or (to - timedelta(days=7))
    return from_, to


def _avg_response_seconds(db: Session, from_: datetime, to: datetime) -> Optional[float]:
    """Promedio del gap entre mensaje cliente y la siguiente respuesta. Postgres con window functions; SQLite con fallback Python."""
    if IS_PG:
        v = db.execute(text("""
            WITH ordered AS (
              SELECT wa_id, direction, created_at,
                     LEAD(direction)  OVER (PARTITION BY wa_id ORDER BY created_at) AS next_dir,
                     LEAD(created_at) OVER (PARTITION BY wa_id ORDER BY created_at) AS next_at
              FROM messages WHERE created_at BETWEEN :f AND :t
            )
            SELECT AVG(EXTRACT(EPOCH FROM (next_at - created_at)))
            FROM ordered
            WHERE direction = 'cliente' AND next_dir IN ('asesor','bot','template')
        """), {"f": from_, "t": to}).scalar()
        return float(v) if v is not None else None
    # SQLite: traer mensajes y calcular en Python
    rows = db.query(M.wa_id, M.direction, M.created_at).filter(
        M.created_at >= from_, M.created_at <= to
    ).order_by(M.wa_id, M.created_at).all()
    deltas = []
    for i, r in enumerate(rows[:-1]):
        nxt = rows[i + 1]
        if r.wa_id == nxt.wa_id and r.direction == D.cliente and nxt.direction in (D.asesor, D.bot, D.template):
            deltas.append((nxt.created_at - r.created_at).total_seconds())
    return sum(deltas) / len(deltas) if deltas else None


@router.get("/summary")
def summary(
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = None,
    asesor: Optional[str] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    from_, to = _range(from_, to)
    q = db.query(M).filter(M.created_at >= from_, M.created_at <= to)
    if asesor:
        q = q.filter(M.operator_name == asesor)

    received = q.filter(M.direction == D.cliente).count()
    advisor_replies = q.filter(M.direction == D.asesor).count()
    bot_replies = q.filter(M.direction == D.bot).count()
    templates = q.filter(M.direction == D.template).count()
    sent = advisor_replies + bot_replies + templates

    return {
        "sent": sent,
        "received": received,
        "advisor_replies": advisor_replies,
        "bot_replies": bot_replies,
        "avg_response_seconds": _avg_response_seconds(db, from_, to),
        "period_from": from_.isoformat(),
        "period_to": to.isoformat(),
    }


@router.get("/timeseries")
def timeseries(
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = None,
    bucket: str = Query("day", regex="^(hour|day|week)$"),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    from_, to = _range(from_, to)
    if IS_PG:
        rows = db.execute(text("""
            SELECT date_trunc(:bucket, created_at) AS b,
                   SUM(CASE WHEN direction = 'cliente' THEN 1 ELSE 0 END) AS received,
                   SUM(CASE WHEN direction = 'asesor'  THEN 1 ELSE 0 END) AS advisor_replies,
                   SUM(CASE WHEN direction IN ('bot','template') THEN 1 ELSE 0 END) AS bot_replies
            FROM messages WHERE created_at BETWEEN :f AND :t
            GROUP BY b ORDER BY b
        """), {"bucket": bucket, "f": from_, "t": to}).all()
        return [{"bucket": r.b.isoformat(), "received": r.received,
                 "advisor_replies": r.advisor_replies, "bot_replies": r.bot_replies} for r in rows]
    # SQLite
    fmt = {"hour": "%Y-%m-%dT%H:00:00", "day": "%Y-%m-%d", "week": "%Y-W%W"}[bucket]
    rows = db.execute(text(f"""
        SELECT strftime('{fmt}', created_at) AS b,
               SUM(CASE WHEN direction = 'cliente' THEN 1 ELSE 0 END) AS received,
               SUM(CASE WHEN direction = 'asesor'  THEN 1 ELSE 0 END) AS advisor_replies,
               SUM(CASE WHEN direction IN ('bot','template') THEN 1 ELSE 0 END) AS bot_replies
        FROM messages WHERE created_at BETWEEN :f AND :t
        GROUP BY b ORDER BY b
    """), {"f": from_, "t": to}).all()
    return [{"bucket": r.b, "received": r.received, "advisor_replies": r.advisor_replies, "bot_replies": r.bot_replies} for r in rows]


@router.get("/by-advisor")
def by_advisor(
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    from_, to = _range(from_, to)
    rows = db.query(M.operator_name, func.count(M.id).label("replies")).filter(
        M.direction == D.asesor, M.created_at >= from_, M.created_at <= to,
    ).group_by(M.operator_name).order_by(func.count(M.id).desc()).all()
    return [{"operator_name": r.operator_name, "replies": r.replies} for r in rows]

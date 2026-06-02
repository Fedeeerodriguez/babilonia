"""
Analítica de respuestas de Tomi.

Lee de la tabla `tomi_conversaciones` (Supabase, proyecto babilonia) — la
misma donde n8n loguea cada interacción. Expone KPIs, serie temporal,
top usuarios / herramientas y un listado paginable con drill-down.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.security import get_current_user
from app import models

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _range(from_: Optional[datetime], to: Optional[datetime]):
    to = to or datetime.now(timezone.utc)
    from_ = from_ or (to - timedelta(days=7))
    return from_, to


def _table_exists(db: Session) -> bool:
    try:
        db.execute(text("SELECT 1 FROM tomi_conversaciones LIMIT 1"))
        return True
    except Exception:
        db.rollback()
        return False


@router.get("/summary")
def summary(
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    from_, to = _range(from_, to)
    if not _table_exists(db):
        return {"enabled": False, "msg": "tomi_conversaciones no existe todavía"}

    row = db.execute(text("""
        SELECT
          COUNT(*) AS total,
          COUNT(DISTINCT user_id) AS usuarios_unicos,
          AVG(latencia_ms)::int AS latencia_promedio_ms,
          AVG(tokens_input + tokens_output)::int AS tokens_promedio,
          SUM(tokens_input + tokens_output) AS tokens_totales
        FROM tomi_conversaciones
        WHERE created_at BETWEEN :f AND :t
    """), {"f": from_, "t": to}).mappings().first()

    return {
        "enabled": True,
        "period_from": from_.isoformat(),
        "period_to": to.isoformat(),
        **dict(row or {}),
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
    if not _table_exists(db):
        return []
    rows = db.execute(text("""
        SELECT date_trunc(:bucket, created_at) AS b,
               COUNT(*) AS total,
               AVG(latencia_ms)::int AS lat_ms
        FROM tomi_conversaciones
        WHERE created_at BETWEEN :f AND :t
        GROUP BY b ORDER BY b
    """), {"bucket": bucket, "f": from_, "t": to}).all()
    return [{"bucket": r.b.isoformat(), "total": r.total, "latencia_ms": r.lat_ms} for r in rows]


@router.get("/top-users")
def top_users(
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    from_, to = _range(from_, to)
    if not _table_exists(db):
        return []
    rows = db.execute(text("""
        SELECT user_id, COALESCE(MAX(user_nombre), '') AS nombre, COUNT(*) AS interacciones,
               MAX(created_at) AS ultima
        FROM tomi_conversaciones
        WHERE created_at BETWEEN :f AND :t
        GROUP BY user_id ORDER BY interacciones DESC LIMIT :lim
    """), {"f": from_, "t": to, "lim": limit}).all()
    return [{"user_id": r.user_id, "nombre": r.nombre,
             "interacciones": r.interacciones, "ultima": r.ultima.isoformat() if r.ultima else None}
            for r in rows]


@router.get("/top-tools")
def top_tools(
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    from_, to = _range(from_, to)
    if not _table_exists(db):
        return []
    rows = db.execute(text("""
        SELECT tool, COUNT(*) AS uso
        FROM tomi_conversaciones,
             LATERAL jsonb_array_elements_text(COALESCE(herramientas_usadas, '[]'::jsonb)) AS tool
        WHERE created_at BETWEEN :f AND :t
        GROUP BY tool ORDER BY uso DESC
    """), {"f": from_, "t": to}).all()
    return [{"tool": r.tool, "uso": r.uso} for r in rows]


@router.get("/conversaciones")
def listado(
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = None,
    q: Optional[str] = None,
    user_id: Optional[str] = None,
    canal: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    from_, to = _range(from_, to)
    if not _table_exists(db):
        return {"items": [], "total": 0}

    where = ["created_at BETWEEN :f AND :t"]
    params = {"f": from_, "t": to, "lim": limit, "off": offset}
    if q:
        where.append("(mensaje_usuario ILIKE :q OR respuesta_tomi ILIKE :q OR user_nombre ILIKE :q)")
        params["q"] = f"%{q}%"
    if user_id:
        where.append("user_id = :uid")
        params["uid"] = user_id
    if canal:
        where.append("canal = :canal")
        params["canal"] = canal
    where_sql = " AND ".join(where)

    total = db.execute(text(f"SELECT COUNT(*) FROM tomi_conversaciones WHERE {where_sql}"),
                       params).scalar()
    rows = db.execute(text(f"""
        SELECT id, created_at, canal, user_id, user_nombre,
               LEFT(mensaje_usuario, 200) AS mensaje_usuario,
               LEFT(respuesta_tomi, 400) AS respuesta_tomi,
               herramientas_usadas, latencia_ms,
               (tokens_input + tokens_output) AS tokens
        FROM tomi_conversaciones
        WHERE {where_sql}
        ORDER BY created_at DESC LIMIT :lim OFFSET :off
    """), params).mappings().all()
    return {"total": total, "items": [dict(r) for r in rows]}


@router.get("/conversacion/{conv_id}")
def detalle(
    conv_id: str,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    if not _table_exists(db):
        raise HTTPException(404, "tabla no existe")
    row = db.execute(text("""
        SELECT * FROM tomi_conversaciones WHERE id = :id
    """), {"id": conv_id}).mappings().first()
    if not row:
        raise HTTPException(404, "no encontrado")
    return dict(row)

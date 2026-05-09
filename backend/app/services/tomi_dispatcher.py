"""Dispatcher 23h: cron interno que reemplaza el workflow tomi-trigger-23h de n8n.

Cada 5 min:
  1. Encuentra conversaciones donde el último mensaje del cliente tiene 23–24h
     y no hay nada posterior.
  2. POST al webhook de tomi unificado con el payload.
  3. tomi unificado arma la respuesta y la manda por WATI.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
import httpx
from sqlalchemy import text
from app.database import SessionLocal, engine

IS_PG = engine.dialect.name in ("postgresql", "postgres")

log = logging.getLogger(__name__)

TOMI_WEBHOOK_URL = os.getenv("TOMI_WEBHOOK_URL", "")  # ej: https://n8n.babilonia.ai/webhook/tomi-responder
DISPATCH_INTERVAL_MINUTES = int(os.getenv("TOMI_DISPATCH_INTERVAL_MINUTES", "5"))


PG_QUERY = """
WITH last_user AS (
  SELECT DISTINCT ON (wa_id)
         wa_id, sender_name, content, created_at
  FROM messages
  WHERE direction = 'cliente'
  ORDER BY wa_id, created_at DESC
)
SELECT lu.wa_id,
       lu.sender_name,
       lu.content    AS last_user_message,
       lu.created_at AS user_at,
       EXTRACT(EPOCH FROM (NOW() - lu.created_at))::int AS waited_seconds
FROM last_user lu
WHERE lu.created_at <= NOW() - INTERVAL '23 hours'
  AND lu.created_at >  NOW() - INTERVAL '24 hours'
  AND NOT EXISTS (
    SELECT 1 FROM messages m
    WHERE m.wa_id = lu.wa_id AND m.created_at > lu.created_at
  )
LIMIT 20
"""

SQLITE_QUERY = """
WITH last_user AS (
  SELECT wa_id, sender_name, content, created_at
  FROM messages m1
  WHERE direction = 'cliente'
    AND created_at = (
      SELECT MAX(created_at) FROM messages m2
      WHERE m2.wa_id = m1.wa_id AND m2.direction = 'cliente'
    )
)
SELECT lu.wa_id,
       lu.sender_name,
       lu.content    AS last_user_message,
       lu.created_at AS user_at,
       CAST((julianday('now') - julianday(lu.created_at)) * 86400 AS INTEGER) AS waited_seconds
FROM last_user lu
WHERE julianday(lu.created_at) <= julianday('now', '-23 hours')
  AND julianday(lu.created_at) >  julianday('now', '-24 hours')
  AND NOT EXISTS (
    SELECT 1 FROM messages m
    WHERE m.wa_id = lu.wa_id AND m.created_at > lu.created_at
  )
LIMIT 20
"""


def find_pending_candidates() -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        rows = db.execute(text(PG_QUERY if IS_PG else SQLITE_QUERY)).all()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


def fire_to_tomi(candidate: Dict[str, Any]) -> bool:
    if not TOMI_WEBHOOK_URL:
        log.warning("TOMI_WEBHOOK_URL no configurada, skip dispatch")
        return False
    try:
        with httpx.Client(timeout=30) as client:
            r = client.post(TOMI_WEBHOOK_URL, json={
                "wa_id": candidate["wa_id"],
                "sender_name": candidate.get("sender_name") or "",
                "last_user_message": candidate["last_user_message"],
                "user_at": candidate["user_at"].isoformat() if hasattr(candidate["user_at"], "isoformat") else str(candidate["user_at"]),
                "waited_seconds": int(candidate["waited_seconds"]),
            })
        log.info("→ Tomi disparado para %s (status %s)", candidate["wa_id"], r.status_code)
        return r.status_code < 400
    except Exception as e:
        log.error("Error disparando Tomi para %s: %s", candidate["wa_id"], e)
        return False


def run_once() -> Dict[str, Any]:
    """Ejecuta un tick. Útil para llamar manualmente desde un endpoint."""
    candidates = find_pending_candidates()
    fired = 0
    for c in candidates:
        if fire_to_tomi(c):
            fired += 1
    log.info("Dispatcher tick: %d candidatos, %d disparados", len(candidates), fired)
    return {"candidates": len(candidates), "fired": fired, "items": candidates}

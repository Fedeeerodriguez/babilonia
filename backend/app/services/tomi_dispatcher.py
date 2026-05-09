"""Dispatcher Tomi — dos escenarios de disparo:

A) Trigger-23h (comportamiento original):
   El último mensaje del CLIENTE lleva 23-24 h sin respuesta de nadie.
   → Tomi retoma la conversación.

B) Ventana-24h-humano (nuevo):
   Un ASESOR contestó manualmente hace 23-24 h y el cliente NO volvió
   a escribir desde entonces.
   → La ventana de silencio del bot expiró. Tomi retoma incluyendo
     el historial de la conversación en el payload (campo `history`)
     para tener contexto de lo que se habló.

Configurable vía env:
  TOMI_WEBHOOK_URL              URL del webhook de n8n / responder
  TOMI_DISPATCH_INTERVAL_MINUTES  cada cuántos min corre el cron (default 5)
  TOMI_HUMAN_WINDOW_HOURS         ventana de silencio tras respuesta humana
                                  (default 24)
"""
import logging
import os
from typing import List, Dict, Any

import httpx
from sqlalchemy import text

from app.database import SessionLocal, engine

IS_PG = engine.dialect.name in ("postgresql", "postgres")

log = logging.getLogger(__name__)

TOMI_WEBHOOK_URL = os.getenv("TOMI_WEBHOOK_URL", "")
DISPATCH_INTERVAL_MINUTES = int(os.getenv("TOMI_DISPATCH_INTERVAL_MINUTES", "5"))
HUMAN_WINDOW_HOURS = int(os.getenv("TOMI_HUMAN_WINDOW_HOURS", "24"))

# ─────────────────────────── QUERIES ────────────────────────────────

# ── Escenario A: cliente esperando 23-24 h sin ninguna respuesta ─────

PG_QUERY_CLIENT = """
WITH last_user AS (
  SELECT DISTINCT ON (wa_id)
    wa_id, sender_name, content, created_at
  FROM messages
  WHERE direction = 'cliente'
  ORDER BY wa_id, created_at DESC
)
SELECT lu.wa_id,
       lu.sender_name,
       lu.content          AS last_user_message,
       lu.created_at       AS user_at,
       EXTRACT(EPOCH FROM (NOW() - lu.created_at))::int AS waited_seconds
FROM last_user lu
WHERE lu.created_at <= NOW() - INTERVAL '23 hours'
  AND lu.created_at >  NOW() - INTERVAL '24 hours'
  AND NOT EXISTS (
    SELECT 1 FROM messages m
    WHERE m.wa_id = lu.wa_id
      AND m.created_at > lu.created_at
  )
LIMIT 20
"""

SQLITE_QUERY_CLIENT = """
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
    WHERE m.wa_id = lu.wa_id
      AND m.created_at > lu.created_at
  )
LIMIT 20
"""

# ── Escenario B: ventana 24 h del asesor expirada ───────────────────

PG_QUERY_HUMAN_WINDOW = """
WITH last_asesor AS (
  SELECT DISTINCT ON (wa_id)
    wa_id, sender_name, content, created_at
  FROM messages
  WHERE direction = 'asesor'
  ORDER BY wa_id, created_at DESC
)
SELECT la.wa_id,
       la.sender_name,
       la.content          AS last_asesor_message,
       la.created_at       AS asesor_at,
       EXTRACT(EPOCH FROM (NOW() - la.created_at))::int AS waited_seconds
FROM last_asesor la
WHERE la.created_at <= NOW() - INTERVAL '23 hours'
  AND la.created_at >  NOW() - INTERVAL '24 hours'
  AND NOT EXISTS (
    SELECT 1 FROM messages m
    WHERE m.wa_id = la.wa_id
      AND m.direction = 'cliente'
      AND m.created_at > la.created_at
  )
LIMIT 20
"""

SQLITE_QUERY_HUMAN_WINDOW = """
WITH last_asesor AS (
  SELECT wa_id, sender_name, content, created_at
  FROM messages m1
  WHERE direction = 'asesor'
    AND created_at = (
      SELECT MAX(created_at) FROM messages m2
      WHERE m2.wa_id = m1.wa_id AND m2.direction = 'asesor'
    )
)
SELECT la.wa_id,
       la.sender_name,
       la.content    AS last_asesor_message,
       la.created_at AS asesor_at,
       CAST((julianday('now') - julianday(la.created_at)) * 86400 AS INTEGER) AS waited_seconds
FROM last_asesor la
WHERE julianday(la.created_at) <= julianday('now', '-23 hours')
  AND julianday(la.created_at) >  julianday('now', '-24 hours')
  AND NOT EXISTS (
    SELECT 1 FROM messages m
    WHERE m.wa_id = la.wa_id
      AND m.direction = 'cliente'
      AND m.created_at > la.created_at
  )
LIMIT 20
"""

# ── Historial de conversación (adjunto en Escenario B) ──────────────

HISTORY_QUERY = """
SELECT direction, content, created_at
FROM messages
WHERE wa_id = :wa_id
ORDER BY created_at DESC
LIMIT :limit
"""


def _get_history(db, wa_id: str, limit: int = 30) -> List[Dict]:
    """Devuelve los últimos `limit` mensajes de la convo, en orden cronológico."""
    rows = db.execute(text(HISTORY_QUERY), {"wa_id": wa_id, "limit": limit}).all()
    return [
        {
            "direction": r.direction,
            "content": r.content,
            "at": (
                r.created_at.isoformat()
                if hasattr(r.created_at, "isoformat")
                else str(r.created_at)
            ),
        }
        for r in reversed(rows)
    ]


# ─────────────────────────── FINDERS ────────────────────────────────

def find_client_candidates() -> List[Dict[str, Any]]:
    """Escenario A: cliente esperando 23-24 h sin respuesta."""
    db = SessionLocal()
    try:
        q = PG_QUERY_CLIENT if IS_PG else SQLITE_QUERY_CLIENT
        rows = db.execute(text(q)).all()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


def find_human_window_candidates() -> List[Dict[str, Any]]:
    """Escenario B: ventana 24 h del asesor expirada."""
    db = SessionLocal()
    try:
        q = PG_QUERY_HUMAN_WINDOW if IS_PG else SQLITE_QUERY_HUMAN_WINDOW
        rows = db.execute(text(q)).all()
        candidates = []
        for r in rows:
            c = dict(r._mapping)
            c["history"] = _get_history(db, c["wa_id"])  # historial para contexto
            candidates.append(c)
        return candidates
    finally:
        db.close()


# ─────────────────────────── WEBHOOK ────────────────────────────────

def fire_to_tomi(candidate: Dict[str, Any], trigger: str = "client_23h") -> bool:
    """Envía el payload al webhook de Tomi.

    trigger values:
      "client_23h"          – Escenario A
      "human_window_expired" – Escenario B (incluye campo history)
    """
    if not TOMI_WEBHOOK_URL:
        log.warning("TOMI_WEBHOOK_URL no configurada, skip dispatch")
        return False

    payload: Dict[str, Any] = {
        "trigger": trigger,
        "wa_id": candidate["wa_id"],
        "sender_name": candidate.get("sender_name") or "",
        "waited_seconds": int(candidate.get("waited_seconds", 0)),
    }

    if trigger == "client_23h":
        payload["last_user_message"] = candidate["last_user_message"]
        payload["user_at"] = (
            candidate["user_at"].isoformat()
            if hasattr(candidate["user_at"], "isoformat")
            else str(candidate["user_at"])
        )
    else:  # human_window_expired
        payload["last_asesor_message"] = candidate["last_asesor_message"]
        payload["asesor_at"] = (
            candidate["asesor_at"].isoformat()
            if hasattr(candidate["asesor_at"], "isoformat")
            else str(candidate["asesor_at"])
        )
        payload["history"] = candidate.get("history", [])

    try:
        with httpx.Client(timeout=30) as client:
            r = client.post(TOMI_WEBHOOK_URL, json=payload)
        log.info(
            "→ Tomi [%s] disparado para %s (HTTP %s)",
            trigger, candidate["wa_id"], r.status_code,
        )
        return r.status_code < 400
    except Exception as e:
        log.error("Error disparando Tomi para %s: %s", candidate["wa_id"], e)
        return False


# ──────────────────────────── TICK ──────────────────────────────────

def run_once() -> Dict[str, Any]:
    """Ejecuta un tick completo (Escenario A + B). Llamado por el cron."""
    fired = 0
    fired_wa_ids: set = set()  # evita doble disparo si ambos escenarios coinciden

    # ── Escenario A ──────────────────────────────────────────────────
    client_candidates = find_client_candidates()
    for c in client_candidates:
        if c["wa_id"] not in fired_wa_ids:
            if fire_to_tomi(c, trigger="client_23h"):
                fired += 1
                fired_wa_ids.add(c["wa_id"])

    # ── Escenario B ──────────────────────────────────────────────────
    human_candidates = find_human_window_candidates()
    for c in human_candidates:
        if c["wa_id"] not in fired_wa_ids:
            if fire_to_tomi(c, trigger="human_window_expired"):
                fired += 1
                fired_wa_ids.add(c["wa_id"])

    total = len(client_candidates) + len(human_candidates)
    log.info(
        "Dispatcher tick: %d candidatos (%dA + %dB), %d disparados",
        total, len(client_candidates), len(human_candidates), fired,
    )
    return {
        "candidates": total,
        "fired": fired,
        "client_candidates": len(client_candidates),
        "human_window_candidates": len(human_candidates),
    }

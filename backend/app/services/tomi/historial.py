"""Servicio de historial WATI: últimos mensajes y filtro 23h (humano respondió).

Reemplaza los nodos Postgres + IF + Code "Filtro 23h" del workflow n8n por
endpoints determinísticos.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger("tomi.historial")

ADMIN_EMAIL = "admin@babilonia.ai"


def humano_respondio_recientemente(
    db: Session,
    wa_id: str,
    hours: int = 23,
) -> Dict[str, Any]:
    """True si un asesor humano (no admin, no bot) escribió en las últimas N horas."""
    if not wa_id:
        return {"humano_count": 0, "bloquear": False}
    row = db.execute(text("""
        SELECT COUNT(*)::int AS c
        FROM messages
        WHERE wa_id = :wa
          AND direction = 'asesor'
          AND operator_email IS NOT NULL
          AND operator_email != :admin
          AND created_at > NOW() - (:h || ' hours')::interval
    """), {"wa": wa_id, "admin": ADMIN_EMAIL, "h": str(hours)}).mappings().first()
    count = (row or {}).get("c", 0)
    return {"humano_count": count, "bloquear": count > 0}


def ultimos_mensajes(
    db: Session,
    wa_id: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Devuelve los últimos N mensajes de un wa_id (orden cronológico ascendente)."""
    if not wa_id:
        return []
    try:
        rows = db.execute(text("""
            SELECT id, direction, content, operator_name, operator_email,
                   message_type, template_name, created_at
            FROM messages
            WHERE wa_id = :wa
            ORDER BY created_at DESC
            LIMIT :lim
        """), {"wa": wa_id, "lim": limit}).mappings().all()
    except Exception as e:
        log.error("ultimos_mensajes falló: %s", e)
        return []
    out = [dict(r) for r in rows]
    # Devolver del más viejo al más nuevo para que el LLM lo lea como chat
    out.reverse()
    # Cast datetime y uuid a str
    for r in out:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()
        if r.get("id") is not None:
            r["id"] = str(r["id"])
    return out


def buscar_correo_en_historial(
    db: Session,
    wa_id: str,
    lookback: int = 50,
) -> Optional[str]:
    """Busca un email mencionado en los últimos mensajes del cliente (cliente direction)."""
    import re
    if not wa_id:
        return None
    try:
        rows = db.execute(text("""
            SELECT content FROM messages
            WHERE wa_id = :wa AND direction = 'cliente'
            ORDER BY created_at DESC
            LIMIT :lim
        """), {"wa": wa_id, "lim": lookback}).mappings().all()
    except Exception as e:
        log.error("buscar_correo_en_historial falló: %s", e)
        return None
    pattern = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
    for r in rows:
        m = pattern.search(r.get("content") or "")
        if m:
            return m.group(0).lower()
    return None

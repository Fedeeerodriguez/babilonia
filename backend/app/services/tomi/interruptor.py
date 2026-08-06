"""Interruptor global de la automatización de Tomi (kill switch).

La decisión vive ACÁ, en el backend — no en el JSON de n8n. La plataforma (botón
admin) prende/apaga; el clasificador —primer endpoint que toca cada mensaje— lee
este flag y, si está apagado, responde `pausado: true`. n8n solo obedece ese
booleano (un mini-gate), así que la lógica de on/off es 100% código.

- Se persiste en la tabla `tomi_settings` (sobrevive reinicios, compartido entre
  workers).
- Se cachea unos segundos en memoria para no pegarle a la DB en cada mensaje.
- Fail-open: si la DB falla o no hay fila, se asume ACTIVO. Nunca callamos a Tomi
  por un hipo de infraestructura; solo un apagado explícito lo silencia.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app import models

log = logging.getLogger("tomi.interruptor")

CLAVE = "automation_enabled"
_TTL = 3.0  # segundos de caché en memoria (efecto casi inmediato al togglear)
_cache: Dict[str, Any] = {"enabled": True, "ts": 0.0}


def _leer_db(db: Session) -> Optional[models.TomiSetting]:
    return db.query(models.TomiSetting).filter(models.TomiSetting.key == CLAVE).first()


def is_enabled(db: Session) -> bool:
    """True si la automatización está activa. Fail-open ante errores."""
    now = time.time()
    if now - _cache["ts"] < _TTL:
        return bool(_cache["enabled"])
    try:
        row = _leer_db(db)
        enabled = True if row is None else (row.value == "1")
        _cache.update(enabled=enabled, ts=now)
        return enabled
    except Exception as e:  # noqa: BLE001
        log.warning("interruptor: no pude leer estado (%s) — asumo ACTIVO", e)
        return True


def get_state(db: Session) -> Dict[str, Any]:
    """Estado detallado para la plataforma."""
    try:
        row = _leer_db(db)
        enabled = True if row is None else (row.value == "1")
        return {
            "enabled": enabled,
            "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
            "updated_by": row.updated_by if row else None,
        }
    except Exception as e:  # noqa: BLE001
        log.warning("interruptor.get_state falló (%s) — asumo ACTIVO", e)
        return {"enabled": True, "updated_at": None, "updated_by": None, "error": str(e)}


def set_enabled(db: Session, enabled: bool, actor: Optional[str] = None) -> Dict[str, Any]:
    """Prende/apaga la automatización y bustea la caché para efecto inmediato."""
    row = _leer_db(db)
    now = datetime.now(timezone.utc)
    if row is None:
        row = models.TomiSetting(
            key=CLAVE, value="1" if enabled else "0", updated_at=now, updated_by=actor
        )
        db.add(row)
    else:
        row.value = "1" if enabled else "0"
        row.updated_at = now
        row.updated_by = actor
    db.commit()
    _cache.update(enabled=bool(enabled), ts=time.time())
    log.info("interruptor: automatización %s por %s",
             "ACTIVADA" if enabled else "PAUSADA", actor or "?")
    return {"enabled": bool(enabled), "updated_at": now.isoformat(), "updated_by": actor}

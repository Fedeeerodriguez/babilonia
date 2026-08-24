"""Sistema de alertas de fallos de Tommy.

Un solo notificador para las 2 capas:
  - Capa A (backend): TomiSafeRoute llama a `reportar()` cuando un endpoint /api/tomi
    tira una excepción o un 422/400.
  - Capa B (n8n): el Error Workflow hace POST a /api/tomi/alerta, que llama a `reportar()`.

Qué hace `reportar()`:
  1. Calcula una FIRMA del error (capa+origen+tipo) y hace dedupe en `tomi_errores`
     (si la misma firma se repite, incrementa `count` en vez de duplicar).
  2. Manda un aviso por Telegram con rate-limit por firma (no spamea).
  3. Es 100% fail-safe: si algo falla acá (Telegram caído, DB, env sin setear),
     NUNCA propaga la excepción — solo loguea. Un fallo del sistema de alertas
     jamás puede romper un request de Tommy.

Config por env:
  TELEGRAM_ALERT_BOT_TOKEN   token del bot de @BotFather
  TELEGRAM_ALERT_CHAT_ID     chat_id destino (tu Telegram)
  TOMI_ALERT_ENABLED         "1" para activar (default: activo si hay token+chat)
  TOMI_ALERT_WINDOW_SECONDS  ventana de rate-limit por firma (default 600 = 10 min)
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import traceback
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

import httpx

from app import models
from app.database import SessionLocal

log = logging.getLogger("tomi.alertas")

_TOKEN = os.getenv("TELEGRAM_ALERT_BOT_TOKEN", "").strip()
_CHAT_ID = os.getenv("TELEGRAM_ALERT_CHAT_ID", "").strip()
_WINDOW = int(os.getenv("TOMI_ALERT_WINDOW_SECONDS", "600"))


def _enabled() -> bool:
    if os.getenv("TOMI_ALERT_ENABLED", "").strip() == "0":
        return False
    return bool(_TOKEN and _CHAT_ID)


def _firma(capa: str, origen: str, error_type: str) -> str:
    base = f"{capa}|{origen}|{error_type}".lower()
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]


def _emoji(sev: str) -> str:
    return {"WARN": "⚠️", "ERROR": "🔴", "CRITICAL": "🚨"}.get(sev, "🔴")


def _enviar_telegram(texto: str) -> None:
    """Envía un mensaje por la Bot API. Timeout corto, nunca levanta excepción."""
    if not (_TOKEN and _CHAT_ID):
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{_TOKEN}/sendMessage",
            json={
                "chat_id": _CHAT_ID,
                "text": texto[:4000],          # límite de Telegram ~4096
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=5.0,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo enviar alerta Telegram: %s", e)


def _fmt(row: Dict[str, Any]) -> str:
    sev = row.get("severidad") or "ERROR"
    partes = [
        f"{_emoji(sev)} <b>Tommy · {sev}</b>",
        f"<b>Capa:</b> {row.get('capa')}",
        f"<b>Origen:</b> <code>{row.get('origen')}</code>",
        f"<b>Error:</b> {row.get('error_type')}",
    ]
    if row.get("http_status"):
        partes.append(f"<b>HTTP:</b> {row['http_status']}")
    if row.get("mensaje"):
        partes.append(f"<b>Detalle:</b> {str(row['mensaje'])[:500]}")
    if row.get("wa_id"):
        partes.append(f"<b>Usuario:</b> <code>{row['wa_id']}</code>")
    if row.get("user_message"):
        partes.append(f"<b>Msg usuario:</b> {str(row['user_message'])[:200]}")
    if row.get("count", 1) and row["count"] > 1:
        partes.append(f"<b>Repeticiones:</b> {row['count']} (misma firma)")
    partes.append(f"<i>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</i>")
    return "\n".join(partes)


def _persistir_y_decidir(
    *, firma: str, capa: str, origen: str, error_type: str, severidad: str,
    mensaje: str, http_status: Optional[int], wa_id: Optional[str],
    user_message: Optional[str], detalle: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Upsert por firma en tomi_errores + decide si toca notificar (rate-limit).

    Devuelve el dict a notificar, o None si hay que silenciar por rate-limit.
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        existing = (
            db.query(models.TomiError)
            .filter(models.TomiError.signature == firma,
                    models.TomiError.resolved == False)  # noqa: E712
            .order_by(models.TomiError.id.desc())
            .first()
        )

        if existing:
            new_count = (existing.count or 1) + 1
            existing.count = new_count
            existing.last_seen = now
            existing.mensaje = mensaje
            existing.http_status = http_status
            existing.wa_id = wa_id
            existing.user_message = user_message
            db.commit()
            last_notif = existing.last_notified_at
            # rate-limit: no re-notificar la misma firma dentro de la ventana...
            if last_notif is not None:
                if last_notif.tzinfo is None:
                    last_notif = last_notif.replace(tzinfo=timezone.utc)
                dentro_ventana = (now - last_notif) < timedelta(seconds=_WINDOW)
                # ...salvo escalada a CRITICAL por ráfaga (múltiplos de 10).
                escala = new_count % 10 == 0
                if dentro_ventana and not escala:
                    return None
                if escala:
                    severidad = "CRITICAL"
            existing.last_notified_at = now
            existing.severidad = severidad
            db.commit()
            count = new_count
        else:
            row = models.TomiError(
                signature=firma, capa=capa, origen=origen, error_type=error_type,
                severidad=severidad, mensaje=mensaje, http_status=http_status,
                wa_id=wa_id, user_message=user_message, detalle=detalle or {},
                count=1, created_at=now, last_seen=now, last_notified_at=now,
            )
            db.add(row)
            db.commit()
            count = 1

        return {"capa": capa, "origen": origen, "error_type": error_type,
                "severidad": severidad, "mensaje": mensaje, "http_status": http_status,
                "wa_id": wa_id, "user_message": user_message, "count": count}
    finally:
        db.close()


def reportar(
    *,
    capa: str,                       # "backend" | "n8n"
    origen: str,                     # endpoint o nodo
    error_type: str,                 # tipo/clase de error
    mensaje: str = "",
    severidad: str = "ERROR",        # WARN | ERROR | CRITICAL
    http_status: Optional[int] = None,
    wa_id: Optional[str] = None,
    user_message: Optional[str] = None,
    detalle: Optional[Dict[str, Any]] = None,
    exc: Optional[BaseException] = None,
) -> None:
    """Punto de entrada único. Fail-safe: nunca levanta. Notifica en background."""
    if not _enabled():
        return

    def _run():
        try:
            det = dict(detalle or {})
            if exc is not None and "stack" not in det:
                det["stack"] = "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                )[-1500:]
            firma = _firma(capa, origen, error_type)
            row = _persistir_y_decidir(
                firma=firma, capa=capa, origen=origen, error_type=error_type,
                severidad=severidad, mensaje=mensaje or (str(exc) if exc else ""),
                http_status=http_status, wa_id=wa_id, user_message=user_message,
                detalle=det,
            )
            if row is not None:
                _enviar_telegram(_fmt(row))
        except Exception as e:  # noqa: BLE001 — el sistema de alertas NUNCA rompe nada
            log.warning("Fallo interno del notificador de alertas: %s", e)

    # En un hilo para no bloquear el request (ya está en su camino de error).
    threading.Thread(target=_run, daemon=True).start()

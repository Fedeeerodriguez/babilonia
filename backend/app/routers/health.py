"""Health checks para monitoreo (EasyPanel, uptime, alertas).

- GET /health        → liveness: el proceso está vivo (sin tocar dependencias).
- GET /health/ready  → readiness: chequea las 2 DBs + config de Notion/OpenAI.
                       Devuelve 503 si alguna DB no responde (para que el monitor alerte).
"""
import logging
import os
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.database import engine, docs_engine

router = APIRouter(tags=["health"])
log = logging.getLogger("tomi.health")


def _ping(eng) -> dict:
    t0 = time.time()
    try:
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        return {"ok": True, "ms": int((time.time() - t0) * 1000)}
    except Exception as e:  # noqa: BLE001
        log.warning("health ping falló: %s", e)
        return {"ok": False, "error": str(e)[:200]}


@router.get("/health")
def health():
    """Liveness simple — no toca dependencias externas."""
    return {"status": "ok", "brand": "Tomi · Babilonia", "version": "0.3.0"}


@router.get("/health/ready")
def health_ready():
    """Readiness — chequea dependencias. 503 si alguna DB está caída."""
    checks = {
        "main_db": _ping(engine),
        "docs_db": _ping(docs_engine),
        "notion_configured": bool(os.getenv("NOTION_TOKEN")),
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
    }
    healthy = checks["main_db"]["ok"] and checks["docs_db"]["ok"]
    status = "ok" if healthy else "degraded"
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": status, "checks": checks},
    )

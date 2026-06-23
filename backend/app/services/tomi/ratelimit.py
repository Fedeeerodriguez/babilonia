"""Rate limiting simple, en memoria y sin dependencias externas.

Ventana fija por minuto, por IP de cliente, aplicada solo a los endpoints
pesados de Tomi (los que llaman LLM / pgvector / Notion). Evita que un cliente
dispare costos o tire el servicio a pedos. Para single-backend alcanza; si en
el futuro hay varios workers/replicas, migrar a Redis.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Dict, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

log = logging.getLogger("tomi.ratelimit")

# Prefijos de ruta a limitar (los que cuestan plata / recursos).
LIMITED_PREFIXES = (
    "/api/tomi/agente",
    "/api/tomi/memorias-agente",
    "/api/tomi/memorias",
    "/api/tomi/bases-datos",
)

# Requests permitidos por ventana, por IP.
MAX_PER_WINDOW = int(os.getenv("TOMI_RATE_LIMIT", "30"))
WINDOW_SECONDS = int(os.getenv("TOMI_RATE_WINDOW", "60"))


def _client_ip(request: Request) -> str:
    # Respeta el proxy (Cloudflare/EasyPanel) si manda X-Forwarded-For.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._lock = threading.Lock()
        # key -> (window_start, count)
        self._hits: Dict[str, Tuple[float, int]] = {}

    def _allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            window_start, count = self._hits.get(key, (now, 0))
            if now - window_start >= WINDOW_SECONDS:
                # nueva ventana
                self._hits[key] = (now, 1)
                # prune oportunista de entradas viejas para no crecer infinito
                if len(self._hits) > 5000:
                    self._hits = {
                        k: v for k, v in self._hits.items()
                        if now - v[0] < WINDOW_SECONDS
                    }
                return True
            if count >= MAX_PER_WINDOW:
                return False
            self._hits[key] = (window_start, count + 1)
            return True

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method == "POST" and path.startswith(LIMITED_PREFIXES):
            key = f"{_client_ip(request)}:{path}"
            if not self._allow(key):
                log.warning("rate limit excedido: %s", key)
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Demasiadas consultas. Esperá un momento y reintentá.",
                        "retry_after_seconds": WINDOW_SECONDS,
                    },
                    headers={"Retry-After": str(WINDOW_SECONDS)},
                )
        return await call_next(request)

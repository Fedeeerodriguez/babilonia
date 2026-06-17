"""Circuit breaker simple y thread-safe.

Cuando una dependencia externa (Notion, OpenAI) falla N veces seguidas, el breaker
"abre" y durante un cooldown corta las llamadas al toque en vez de seguir golpeando
algo que está caído (evita amontonar workers esperando timeouts). Pasado el cooldown
deja pasar UNA llamada de prueba (half-open); si va bien, cierra; si falla, reabre.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("tomi.circuit")


class CircuitOpenError(RuntimeError):
    """Se levanta cuando el breaker está abierto (dependencia caída)."""


class CircuitBreaker:
    def __init__(self, name: str, fail_threshold: int = 5, cooldown: float = 30.0):
        self.name = name
        self.fail_threshold = fail_threshold
        self.cooldown = cooldown
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at = 0.0
        self._state = "closed"  # closed | open | half_open

    def allow(self) -> bool:
        """¿Se permite la próxima llamada? Maneja la transición open → half_open."""
        with self._lock:
            if self._state == "open":
                if time.time() - self._opened_at >= self.cooldown:
                    self._state = "half_open"
                    log.info("circuit %s → half_open (prueba)", self.name)
                    return True
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            if self._state != "closed":
                log.info("circuit %s → closed (recuperado)", self.name)
            self._failures = 0
            self._state = "closed"

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state == "half_open" or self._failures >= self.fail_threshold:
                self._state = "open"
                self._opened_at = time.time()
                log.warning(
                    "circuit %s → open tras %d fallos (cooldown %.0fs)",
                    self.name, self._failures, self.cooldown,
                )

    def call(self, fn, *args, **kwargs):
        """Ejecuta fn bajo el breaker. Levanta CircuitOpenError si está abierto."""
        if not self.allow():
            raise CircuitOpenError(f"{self.name} no disponible (circuit abierto)")
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        else:
            self.record_success()
            return result

    def state(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "state": self._state,
                "failures": self._failures,
                "cooldown": self.cooldown,
            }

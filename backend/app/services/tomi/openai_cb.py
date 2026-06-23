"""Circuit breaker compartido para las llamadas a OpenAI.

Mismo patrón que `notion_breaker`: si OpenAI falla N veces seguidas, el breaker
abre y corta rápido en vez de amontonar workers esperando timeouts. Pasado el
cooldown deja pasar una llamada de prueba.

Lo importan tanto `agente.py` como `agente_memorias.py` para compartir estado.
"""
from __future__ import annotations

import os

from app.services.tomi.circuit import CircuitBreaker, CircuitOpenError  # re-export

openai_breaker = CircuitBreaker(
    "openai",
    fail_threshold=int(os.getenv("OPENAI_CB_THRESHOLD", "5")),
    cooldown=float(os.getenv("OPENAI_CB_COOLDOWN", "30")),
)

# Mensaje de degradación elegante para mostrar al usuario final cuando el LLM
# no está disponible (no exponemos el error técnico).
LLM_FALLBACK_MSG = (
    "Estoy con una demora técnica para procesar esta consulta. "
    "Probá de nuevo en un ratito; si es urgente, te paso con un humano."
)

__all__ = ["openai_breaker", "CircuitOpenError", "LLM_FALLBACK_MSG"]

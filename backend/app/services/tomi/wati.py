"""Cliente mínimo de WATI (WhatsApp) para mensajes que inicia Tomi.

WhatsApp solo permite que la empresa inicie una conversación con una PLANTILLA aprobada
(los mensajes libres valen únicamente dentro de las 24 h desde el último mensaje del
usuario). Por eso los avisos proactivos usan `sendTemplateMessage`.

Variables de entorno (las mismas que usa n8n):
  - WATI_SERVER : URL base del tenant, p. ej. https://live-mt-server.wati.io/465046
  - WATI_TOKEN  : token de la API (con o sin el prefijo "Bearer ")
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger("tomi.wati")


def numero_whatsapp(tel: Optional[str]) -> Optional[str]:
    """Normaliza un teléfono al formato que espera WATI (solo dígitos, con código de país).

    Los números de 10 dígitos se asumen de México y se les antepone 52.
    Devuelve None si no hay un número utilizable.
    """
    d = re.sub(r"\D", "", str(tel or ""))
    if len(d) == 10:
        d = "52" + d
    return d if len(d) >= 11 else None


def _limpiar(valor: Any) -> str:
    # WhatsApp rechaza parámetros de plantilla con saltos de línea, tabs o 4+ espacios.
    s = re.sub(r"[\r\n\t]+", " · ", str(valor if valor is not None else "")).strip()
    s = re.sub(r" {4,}", "   ", s)
    return s or "—"


def enviar_plantilla(numero: str, plantilla: str, parametros: Dict[str, Any],
                     broadcast: str = "tomi_avisos") -> Dict[str, Any]:
    """Envía una plantilla de WATI. Devuelve {ok, status, detalle}. Nunca levanta."""
    server = os.getenv("WATI_SERVER", "").rstrip("/")
    token = os.getenv("WATI_TOKEN", "").strip()
    if not server or not token:
        return {"ok": False, "status": None, "detalle": "WATI_SERVER / WATI_TOKEN no configurados"}
    auth = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    params: List[Dict[str, str]] = [{"name": k, "value": _limpiar(v)} for k, v in parametros.items()]
    try:
        r = httpx.post(
            f"{server}/api/v1/sendTemplateMessage",
            params={"whatsappNumber": numero},
            headers={"Authorization": auth},
            json={"template_name": plantilla, "broadcast_name": broadcast, "parameters": params},
            timeout=20,
        )
        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text[:300]}
        ok = r.status_code < 300 and data.get("result") is not False
        if not ok:
            log.warning("WATI plantilla %s a %s falló (%s): %s", plantilla, numero, r.status_code, data)
        return {"ok": ok, "status": r.status_code, "detalle": data}
    except Exception as e:  # noqa: BLE001
        log.error("WATI plantilla %s a %s error: %s", plantilla, numero, e)
        return {"ok": False, "status": None, "detalle": str(e)}

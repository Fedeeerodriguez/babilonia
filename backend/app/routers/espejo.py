"""Espejo de Notion: webhook de Notion y estado del sincronizador.

  POST /api/notion/webhook       Notion avisa que una página cambió → se encola y el worker la vuelve
                                 a leer (el aviso nunca se toma como dato). Firma X-Notion-Signature.
  GET  /api/tomi/espejo/estado   último sync por base, atraso y pedidos a Notion (X-Tomi-Key)
  GET  /api/tomi/espejo/token-webhook   el token de verificación que mandó Notion (X-Tomi-Key),
                                 para pegarlo en Notion al crear la suscripción.

La primera vez Notion manda {"verification_token": "..."} sin firma: se guarda en
notion_espejo.ajustes y desde ahí firma todos los avisos. Ver docs/ESPEJO_NOTION.md.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request

from app.routers.tomi import _auth

log = logging.getLogger(__name__)
router = APIRouter(tags=["espejo"])

_EVENTOS_PAGINA = {"page.created", "page.properties_updated", "page.content_updated", "page.deleted",
                   "page.undeleted", "page.moved", "page.locked", "page.unlocked"}
_repo = None


def _get_repo():
    global _repo
    if _repo is None:
        from app.services.espejo.repo import RepoEspejo
        _repo = RepoEspejo()
    return _repo


def firma_valida(token: str, cuerpo: bytes, firma: Optional[str]) -> bool:
    if not (token and firma):
        return False
    esperada = "sha256=" + hmac.new(token.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, firma)


@router.post("/api/notion/webhook")
async def webhook_notion(request: Request, x_notion_signature: Optional[str] = Header(default=None)):
    cuerpo = await request.body()
    try:
        datos = json.loads(cuerpo or b"{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="json inválido")
    repo = _get_repo()
    if "verification_token" in datos and len(datos) == 1:
        repo.guardar_ajuste("notion_webhook_token", str(datos["verification_token"]))
        log.info("espejo: llegó el token de verificación del webhook de Notion (guardado)")
        return {"ok": True}
    token = os.getenv("NOTION_WEBHOOK_TOKEN") or repo.leer_ajuste("notion_webhook_token") or ""
    if not firma_valida(token, cuerpo, x_notion_signature):
        raise HTTPException(status_code=401, detail="firma inválida")
    tipo, entidad = datos.get("type"), datos.get("entity") or {}
    if tipo in _EVENTOS_PAGINA and entidad.get("type") == "page" and entidad.get("id"):
        repo.encolar_pendiente(entidad["id"], tipo)
    return {"ok": True}


@router.get("/api/tomi/espejo/estado")
def estado_espejo(x_tomi_key: Optional[str] = Header(default=None)):
    _auth(x_tomi_key)
    repo = _get_repo()
    ahora = datetime.now(timezone.utc)
    bases = []
    for b in repo.listar_bases():
        atraso = (ahora - b["ultimo_sync"]).total_seconds() if b.get("ultimo_sync") else None
        bases.append({**b, "atraso_seg": round(atraso) if atraso is not None else None,
                      "vieja": atraso is None or atraso > int(os.getenv("ESPEJO_VIEJA_SEG", "600"))})
    return {"bases": bases, "viejas": [b["slug"] for b in bases if b["vieja"]],
            "pedidos_notion_ultima_hora": repo.pedidos_ultima_hora(), "paginas": repo.contar_paginas()}


@router.get("/api/tomi/espejo/token-webhook")
def token_webhook(x_tomi_key: Optional[str] = Header(default=None)):
    _auth(x_tomi_key)
    return {"token": _get_repo().leer_ajuste("notion_webhook_token")}

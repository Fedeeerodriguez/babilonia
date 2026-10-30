"""QA OFFLINE — webhook de Notion del espejo: verificación, firma y encolado. Sin red ni base."""
from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import espejo


class RepoFalso:
    def __init__(self):
        self.ajustes, self.pendientes = {}, {}

    def guardar_ajuste(self, k, v):
        self.ajustes[k] = v

    def leer_ajuste(self, k):
        return self.ajustes.get(k)

    def encolar_pendiente(self, pid, evento):
        self.pendientes[pid] = evento


def cliente(monkeypatch):
    repo = RepoFalso()
    monkeypatch.setattr(espejo, "_repo", repo)
    monkeypatch.delenv("NOTION_WEBHOOK_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(espejo.router)
    return TestClient(app), repo


def firmar(token, cuerpo: bytes):
    return "sha256=" + hmac.new(token.encode(), cuerpo, hashlib.sha256).hexdigest()


def test_verificacion_y_aviso_firmado_se_encola(monkeypatch):
    cli, repo = cliente(monkeypatch)
    assert cli.post("/api/notion/webhook", json={"verification_token": "secret_abc"}).status_code == 200
    assert repo.ajustes["notion_webhook_token"] == "secret_abc"
    cuerpo = json.dumps({"type": "page.properties_updated", "entity": {"id": "p1", "type": "page"}}).encode()
    r = cli.post("/api/notion/webhook", content=cuerpo, headers={"X-Notion-Signature": firmar("secret_abc", cuerpo),
                                                                 "Content-Type": "application/json"})
    assert r.status_code == 200 and repo.pendientes == {"p1": "page.properties_updated"}


def test_firma_mala_o_ausente_se_rechaza(monkeypatch):
    cli, repo = cliente(monkeypatch)
    repo.ajustes["notion_webhook_token"] = "secret_abc"
    cuerpo = json.dumps({"type": "page.created", "entity": {"id": "p1", "type": "page"}}).encode()
    assert cli.post("/api/notion/webhook", content=cuerpo).status_code == 401
    assert cli.post("/api/notion/webhook", content=cuerpo,
                    headers={"X-Notion-Signature": firmar("otro", cuerpo)}).status_code == 401
    assert repo.pendientes == {}


def test_eventos_que_no_son_de_pagina_no_se_encolan(monkeypatch):
    cli, repo = cliente(monkeypatch)
    repo.ajustes["notion_webhook_token"] = "t"
    cuerpo = json.dumps({"type": "comment.created", "entity": {"id": "c1", "type": "comment"}}).encode()
    assert cli.post("/api/notion/webhook", content=cuerpo,
                    headers={"X-Notion-Signature": firmar("t", cuerpo)}).status_code == 200
    assert repo.pendientes == {}

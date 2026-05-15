"""Patch del workflow n8n `Enviar a WATI (snippet)` (id 6SPTSxDdObcgjKHP).

Reemplaza los 8 Notion tools del sub-agente `bases_datos` por HTTP Request tools
que apuntan a /api/tomi/* del backend Babilonia (FastAPI).

Uso:
    set N8N_KEY=...
    set TOMI_API_BASE=https://api.babilonia.ai
    set TOMI_INTERNAL_KEY=...
    python tools/patch_n8n_bases_datos.py
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

N8N_KEY = os.environ["N8N_KEY"]
WF_ID = os.environ.get("N8N_WF_ID", "6SPTSxDdObcgjKHP")
URL = f"https://n8n.babilonia.ai/api/v1/workflows/{WF_ID}"

TOMI_API_BASE = os.environ.get("TOMI_API_BASE", "https://api.babilonia.ai")
TOMI_KEY = os.environ.get("TOMI_INTERNAL_KEY", "")

# Nombres de los nuevos HTTP tools (idempotente: se borran y recrean)
HTTP_TOOLS = [
    {
        "name": "asesor_por_email",
        "endpoint": "/api/tomi/asesor",
        "description": "Busca un asesor en Notion por email. Body: {email}",
        "body": {"email": "={{ $fromAI('email','Email del asesor','string') }}"},
    },
    {
        "name": "estudiante_por_email",
        "endpoint": "/api/tomi/estudiante",
        "description": "Busca un estudiante por email. Body: {email}",
        "body": {"email": "={{ $fromAI('email','Email del estudiante','string') }}"},
    },
    {
        "name": "cliente_por_email",
        "endpoint": "/api/tomi/cliente",
        "description": "Busca un cliente final por email. Body: {email}",
        "body": {"email": "={{ $fromAI('email','Email del cliente','string') }}"},
    },
    {
        "name": "emisiones",
        "endpoint": "/api/tomi/emisiones",
        "description": "Busca emisiones por nombre de cliente y/o número de póliza. Body: {cliente?, poliza?}",
        "body": {
            "cliente": "={{ $fromAI('cliente','Nombre del cliente (opcional)','string') }}",
            "poliza": "={{ $fromAI('poliza','Número de póliza (opcional)','string') }}",
        },
    },
    {
        "name": "cobranzas",
        "endpoint": "/api/tomi/cobranzas",
        "description": "Busca cobranzas por número de póliza. Body: {poliza}",
        "body": {"poliza": "={{ $fromAI('poliza','Número de póliza','string') }}"},
    },
    {
        "name": "tickets_allianz",
        "endpoint": "/api/tomi/tickets-allianz",
        "description": "Lista tickets Allianz filtrando por nombre del trámite. Body: {tramite?}",
        "body": {"tramite": "={{ $fromAI('tramite','Nombre del trámite (opcional)','string') }}"},
    },
    {
        "name": "tickets_babilonia",
        "endpoint": "/api/tomi/tickets-babilonia",
        "description": "Lista últimos tickets internos Babilonia. Body: {limit?}",
        "body": {"limit": "={{ $fromAI('limit','Cantidad máxima (default 10)','number') }}"},
    },
    {
        "name": "calendly",
        "endpoint": "/api/tomi/calendly",
        "description": "Busca eventos Calendly por nombre del cliente. Body: {cliente?, limit?}",
        "body": {
            "cliente": "={{ $fromAI('cliente','Nombre del cliente','string') }}",
            "limit": "={{ $fromAI('limit','Cantidad (default 10)','number') }}",
        },
    },
    {
        "name": "memorias_supabase",
        "endpoint": "/api/tomi/memorias",
        "description": "Búsqueda semántica en memorias (vector store). Body: {query, categoria?, wa_id?, k?}",
        "body": {
            "query": "={{ $fromAI('query','Texto a buscar en memorias','string') }}",
            "categoria": "={{ $fromAI('categoria','Categoría (opcional)','string') }}",
            "wa_id": "={{ $fromAI('wa_id','wa_id del cliente (opcional)','string') }}",
            "k": 4,
        },
    },
]


def http_tool_node(name: str, endpoint: str, description: str, body: dict, x: int, y: int) -> dict:
    body_params = []
    for k, v in body.items():
        body_params.append({"name": k, "value": v})
    return {
        "parameters": {
            "toolDescription": description,
            "method": "POST",
            "url": f"{TOMI_API_BASE}{endpoint}",
            "sendHeaders": True,
            "headerParameters": {"parameters": [
                {"name": "X-Tomi-Key", "value": TOMI_KEY},
                {"name": "Content-Type", "value": "application/json"},
            ]},
            "sendBody": True,
            "specifyBody": "keypair",
            "bodyParameters": {"parameters": body_params},
            "options": {},
        },
        "type": "@n8n/n8n-nodes-langchain.toolHttpRequest",
        "typeVersion": 1.1,
        "position": [x, y],
        "id": f"tomi-http-{name}",
        "name": f"tomi_{name}",
    }


def main():
    req = urllib.request.Request(URL, headers={"X-N8N-API-KEY": N8N_KEY})
    wf = json.loads(urllib.request.urlopen(req).read().decode("utf-8"))

    # Localizar sub-workflow bases_datos: nodo AI Agent llamado "bases_datos" o similar
    base_x, base_y = 0, 1200
    bd_node = next((n for n in wf["nodes"] if "base" in n["name"].lower() and "dato" in n["name"].lower()), None)
    if bd_node:
        base_x, base_y = bd_node["position"][0], bd_node["position"][1] + 200

    # Quitar tools http previos
    keep = []
    for n in wf["nodes"]:
        if n["name"].startswith("tomi_"):
            continue
        keep.append(n)
    wf["nodes"] = keep

    # Quitar conexiones previas de los tomi_*
    for nm in list(wf["connections"].keys()):
        if nm.startswith("tomi_"):
            wf["connections"].pop(nm, None)

    # Crear los HTTP tools y conectarlos al sub-agente bases_datos via ai_tool
    new_nodes = []
    for i, t in enumerate(HTTP_TOOLS):
        node = http_tool_node(t["name"], t["endpoint"], t["description"], t["body"],
                              x=base_x + (i % 5) * 220, y=base_y + (i // 5) * 200)
        new_nodes.append(node)
        # ai_tool connection from tool -> bases_datos
        if bd_node:
            wf["connections"].setdefault(node["name"], {}).setdefault("ai_tool", [[{
                "node": bd_node["name"], "type": "ai_tool", "index": 0
            }]])
    wf["nodes"].extend(new_nodes)

    allowed = {k: v for k, v in (wf.get("settings") or {}).items()
               if k in ("saveExecutionProgress", "saveManualExecutions", "saveDataErrorExecution",
                        "saveDataSuccessExecution", "executionTimeout", "timezone", "executionOrder")}
    upd = {
        "name": wf["name"],
        "nodes": wf["nodes"],
        "connections": wf["connections"],
        "settings": allowed or {"executionOrder": "v1"},
    }

    req = urllib.request.Request(
        URL, method="PUT",
        headers={"X-N8N-API-KEY": N8N_KEY, "Content-Type": "application/json"},
        data=json.dumps(upd).encode("utf-8"),
    )
    try:
        resp = urllib.request.urlopen(req)
        print(f"PUT {resp.status} — {len(new_nodes)} HTTP tools instalados.")
    except urllib.error.HTTPError as e:
        print(f"PUT error: {e.code} {e.read().decode()[:400]}")


if __name__ == "__main__":
    main()

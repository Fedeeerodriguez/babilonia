"""Reemplaza Postgres "¿Humano en 23h?" + IF + Code "Filtro 23h" por un solo
HTTP Request a /api/tomi/humano-reciente + un IF que cortocircuita si bloquear==true.

Uso:
    set N8N_KEY=...
    set TOMI_API_BASE=https://api.babilonia.ai
    set TOMI_INTERNAL_KEY=...
    python tools/patch_n8n_filtro_23h.py
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


def build_http_node(wh_pos):
    return {
        "parameters": {
            "method": "POST",
            "url": f"{TOMI_API_BASE}/api/tomi/humano-reciente",
            "sendHeaders": True,
            "headerParameters": {"parameters": [
                {"name": "X-Tomi-Key", "value": TOMI_KEY},
                {"name": "Content-Type", "value": "application/json"},
            ]},
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={ \"wa_id\": \"{{ $json.body.waId }}\", \"hours\": 23 }",
            "options": {},
        },
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [wh_pos[0] + 220, wh_pos[1]],
        "id": "tomi-filtro-23h-http",
        "name": "tomi_filtro_23h",
    }


def build_if_node(http_pos):
    return {
        "parameters": {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict"},
                "conditions": [{
                    "id": "bloquear-true",
                    "leftValue": "={{ $json.bloquear }}",
                    "rightValue": False,
                    "operator": {"type": "boolean", "operation": "equals"},
                }],
                "combinator": "and",
            },
            "options": {},
        },
        "type": "n8n-nodes-base.if",
        "typeVersion": 2.2,
        "position": [http_pos[0] + 220, http_pos[1]],
        "id": "tomi-filtro-23h-if",
        "name": "tomi_filtro_23h_if",
    }


def main():
    req = urllib.request.Request(URL, headers={"X-N8N-API-KEY": N8N_KEY})
    wf = json.loads(urllib.request.urlopen(req).read().decode("utf-8"))

    # Encontrar Webhook tomi-responder
    webhook = next(
        n for n in wf["nodes"]
        if n["type"] == "n8n-nodes-base.webhook"
        and n.get("parameters", {}).get("path") == "tomi-responder"
    )
    wh_pos = webhook["position"]

    # Downstream actual (lo que está después del Webhook)
    conn = wf["connections"].get(webhook["name"], {})
    downstream = (conn.get("main") or [[]])[0]

    # Quitar nodos viejos del filtro
    OLD_NAMES = {"¿Humano en 23h?", "Filtro 23h", "tomi_filtro_23h", "tomi_filtro_23h_if"}
    wf["nodes"] = [n for n in wf["nodes"] if n["name"] not in OLD_NAMES]
    for nm in list(wf["connections"].keys()):
        if nm in OLD_NAMES:
            wf["connections"].pop(nm, None)

    # Construir nuevos
    http_node = build_http_node(wh_pos)
    if_node = build_if_node(http_node["position"])
    wf["nodes"].append(http_node)
    wf["nodes"].append(if_node)

    # Reconectar: Webhook -> tomi_filtro_23h -> tomi_filtro_23h_if -> downstream original
    wf["connections"][webhook["name"]] = {"main": [[{"node": http_node["name"], "type": "main", "index": 0}]]}
    wf["connections"][http_node["name"]] = {"main": [[{"node": if_node["name"], "type": "main", "index": 0}]]}
    wf["connections"][if_node["name"]] = {"main": [downstream, []]}  # true -> sigue al flow, false -> nada (corta)

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
        print(f"PUT {resp.status} — filtro 23h reemplazado por HTTP Request al backend.")
    except urllib.error.HTTPError as e:
        print(f"PUT error: {e.code} {e.read().decode()[:400]}")


if __name__ == "__main__":
    main()

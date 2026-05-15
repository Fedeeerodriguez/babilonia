"""Agente LLM de Tomi · Babilonia.

Orquesta las funciones determinísticas de bases_datos via OpenAI tool calling.
El LLM decide QUÉ buscar y CÓMO formatear la respuesta. Toda la lógica de Notion
sigue siendo Python sin variabilidad.

Flujo:
  user mensaje
    → System prompt + historial
    → LLM elige tool (consultar_bases / expandir_pagina)
    → Python ejecuta y devuelve JSON
    → LLM lee resultado y o llama otra tool o responde
    → loop hasta max_iteraciones o respuesta final
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI

from app.services.tomi import bases_datos as bd
from app.services.tomi import notion_client as nc

log = logging.getLogger("tomi.agente")

CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini")

SYSTEM_PROMPT = """Sos Tomi, el asistente de Babilonia para asesores, clientes y estudiantes de Allianz.

Hablás en español rioplatense, sos breve y directo. Sin emojis salvo confirmación.

TENÉS UNA TOOL: `consultar_bases`. Es la única forma de acceder a datos Notion.
- Pasale el mensaje completo del usuario en `mensaje` y opcionalmente listas explícitas (emails, polizas, clientes, asesores) si las extraés.
- Python tiene regex y entiende: emails, números de póliza (Plus3-403328, PLU3-408444), nombres precedidos por "cliente"/"asesor"/"sr."/"sra.".
- Si necesitás más detalle de una page específica, podés llamar `expandir_pagina(page_id)`.

ESTRUCTURA DEL RESULTADO de `consultar_bases`:
- `usuarios[]`: matches por email — cada uno tiene `tipo` (asesor|estudiante|cliente|prospecto) y `expandido`:
  - Si tipo=asesor: `expandido.clientes[]` con TODOS sus clientes, `expandido.eventos_calendly[]`, `expandido.total_clientes`
  - Si tipo=cliente: `expandido.asesor`, `expandido.emisiones[]`, `expandido.tickets_allianz[]`, `expandido.eventos_calendly[]`
- `emisiones[]`: pólizas emitidas (con Asesor resuelto al nombre)
- `cobranzas[]`: cobranzas por póliza
- `tickets_allianz[]`, `calendly[]`
- `asesores_por_nombre[]`, `clientes_por_nombre[]`: matches por nombre
- `no_encontrados`: emails/pólizas sin match

REGLAS:
1. Máximo 3 tool calls por respuesta. Si con la primera ya tenés todo, RESPONDÉ directo.
2. Si el usuario pregunta por "todos los X de Y", buscá Y primero y leé `expandido.X` (NO hagas tools extra).
3. Si encontrás más de 20 resultados, hacé resumen con conteos.
4. Si no hay datos, decilo: "No encontré datos sobre X".
5. Nunca inventes datos. Solo respondé con lo que devolvieron las tools.

EJEMPLO de buen comportamiento:
Usuario: "todos los clientes de la asesora Jimena con correo jimenabarrerah@gmail.com"
→ Tool call: consultar_bases(mensaje="...", emails=["jimenabarrerah@gmail.com"])
→ Tool response: usuarios[0]={tipo:asesor, expandido:{clientes:[...47 items], total_clientes:47}}
→ Tu respuesta: "Jimena Barrera tiene 47 clientes. Los principales: Karla Mauricio, [...], [...]. ¿Querés que te liste todos o filtrar por algún criterio?"
"""


def _tools_schema() -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "consultar_bases",
                "description": (
                    "Consulta las bases de datos Notion (clientes, asesores, emisiones, cobranzas, "
                    "tickets allianz, calendly). Pasá el mensaje completo del usuario y opcionalmente "
                    "listas explícitas de entidades si las podés extraer."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mensaje": {
                            "type": "string",
                            "description": "Texto libre del usuario. Python aplica regex para extraer emails, pólizas y nombres.",
                        },
                        "emails": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Emails a buscar (suma a los que regex extraiga del mensaje).",
                        },
                        "polizas": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Números de póliza tipo Plus3-403328, PLU3-408444.",
                        },
                        "clientes": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Nombres de clientes (no emails) — busca en Clientes General + Emisiones.",
                        },
                        "asesores": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Nombres de asesores — busca en Asesores y filtra Calendly.",
                        },
                        "incluir": {
                            "type": "array",
                            "items": {"type": "string", "enum": [
                                "usuarios", "emisiones", "cobranzas", "tickets_allianz",
                                "calendly", "clientes_por_nombre", "asesores_por_nombre"
                            ]},
                            "description": "Subset opcional. Si omitís, Python infiere del mensaje.",
                        },
                    },
                    "required": ["mensaje"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "expandir_pagina",
                "description": (
                    "Obtiene todos los detalles de una page Notion por ID. Útil cuando una relación "
                    "viene como {id, name} y querés ver más campos (correo, teléfono, etc.)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "page_id": {"type": "string", "description": "UUID de la page Notion."},
                    },
                    "required": ["page_id"],
                },
            },
        },
    ]


def _dispatch(name: str, args: Dict[str, Any]) -> Any:
    """Ejecuta una tool por nombre y devuelve resultado serializable."""
    if name == "consultar_bases":
        return bd.consultar(
            mensaje=args.get("mensaje", ""),
            emails=args.get("emails"),
            polizas=args.get("polizas"),
            clientes=args.get("clientes"),
            asesores=args.get("asesores"),
            incluir=args.get("incluir"),
        )
    if name == "expandir_pagina":
        return nc._resolve_page_full(args.get("page_id", ""))
    return {"error": f"tool desconocida: {name}"}


def _truncar_tool_result(data: Any, max_chars: int = 8000) -> str:
    """Serializa y trunca el resultado de una tool para no inflar el contexto."""
    s = json.dumps(data, ensure_ascii=False, default=str)
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + f"\n...[truncado, total {len(s)} chars]"


def responder(
    mensaje: str,
    historial: Optional[List[Dict[str, str]]] = None,
    wa_id: Optional[str] = None,
    max_iter: int = 5,
) -> Dict[str, Any]:
    """Loop de tool-calling. Devuelve {respuesta, tool_calls, iteraciones, datos, stats}."""
    t0 = time.time()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"error": "OPENAI_API_KEY no configurada"}

    client = OpenAI(api_key=api_key)
    tools = _tools_schema()

    messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if historial:
        # historial esperado: [{role: user|assistant, content: ...}]
        for h in historial[-10:]:  # últimos 10 turnos
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": mensaje})

    tool_calls_log: List[Dict[str, Any]] = []
    datos_acumulados: List[Any] = []

    for i in range(max_iter):
        try:
            resp = client.chat.completions.create(
                model=CHAT_MODEL,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.2,
            )
        except Exception as e:
            log.error("OpenAI falló: %s", e)
            return {"error": f"LLM falló: {e}", "iteraciones": i}

        msg = resp.choices[0].message
        # Agregar el mensaje del asistente (con tool_calls si las hay)
        asst_msg: Dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            asst_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
        messages.append(asst_msg)

        if not msg.tool_calls:
            # Respuesta final
            return {
                "respuesta": msg.content or "",
                "iteraciones": i + 1,
                "tool_calls": tool_calls_log,
                "datos": datos_acumulados,
                "stats": {
                    "tiempo_ms": int((time.time() - t0) * 1000),
                    "modelo": CHAT_MODEL,
                },
            }

        # Ejecutar cada tool call
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            log.info("tool: %s args=%s", tc.function.name, args)
            try:
                result = _dispatch(tc.function.name, args)
            except Exception as e:
                log.error("dispatch falló: %s", e)
                result = {"error": str(e)}
            datos_acumulados.append({"tool": tc.function.name, "args": args, "result": result})
            tool_calls_log.append({
                "tool": tc.function.name,
                "args": args,
                "result_chars": len(json.dumps(result, default=str)),
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": _truncar_tool_result(result),
            })

    return {
        "respuesta": "[max iteraciones alcanzadas sin respuesta final]",
        "iteraciones": max_iter,
        "tool_calls": tool_calls_log,
        "datos": datos_acumulados,
        "error": "max_iter",
    }

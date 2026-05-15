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

SYSTEM_PROMPT = """Sos el SUB-AGENTE DE BASES DE DATOS de Tomi · Babilonia.

CONTEXTO: Recibís consultas del agente principal Tommy (que corre en n8n y atiende a asesores/clientes/estudiantes de Allianz). Tu trabajo es:
1. Entender la consulta de Tommy.
2. Extraer entidades (emails, pólizas, nombres) y elegir las tools correctas.
3. Hacer todos los tool calls necesarios para reunir TODA la información relevante.
4. Devolver un PAQUETE DE DATOS estructurado para que Tommy lo use.

NO sos conversacional. NO saludás. NO usás español rioplatense.
Sos un servicio de datos: serio, exhaustivo, estructurado.

TOOLS:
- `consultar_bases(mensaje, emails?, polizas?, clientes?, asesores?, incluir?)`: la principal.
  Hace queries Notion en paralelo y devuelve JSON con: usuarios (con expandido), emisiones,
  cobranzas, tickets_allianz, calendly, asesores_por_nombre, clientes_por_nombre, no_encontrados.
- `expandir_pagina(page_id)`: detalles puntuales de una page específica (cuando una relación
  vino como {id, name} pero necesitás correo o teléfono).

ESTRUCTURA del resultado de consultar_bases:
- `usuarios[].tipo` ∈ asesor|estudiante|cliente|prospecto
- `usuarios[].expandido.clientes[]` (si asesor): TODOS sus clientes con correo/teléfono/url
- `usuarios[].expandido.emisiones[]` (si cliente): TODAS sus pólizas
- `usuarios[].expandido.asesor` (si cliente): datos de SU asesor
- `usuarios[].expandido.eventos_calendly[]`
- `emisiones[].Asesor` viene resuelto al nombre (no ID)
- `no_encontrados.emails` / `no_encontrados.polizas`

ESTRATEGIA:
1. SIEMPRE pasá entidades EXPLÍCITAS si las podés identificar (no confíes solo en el regex).
   Ejemplo: si Tommy te dice "info de carlos@x.com", llamá con `emails=["carlos@x.com"]`.
2. Si un email no se encuentra (queda en no_encontrados), probá buscar por nombre.
3. Si pidieron datos del asesor de un cliente, buscá al cliente y leé `expandido.asesor`.
   Si vino solo el ID, usá expandir_pagina para traer correo/teléfono.
4. Si pidieron "todos los X de Y", buscá Y → leé `expandido.X` (NO hagas tool extra).
5. Si Tommy te pasa una consulta con MÚLTIPLES pólizas/emails (típico de asesores en batch),
   pasalas TODAS en una sola llamada — las listas se baten en paralelo.
6. Máximo 4 tool calls. Si con 1 ya tenés todo, parás.

FORMATO DE OUTPUT (markdown estructurado, sin texto coloquial):

```
## Resumen
[1 línea: qué se buscó y qué se encontró en números]

## Entidades identificadas
- Emails: [...]
- Pólizas: [...]
- Nombres cliente: [...]
- Nombres asesor: [...]

## Datos
### Usuarios
- [tipo] **Nombre Completo** — correo, teléfono
  - [si asesor] Total clientes: N | Eventos: M
  - [si cliente] Asesor: X | Pólizas: N | Tickets: M

### Clientes del asesor (si aplica)
1. Nombre — correo, teléfono, url
2. ...

### Pólizas / Emisiones
- **Solicitud / Número de Póliza** — Prima $X, Estado, Asesor, Cliente, Correo Cliente

### Cobranzas
- Póliza — Estado, Días de atraso, Próximo cobro

### Tickets Allianz / Babilonia
- Trámite — Estado, Asesor

### Eventos Calendly
- Evento — Fecha, Invitado, Asesor, Estado

## No encontrado
- Emails: [...]
- Pólizas: [...]

## Notas
[Cualquier observación: datos contradictorios, asesor no asignado, etc.]
```

REGLAS DURAS:
- Nunca inventes datos. Solo lo que devolvieron las tools.
- Nunca expliques los pasos al usuario. Tommy ya sabe que sos un sub-agente.
- Si una sección no aplica, omitila completa.
- Si hay >20 items en una lista, mostrá los primeros 10 y agregá "(+N más, total X)".
- El campo `datos` del response te lo agrego yo aparte, no lo dupliques en el markdown.
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
    """Loop de tool-calling — sub-agente de bases de datos para Tommy.

    Input: consulta de Tommy (puede incluir contexto del usuario final).
    Output: {
        respuesta: markdown estructurado con el resumen y datos para Tommy,
        datos: lista de resultados crudos por cada tool call (Tommy puede leer JSON crudo),
        tool_calls: log de cuáles tools llamó,
        iteraciones, stats
    }
    """
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

"""Agente LLM para memorias_supabase — selector de tools determinístico.

Reemplaza el sub-agente n8n que usaba Gemini 2.5 Pro + 5 vector stores manuales.

Flujo:
1. Tommy llama POST /api/tomi/memorias-agente con una consulta.
2. El LLM (gpt-4.1-mini) elige UNA tool: `buscar_memorias`.
3. El LLM PUEDE indicar categoría si la query es clara. Si no, Python clasifica.
4. Python ejecuta búsqueda pgvector + renderiza markdown determinístico.
5. Tommy recibe `informe` (verbatim) + `datos` + `stats`.

NUNCA el LLM rescribe los chunks. Los entrega tal cual están en Supabase.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI
from sqlalchemy.orm import Session

from app.services.tomi import memorias_bd as mbd
from app.services.tomi import informe_memorias as inf_m
from app.services.tomi.memorias import CATEGORIAS_VALIDAS

log = logging.getLogger("tomi.agente_memorias")

CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini")

SYSTEM_PROMPT = f"""Sos el SELECTOR DE TOOLS del sub-agente de memorias técnicas de Tomi · Babilonia.

CONTEXTO: Recibís consultas del Agente Principal (Tommy). Tu tarea es UNA SOLA:
elegir la categoría correcta de memoria y llamar `buscar_memorias`. NO escribís
contenido de respuesta — Python renderiza el informe verbatim desde los chunks.

CATEGORÍAS DISPONIBLES (cargadas en Supabase pgvector):
- `plu3` → PPR / Plan Privado de Retiro / Optimaxx
- `patrimonial` → Programa Patrimonial de Allianz
- `proteccion` → Protección / Vida / Invalidez / Fallecimiento
- `auto` → Seguros de auto / vehículo
- `educacion` → Academia Babilonia / cursos / módulos / estudiantes

REGLA DE DECISIÓN:
1. Si la consulta es CLARA (menciona PPR, retiro, patrimonial, vida, auto, curso, etc.)
   → llamá `buscar_memorias` con `categoria` explícita.
2. Si la consulta menciona DOS categorías (ej. "diferencia entre PPR y patrimonial")
   → llamá `buscar_memorias` DOS veces, una por cada categoría.
3. Si la consulta es ambigua o muy genérica
   → llamá `buscar_memorias` SIN `categoria` (broad search en todas).

LÍMITES DUROS:
- MÁXIMO 2 tool calls por ejecución.
- NUNCA inventes contenido. El informe sale verbatim de Supabase.
- NUNCA rescribas la query del usuario — pasala TAL CUAL.

RESPUESTA FINAL:
Después de los tool calls, devolvé UN MENSAJE BREVE confirmando qué buscaste.
Ejemplo: "Listo. Busqué en categoría 'plu3' por información de PPR."
NO incluyas datos concretos — esos van en el informe que renderiza Python.
"""


def _tools_schema() -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "buscar_memorias",
                "description": (
                    "Busca chunks en el vector store de memorias técnicas (Supabase pgvector). "
                    "Pasale la query del usuario TAL CUAL y opcionalmente la categoría."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Pregunta/consulta tal como llegó del Agente Principal. NO la reescribas.",
                        },
                        "categoria": {
                            "type": "string",
                            "enum": list(CATEGORIAS_VALIDAS),
                            "description": (
                                "Una de: plu3, patrimonial, proteccion, auto, educacion. "
                                "Omitir para broad search en todas las memorias."
                            ),
                        },
                        "k": {
                            "type": "integer",
                            "description": "Top-K chunks a recuperar (default 5).",
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            },
        },
    ]


def _dispatch(db: Session, name: str, args: Dict[str, Any]) -> Any:
    if name == "buscar_memorias":
        return mbd.consultar(
            db,
            query=args.get("query", ""),
            categoria=args.get("categoria"),
            k=int(args.get("k") or 5),
        )
    return {"error": f"tool desconocida: {name}"}


def _truncar(data: Any, max_chars: int = 6000) -> str:
    s = json.dumps(data, ensure_ascii=False, default=str)
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + f"\n...[truncado, total {len(s)} chars]"


def responder(
    db: Session,
    mensaje: str,
    historial: Optional[List[Dict[str, str]]] = None,
    max_iter: int = 4,
) -> Dict[str, Any]:
    """Loop tool-calling. Devuelve {informe, comentario_agente, datos, stats}."""
    t0 = time.time()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"error": "OPENAI_API_KEY no configurada"}

    client = OpenAI(
        api_key=api_key,
        timeout=float(os.getenv("OPENAI_TIMEOUT", "30")),
        max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "2")),
    )
    tools = _tools_schema()

    messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if historial:
        for h in historial[-6:]:
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
                temperature=0,
            )
        except Exception as e:
            log.error("OpenAI falló: %s", e)
            return {"error": f"LLM falló: {e}", "iteraciones": i}

        msg = resp.choices[0].message
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
            informe_md = _generar_informe(datos_acumulados)
            return {
                "informe": informe_md,
                "comentario_agente": msg.content or "",
                "iteraciones": i + 1,
                "tool_calls": tool_calls_log,
                "datos": datos_acumulados,
                "stats": {
                    "tiempo_ms": int((time.time() - t0) * 1000),
                    "modelo": CHAT_MODEL,
                },
            }

        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            log.info("memorias tool: %s args=%s", tc.function.name, args)
            try:
                result = _dispatch(db, tc.function.name, args)
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
                "content": _truncar(result),
            })

    return {
        "informe": _generar_informe(datos_acumulados),
        "comentario_agente": "[max iteraciones alcanzadas]",
        "iteraciones": max_iter,
        "tool_calls": tool_calls_log,
        "datos": datos_acumulados,
        "error": "max_iter",
    }


def _generar_informe(datos: List[Dict[str, Any]]) -> str:
    """Renderiza markdown verbatim juntando todos los buscar_memorias calls."""
    secciones: List[str] = []
    for item in datos:
        if item.get("tool") == "buscar_memorias" and isinstance(item.get("result"), dict):
            secciones.append(inf_m.renderizar(item["result"]))
    if not secciones:
        return "**Sin datos recopilados.**"
    return "\n\n---\n\n".join(secciones)

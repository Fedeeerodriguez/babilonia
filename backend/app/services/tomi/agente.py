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
from app.services.tomi import informe as inf
from app.services.tomi.openai_cb import openai_breaker, LLM_FALLBACK_MSG

log = logging.getLogger("tomi.agente")

CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini")

SYSTEM_PROMPT = """Sos el SELECTOR DE TOOLS del sub-agente de bases de datos de Tomi · Babilonia.

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

TU ÚNICO TRABAJO ES ELEGIR LAS TOOLS Y SUS ARGUMENTOS. El informe final lo
genera Python desde los datos crudos — vos NO escribís texto narrativo.

REGLA CRÍTICA — ELEGIR EL MODO CORRECTO:
La tool `consultar_bases` tiene un parámetro `modo` que controla cuánta data devuelve.
Elegí el más acotado posible — traer todo (modo="completo") es caro y ruidoso.

- `perfil` → Solo datos básicos del usuario (nombre, email, tel, role, stats).
   USAR para: "¿quién es X?", "info de contacto de Y", "datos del asesor Z".
   NO trae clientes, NO trae emisiones, NO trae eventos.

- `polizas` → Datos básicos + emisiones del cliente/asesor.
   USAR para: "pólizas de X", "qué seguros tiene Y", "emisiones del asesor Z".

- `clientes` → Datos básicos + lista de clientes del asesor (sin emisiones).
   USAR para: "clientes de X" (rápido sin detalle de pólizas).

- `cartera` → **MODO PREMIUM** para análisis de cartera de un asesor.
   Hace lo siguiente automáticamente:
   1. Trae TODAS las emisiones del asesor (PLU3 + VIPP + GMM + Auto + Patrimonial).
   2. Agrupa por correo del cliente — deduplica una misma persona que tiene varios productos.
   3. Para cada cliente, dedupe sus pólizas (si una póliza aparece 2 veces, prevalece la activa).
   4. Resuelve fondos de inversión (Portafolios) por cada póliza.
   USAR para: "cartera de X", "clientes y fondos del asesor", "qué productos tiene cada cliente de Y".
   REQUIERE: `email_asesor`. Sin email, no funciona — el modo necesita un correo concreto.

- `cobranzas` → Solo cobranzas filtradas por póliza.
   USAR para: "cuándo paga X", "saldo de PLU3-XXX", "próximo cobro",
   y también para el "número de cliente" (ver MAPEO DE TÉRMINOS abajo).

MAPEO DE TÉRMINOS — "número de cliente":
Cuando el usuario pida el "número de cliente", "número de socio", "código de cliente"
o "el número" de un cliente/póliza, se refiere SIEMPRE al campo "Número de Referencia"
de la base de Cobranza. Ese dato vive en `cobranzas`, así que para responderlo usá el
modo `cobranzas` (o `completo` si ya estás trayendo todo). El "Número de Referencia"
NO es la póliza ni la solicitud: es un identificador propio del cliente en Cobranza.
Si el cliente no tiene "Número de Referencia" cargado, decilo — no devuelvas otro número.

- `eventos` → Datos básicos + eventos Calendly.
   USAR para: "agenda de X", "próxima cita", "eventos del asesor Z".

DAF (cuenta de agente Allianz):
Si preguntan por el "DAF", "número de agente", "cédula", "estado del DAF",
"cuenta/credencial de agente" de un asesor, pasá el nombre del asesor en `asesores`
(o su email) — Python trae automáticamente la cuenta DAF (número de agente, cédula,
estado activo/inactivo, correo, meses con DAF). El DAF es la cuenta del AGENTE, no del cliente.

- `completo` → TODO. SOLO si el usuario pide explícitamente panorama completo.

FILTROS ADICIONALES:
- `email_asesor` y `email_cliente`: si SABÉS de antemano que un email pertenece a un
  asesor o a un cliente, pasalo en el campo específico — más rápido y preciso.
- `solo_activas`: true para filtrar solo emisiones con estado Activa.
- `limite`: cap superior por categoría (default 100, bajalo si solo querés top N).

Después de hacer los tool calls que necesites, devolvé un mensaje muy breve
explicando QUÉ buscaste (no listes los resultados — eso lo hace Python).
Ejemplo: "Listo. Busqué a Jimena por email y traje sus clientes, emisiones y eventos."

REGLAS DURAS:
- NUNCA escribas datos numéricos en tu respuesta. Si necesitás mencionar un número,
  el informe Python lo va a poner.
- NUNCA listes nombres, pólizas, fechas o cualquier dato concreto.
- Tu respuesta final es solo una confirmación de QUÉ se consultó.
- Si Tommy pide algo que no podés resolver con las tools, decilo explícito.
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
                            "description": "Consulta enriquecida con contexto. Python extrae emails/pólizas/nombres por regex pero conviene pasarlos explícitos abajo.",
                        },
                        "modo": {
                            "type": "string",
                            "enum": ["perfil", "polizas", "clientes", "cobranzas", "eventos", "completo", "cartera"],
                            "description": "QUÉ devolver. 'perfil'=solo datos básicos, 'polizas'=+emisiones, 'clientes'=+cartera, 'cobranzas'=solo cobranzas, 'eventos'=+calendly, 'completo'=todo (caro). USAR el más acotado posible.",
                        },
                        "email_asesor": {
                            "type": "string",
                            "description": "Email que SABÉS pertenece a un asesor. Acelera y evita auto-clasificar.",
                        },
                        "email_cliente": {
                            "type": "string",
                            "description": "Email que SABÉS pertenece a un cliente final.",
                        },
                        "emails": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Emails sin clasificar (Python clasifica). Solo si NO sabés si es asesor o cliente.",
                        },
                        "polizas": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Números de póliza tipo PLU3-XXX, VIPP-XXX.",
                        },
                        "clientes": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Nombres de clientes (no emails).",
                        },
                        "asesores": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Nombres de asesores.",
                        },
                        "solo_activas": {
                            "type": "boolean",
                            "description": "True para filtrar emisiones con Estado == Activa (descarta canceladas/pendientes).",
                        },
                        "limite": {
                            "type": "integer",
                            "description": "Cap superior por categoría (default 100). Bajá a 10-20 para top results.",
                        },
                        "filtro_estado": {
                            "type": "string",
                            "enum": ["activos", "en_proceso", "perdidos"],
                            "description": "(solo modo cartera) Filtra clientes por categoría: 'activos' = con póliza Activa, 'en_proceso' = con póliza pendiente/documentos faltantes, 'perdidos' = cancelados/pre-emisión. Si el asesor pregunta 'cuántos clientes tengo' suele referirse a 'activos'.",
                        },
                        "incluir": {
                            "type": "array",
                            "items": {"type": "string", "enum": [
                                "usuarios", "emisiones", "cobranzas", "tickets_allianz",
                                "calendly", "clientes_por_nombre", "asesores_por_nombre", "daf"
                            ]},
                            "description": "Override granular. Normalmente usar `modo` en su lugar.",
                        },
                    },
                    "required": ["mensaje", "modo"],
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
            modo=args.get("modo") or "completo",
            email_asesor=args.get("email_asesor"),
            email_cliente=args.get("email_cliente"),
            solo_activas=bool(args.get("solo_activas") or False),
            limite=int(args.get("limite") or 100),
            filtro_estado=args.get("filtro_estado"),
        )
    if name == "expandir_pagina":
        return nc._resolve_page_full(args.get("page_id", ""))
    return {"error": f"tool desconocida: {name}"}


def _generar_informe_completo(datos_acumulados: List[Dict[str, Any]]) -> str:
    """Renderiza markdown determinístico uniendo los resultados de TODAS las tools llamadas."""
    secciones: List[str] = []
    for item in datos_acumulados:
        tool = item.get("tool")
        result = item.get("result") or {}
        if tool == "consultar_bases" and isinstance(result, dict):
            secciones.append(inf.renderizar(result))
        elif tool == "expandir_pagina" and isinstance(result, dict):
            secciones.append("## Detalle de page Notion\n")
            for k, v in result.items():
                if k.startswith("_"):
                    continue
                secciones.append(f"- **{k}**: `{v}`")
            secciones.append("")
    if not secciones:
        return "**Sin datos recopilados.**"
    return "\n\n---\n\n".join(secciones)


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

    client = OpenAI(
        api_key=api_key,
        timeout=float(os.getenv("OPENAI_TIMEOUT", "30")),
        max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "2")),
    )
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
        if not openai_breaker.allow():
            log.warning("OpenAI circuit abierto — se corta la consulta")
            return {"error": "LLM no disponible (circuit abierto)", "respuesta": LLM_FALLBACK_MSG, "iteraciones": i}
        try:
            resp = client.chat.completions.create(
                model=CHAT_MODEL,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0,
            )
            openai_breaker.record_success()
        except Exception as e:
            openai_breaker.record_failure()
            log.error("OpenAI falló: %s", e)
            return {"error": f"LLM falló: {e}", "respuesta": LLM_FALLBACK_MSG, "iteraciones": i}

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
            # Generar informe DETERMINÍSTICO desde los datos crudos, ignorando msg.content
            informe_md = _generar_informe_completo(datos_acumulados)
            return {
                "informe": informe_md,           # 100% Python, 100% fiel a Notion
                "comentario_agente": msg.content or "",  # breve nota del LLM (NO contiene datos)
                "iteraciones": i + 1,
                "tool_calls": tool_calls_log,
                "datos": datos_acumulados,        # JSON crudo para que Tommy procese si quiere
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

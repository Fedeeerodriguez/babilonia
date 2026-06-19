"""Agente interno con OpenAI function calling.

Tools disponibles:
  - query_metrics(from?, to?, asesor?)
  - search_conversations(query?, wa_id?, limit?)
  - list_documents(source?)
  - upload_knowledge(title, source, text)
"""
import json
import os
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from openai import OpenAI
from app import models, schemas
from app.database import get_db
from app.security import get_current_user
from app.routers.metrics import summary as metrics_summary
from app.routers.conversations import list_conversations
from app.routers.documents import list_documents, upload_text

router = APIRouter(prefix="/api/agent", tags=["agent"])

CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini")

SYSTEM = """Sos Tomi-asistente, el agente interno de la plataforma Babilonia para el equipo de asesores Allianz.
Hablás en español rioplatense, sos breve y directo. Tenés acceso a tools para consultar métricas, conversaciones,
la base de conocimiento y el SANDBOX de entrenamiento de Tomi. Cuando el usuario pida cargar información a la base, usá upload_knowledge.

SANDBOX / CALIDAD DE TOMI:
Cuando el usuario pregunte por cuántos mensajes hubo, qué porcentaje se aprobó/rechazó, la tasa de
aprobación, o qué se puede mejorar de las respuestas de Tomi, usá `feedback_stats` (te da totales,
% aprobados = correctas, % rechazados = malas, mejorables, desglose por público y top de problemas).
Para dar IDEAS DE MEJORA concretas, llamá además a `feedback_examples` con rating="bad" y/o "mejorable"
para leer las preguntas, las respuestas que fallaron, las correcciones del admin y las etiquetas del
problema; a partir de ESOS datos reales proponé mejoras accionables (no genéricas). Ej: "el 40% de los
rechazos tienen tag 'dato_incorrecto' en consultas de cobranza → conviene reforzar X".

REGLA DE HONESTIDAD (importante): NUNCA inventes datos ni porcentajes. Si una tool no devuelve resultados,
falla, o devuelve un campo "error", decílo claramente ("no encontré datos de X" / "no pude
consultar ahora, probá de nuevo") en vez de adivinar. Citá los números EXACTOS que devuelven las tools.
Si la consulta está fuera de lo que tus tools pueden responder, decí que no tenés esa información.
Mejor un "no sé" honesto que una respuesta inventada."""

TOOLS = [
    {"type": "function", "function": {
        "name": "query_metrics",
        "description": "Devuelve KPIs (enviados, recibidos, respuestas asesor, tiempo respuesta promedio) en un rango.",
        "parameters": {"type": "object", "properties": {
            "from_": {"type": "string", "format": "date-time"},
            "to": {"type": "string", "format": "date-time"},
            "asesor": {"type": "string"},
        }},
    }},
    {"type": "function", "function": {
        "name": "search_conversations",
        "description": "Lista las últimas conversaciones, opcionalmente filtradas por waId/nombre.",
        "parameters": {"type": "object", "properties": {
            "q": {"type": "string"},
            "asesor": {"type": "string"},
            "limit": {"type": "integer", "default": 20},
        }},
    }},
    {"type": "function", "function": {
        "name": "list_documents",
        "description": "Lista documentos cargados en la base de conocimiento, opcionalmente por source.",
        "parameters": {"type": "object", "properties": {"source": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "upload_knowledge",
        "description": "Carga un texto a la base de conocimiento con la metadata indicada.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"}, "source": {"type": "string"}, "text": {"type": "string"},
        }, "required": ["title", "source", "text"]},
    }},
    {"type": "function", "function": {
        "name": "feedback_stats",
        "description": ("Estadísticas del sandbox de entrenamiento de Tomi: total de interacciones, "
                        "cuántas aprobadas (correctas), mejorables y rechazadas (malas), tasa de aprobación, "
                        "desglose por público y top de etiquetas de problemas. Usalo para 'cuántos mensajes "
                        "hubo', '% aprobado/rechazado', 'cómo viene la calidad de Tomi'."),
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "feedback_examples",
        "description": ("Devuelve ejemplos reales del sandbox para analizar qué mejorar. Filtrá por rating "
                        "('bad' = malas, 'mejorable', 'good'). Cada ejemplo trae la pregunta, la respuesta de "
                        "Tomi, la corrección del admin y las etiquetas del problema. Usalo para proponer mejoras concretas."),
        "parameters": {"type": "object", "properties": {
            "rating": {"type": "string", "enum": ["good", "mejorable", "bad"]},
            "limit": {"type": "integer", "default": 15},
        }},
    }},
]


def _run_tool(name: str, args: dict, db: Session, user: models.User):
    if name == "query_metrics":
        from datetime import datetime
        f = datetime.fromisoformat(args["from_"]) if args.get("from_") else None
        t = datetime.fromisoformat(args["to"]) if args.get("to") else None
        return metrics_summary(from_=f, to=t, asesor=args.get("asesor"), db=db, _=user)
    if name == "search_conversations":
        return list_conversations(q=args.get("q"), asesor=args.get("asesor"),
                                  limit=int(args.get("limit", 20)), db=db, _=user)
    if name == "list_documents":
        return [schemas.DocumentOut.model_validate(d).model_dump(mode="json")
                for d in list_documents(source=args.get("source"), db=db, _=user)]
    if name == "upload_knowledge":
        out = upload_text(payload=schemas.TextUploadIn(**args), db=db, user=user)
        return schemas.DocumentOut.model_validate(out).model_dump(mode="json")
    if name == "feedback_stats":
        from app.routers.feedback import feedback_stats as _fb_stats
        s = _fb_stats(db=db, _=user)
        data = s.model_dump() if hasattr(s, "model_dump") else dict(s)
        # Porcentajes explícitos para que el agente no los calcule mal.
        calificadas = data.get("good", 0) + data.get("mejorable", 0) + data.get("bad", 0)
        data["calificadas"] = calificadas
        data["pct_aprobadas"] = round(100 * data.get("good", 0) / calificadas, 1) if calificadas else 0.0
        data["pct_mejorables"] = round(100 * data.get("mejorable", 0) / calificadas, 1) if calificadas else 0.0
        data["pct_rechazadas"] = round(100 * data.get("bad", 0) / calificadas, 1) if calificadas else 0.0
        return data
    if name == "feedback_examples":
        from app.routers.feedback import list_feedback as _fb_list
        rows = _fb_list(
            status=None, rating=args.get("rating"), canal=None, publico=None,
            limit=int(args.get("limit", 15)), offset=0, db=db, _=user,
        )
        return [
            {
                "pregunta": r.pregunta,
                "respuesta_tomi": r.respuesta_tomi,
                "respuesta_corregida": r.respuesta_corregida,
                "rating": r.rating,
                "publico": r.publico,
                "tags": r.tags,
            }
            for r in rows
        ]
    raise ValueError(f"tool desconocido: {name}")


@router.post("/chat")
def chat(
    payload: schemas.AgentChatIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(500, "OPENAI_API_KEY no configurada")
    client = OpenAI(
        timeout=float(os.getenv("OPENAI_TIMEOUT", "30")),
        max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "2")),
    )
    messages = [{"role": "system", "content": SYSTEM}, *payload.history,
                {"role": "user", "content": payload.message}]

    for _ in range(4):  # máximo 4 rondas de tool calling
        resp = client.chat.completions.create(
            model=CHAT_MODEL, messages=messages, tools=TOOLS, tool_choice="auto",
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:
            messages.append({"role": "assistant", "content": msg.content})
            return {"reply": msg.content, "history": messages[1:]}

        messages.append({
            "role": "assistant", "content": msg.content,
            "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
        })
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            try:
                result = _run_tool(tc.function.name, args, db, user)
            except Exception as e:
                result = {"error": str(e)}
            messages.append({
                "role": "tool", "tool_call_id": tc.id,
                "content": json.dumps(result, default=str)[:8000],
            })
    return {"reply": "(no se pudo resolver en 4 turnos)", "history": messages[1:]}


@router.get("/history")
def history(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return db.query(models.AgentChatMessage).filter(
        models.AgentChatMessage.user_id == user.id
    ).order_by(models.AgentChatMessage.created_at.desc()).limit(100).all()

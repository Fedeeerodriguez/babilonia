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
Hablás en español rioplatense, sos breve y directo. Tenés acceso a tools para consultar métricas, conversaciones
y la base de conocimiento. Cuando el usuario pida cargar información a la base, usá upload_knowledge.

REGLA DE HONESTIDAD (importante): NUNCA inventes datos. Si una tool no devuelve resultados,
falla, o devuelve un campo "error", decílo claramente ("no encontré datos de X" / "no pude
consultar ahora, probá de nuevo") en vez de adivinar. Si la consulta está fuera de lo que tus
tools pueden responder, decí que no tenés esa información y sugerí escalarlo a un humano.
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

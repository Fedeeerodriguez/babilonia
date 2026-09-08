"""Auto-aprendizaje de Tommy a partir del feedback de los ASESORES.

Cuando un asesor corrige a Tommy en el chat, este módulo:
  1. Pre-filtra barato si el mensaje PARECE una corrección (evita gastar LLM en todo).
  2. Con un analizador LLM decide: ¿es feedback? ¿es técnico? ¿es aplicable/generalizable?
     Además compara contra las directrices ACTIVAS para decidir la acción:
       nueva | refuerza(id) | contradice(id) | redundante(id) | descartar
  3. Si aplica y hay alta confianza → crea/activa la directriz para TODOS y avisa por Telegram.
     Si la confianza es baja → la deja como 'propuesta' (cola de aprobación).

Solo se invoca para asesores (el gate de rol lo hace el endpoint). Es fail-safe: cualquier
error devuelve "no aprendí nada" sin romper la conversación.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone

from openai import OpenAI
from sqlalchemy.orm import Session

from app import models
from app.models import DirectrizAprendida, DirectrizEstado

log = logging.getLogger("tomi.aprendizaje")

CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini")
# Umbral de confianza (0-100) para auto-activar sin aprobación humana.
UMBRAL_AUTO = int(os.getenv("APRENDIZAJE_UMBRAL_AUTO", "80"))

# Pre-filtro: señales de que un mensaje es una corrección/feedback y no una consulta normal.
_RE_FEEDBACK = re.compile(
    r"\b(no\s+es\s+as[ií]|en\s+realidad|est[aá]s?\s+mal|est[aá]\s+mal|deber[ií]as|"
    r"ten[ée]s\s+que|no\s+deber[ií]as|correg|equivoc|mejor\s+(dec[ií]|deci|responde|and[aá])|"
    r"la\s+pr[oó]xima|no\s+me\s+diste|te\s+falt[oó]|falt[oó]|no\s+hagas|no\s+digas|siempre\s+que|"
    r"cuando\s+te\s+pregunt|no\s+era\s+eso|mal\b|incorrecto|est[aá]\s+bien\s+pero|"
    r"segu[ií]s\s+sin|todav[ií]a\s+no|sin\s+(poner|incluir|mandar|dar|aclarar)|"
    r"por\s+qu[eé]\s+no|te\s+ped[ií]|no\s+ten[ée]s\s+que|ten[ée]s\s+que\s+(poner|decir|incluir)|"
    r"acord[aá]te|record[aá]|de\s+ahora\s+en\s+m[aá]s|a\s+partir\s+de\s+ahora)",
    re.I,
)

_SYSTEM = """Sos el módulo de AUTO-MEJORA de Tommy, el asistente de Babilonia (correduría de
seguros con Allianz). Analizás un mensaje de un ASESOR que puede ser una corrección al
comportamiento de Tommy. Tu trabajo: decidir si de ese feedback se puede extraer una
DIRECTRIZ generalizable que haga a Tommy mejor asistente para TODOS.

Criterios para que sea aplicable:
- Es un feedback TÉCNICO/operativo sobre cómo Tommy responde o actúa (formato, tono, datos
  que debe incluir, procesos, privacidad, alcance), NO una consulta normal ni un desahogo.
- Es GENERALIZABLE: sirve para futuras conversaciones con cualquiera, no es un caso puntual
  ("para mí ponelo en negrita" no; "al listar clientes incluí el nº de póliza" sí).
- NO contradice reglas de privacidad ni te piden algo peligroso/abusivo.

Compará contra las DIRECTRICES ACTIVAS que te paso. Elegí una acción:
- "nueva": es una directriz nueva y válida.
- "refuerza": dice lo mismo que una activa (devolvé su id) → no dupliques.
- "contradice": choca con una activa (devolvé su id) → requiere revisión humana.
- "redundante": ya está cubierto.
- "descartar": no es feedback técnico/generalizable.

PROFUNDIZAR: si el feedback es válido pero te falta contexto para escribir una buena
directriz generalizable (en qué caso aplica, qué debería hacer exactamente, para quién),
poné "necesita_mas_info": true y formulá UNA sola pregunta concreta y breve para entender
mejor. Mirá el HISTORIAL: si ya preguntaste antes y el asesor respondió, NO vuelvas a
preguntar — escribí la directriz (necesita_mas_info=false). Preguntá 2 veces como máximo.

Devolvé SOLO JSON:
{"accion":"nueva|refuerza|contradice|redundante|descartar",
 "necesita_mas_info": true|false,
 "pregunta":"si necesita_mas_info, UNA pregunta breve para profundizar (o null)",
 "directriz":"imperativa y corta, en español, aplicable a todos (o null si aún preguntás)",
 "categoria":"tono|formato|dato|proceso|privacidad|alcance",
 "ambito":"todos|asesores|clientes",
 "confianza":0-100,
 "id_relacionada": <id o null>,
 "motivo":"breve",
 "acuse":"mensaje corto y cálido para el asesor agradeciendo el feedback (cuando ya cerraste la directriz)"}"""


def parece_feedback(mensaje: str) -> bool:
    return bool(mensaje and _RE_FEEDBACK.search(mensaje))


def _norm(texto: str) -> str:
    return re.sub(r"\s+", " ", (texto or "").strip().lower())


def _hash(texto: str) -> str:
    return hashlib.sha256(_norm(texto).encode("utf-8")).hexdigest()[:32]


def directrices_activas(db: Session, ambito: str | None = None) -> list[DirectrizAprendida]:
    q = db.query(DirectrizAprendida).filter(
        DirectrizAprendida.estado == DirectrizEstado.activa.value
    )
    rows = q.order_by(DirectrizAprendida.created_at.asc()).all()
    if ambito:
        rows = [r for r in rows if r.ambito in ("todos", ambito)]
    return rows


def bloque_directrices(db: Session, ambito: str = "todos") -> str:
    """Texto para inyectar en el systemMessage del agente n8n."""
    rows = directrices_activas(db, ambito)
    if not rows:
        return ""
    lineas = [f"- {r.texto}" for r in rows]
    return ("DIRECTRICES APRENDIDAS (seguilas siempre; las aprendió Tommy del feedback de "
            "los asesores):\n" + "\n".join(lineas))


def _analizar_llm(mensaje: str, respuesta_tomi: str, activas: list[DirectrizAprendida],
                  historial: list[dict] | None = None) -> dict | None:
    activas_txt = "\n".join(f"[{r.id}] {r.texto}" for r in activas) or "(ninguna)"
    hist_txt = ""
    if historial:
        # Últimos turnos de la charla (para saber si ya preguntamos y el asesor respondió).
        ult = historial[-6:]
        hist_txt = "HISTORIAL RECIENTE:\n" + "\n".join(
            f"{h.get('role')}: {str(h.get('content'))[:400]}" for h in ult) + "\n\n"
    contenido = (
        f"DIRECTRICES ACTIVAS:\n{activas_txt}\n\n"
        f"{hist_txt}"
        f"RESPUESTA PREVIA DE TOMMY:\n{(respuesta_tomi or '(desconocida)')[:1500]}\n\n"
        f"MENSAJE DEL ASESOR (posible feedback):\n{mensaje[:1500]}"
    )
    try:
        client = OpenAI()
        resp = client.chat.completions.create(
            model=CHAT_MODEL, temperature=0, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": _SYSTEM},
                      {"role": "user", "content": contenido}],
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as ex:  # noqa: BLE001
        log.warning("análisis de feedback falló: %s", ex)
        return None


def _notificar(directriz: DirectrizAprendida, auto: bool) -> None:
    try:
        from app.services.tomi.alertas import _enviar_telegram
        estado = "ACTIVADA (aplica a todos)" if auto else "propuesta (espera aprobación)"
        _enviar_telegram(
            f"🧠 <b>Tommy aprendió algo</b> · {estado}\n"
            f"<b>Directriz:</b> {directriz.texto}\n"
            f"<b>Categoría:</b> {directriz.categoria} · <b>confianza:</b> {directriz.confianza}\n"
            f"<b>Origen:</b> {directriz.origen_email or '—'}\n"
            f"<b>ID:</b> {directriz.id} (revisá/revertí en el panel o /api/tomi/directrices)"
        )
    except Exception as ex:  # noqa: BLE001
        log.warning("no se pudo notificar directriz: %s", ex)


def procesar_feedback_asesor(db: Session, mensaje: str, respuesta_tomi: str | None,
                             origen_email: str | None, historial: list[dict] | None = None,
                             continuacion: bool = False) -> dict:
    """Punto de entrada. Devuelve un dict con el resultado.

    `responder`: si viene con texto, es lo que Tommy le debe decir al asesor (una PREGUNTA
    para profundizar, o el ACUSE de recibo). n8n usa ese texto como respuesta al asesor.

    `continuacion=True`: la llamada anterior devolvió 'preguntar' y este mensaje es la
    respuesta del asesor a esa repregunta → NO aplicar el pre-filtro barato (procesar sí o sí).
    """
    if not continuacion and not parece_feedback(mensaje):
        return {"es_feedback": False}

    activas = directrices_activas(db)
    analisis = _analizar_llm(mensaje, respuesta_tomi or "", activas, historial)
    if not analisis:
        return {"es_feedback": True, "aplicable": False, "motivo": "análisis no disponible"}

    accion = (analisis.get("accion") or "descartar").lower()
    acuse = analisis.get("acuse")

    # PROFUNDIZAR: si falta contexto, Tommy repregunta y todavía NO crea la directriz.
    if analisis.get("necesita_mas_info") and analisis.get("pregunta") and accion != "descartar":
        return {"es_feedback": True, "aplicable": None, "accion": "preguntar",
                "pregunta": analisis["pregunta"], "responder": analisis["pregunta"]}

    if accion == "descartar" or not analisis.get("directriz"):
        return {"es_feedback": True, "aplicable": False, "accion": accion,
                "motivo": analisis.get("motivo"), "acuse": acuse, "responder": acuse}

    # Refuerza una existente → subimos veces_reforzada, no duplicamos.
    if accion in ("refuerza", "redundante") and analisis.get("id_relacionada"):
        d = db.get(DirectrizAprendida, analisis["id_relacionada"])
        if d:
            d.veces_reforzada = (d.veces_reforzada or 1) + 1
            db.commit()
            return {"es_feedback": True, "aplicable": True, "accion": "reforzada",
                    "directriz_id": d.id, "directriz": d.texto, "acuse": acuse, "responder": acuse}

    texto = analisis["directriz"].strip()
    dh = _hash(texto)
    # Dedupe exacto por hash (aunque el LLM no lo haya detectado).
    ya = db.query(DirectrizAprendida).filter(DirectrizAprendida.dedupe_hash == dh).first()
    if ya:
        ya.veces_reforzada = (ya.veces_reforzada or 1) + 1
        db.commit()
        return {"es_feedback": True, "aplicable": True, "accion": "reforzada",
                "directriz_id": ya.id, "directriz": ya.texto, "acuse": acuse, "responder": acuse}

    confianza = int(analisis.get("confianza") or 0)
    # Contradice una activa → SIEMPRE a revisión humana (no auto-activar).
    contradice = accion == "contradice"
    auto = (confianza >= UMBRAL_AUTO) and not contradice
    estado = DirectrizEstado.activa.value if auto else DirectrizEstado.propuesta.value

    d = DirectrizAprendida(
        texto=texto,
        categoria=analisis.get("categoria"),
        ambito=analisis.get("ambito") or "todos",
        estado=estado,
        confianza=confianza,
        dedupe_hash=dh,
        feedback_texto=mensaje[:2000],
        respuesta_previa=(respuesta_tomi or "")[:2000],
        origen_email=origen_email,
        motivo=(("CONTRADICE activa; " if contradice else "") + (analisis.get("motivo") or ""))[:1000],
        activada_at=datetime.now(timezone.utc) if auto else None,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    _notificar(d, auto)
    return {"es_feedback": True, "aplicable": True,
            "accion": "activada" if auto else "propuesta",
            "directriz_id": d.id, "directriz": d.texto, "confianza": confianza,
            "contradice": contradice, "acuse": acuse, "responder": acuse}

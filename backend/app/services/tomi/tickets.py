"""Creación de tickets en Notion, personalizada y con asignación al admin encargado.

Reemplaza los nodos crudos de n8n (que solo seteaban campos sueltos y usaban un
ticket_id inventado por el LLM). Acá:
  - El ticket_id se genera DETERMINISTICAMENTE en el backend (nunca vacío, nunca duplicado).
  - Se ASIGNA al admin correcto (Ceci / Yans / Anayanci / Jime) via el campo "Asignado a".
  - Se mapean tipo de solicitud, prioridad, rol y medio a los selects reales de Notion.

Base destino: "Tickets Babilonia" (NOTION_DB_TICKETS_BABILONIA). La de Allianz
(NOTION_DB_TICKETS_ALLIANZ) requiere que la integración tenga acceso; si no lo tiene,
todo entra a Babilonia con Tipo="Trámite Allianz" para distinguirlo.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from notion_client.errors import APIResponseError

from app.services.tomi import notion_client as nc

log = logging.getLogger("tomi.tickets")

# Admins válidos y sus áreas (según los roles que dio Jime).
ENCARGADOS = {"Ceci", "Yans", "Anayanci", "Jime"}

# Mapeo laxo: si el LLM manda un tipo aproximado, lo llevamos al select real de Notion.
TIPOS_VALIDOS = {
    "Reporte de Error", "Pregunta", "Idea", "Trámite Allianz", "Mentoría cliente",
    "Solicitud de Apoyo a Cliente", "Atención en Discord", "Atención en Correo",
}
PRIORIDAD_MAP = {
    "baja": "🔵 Baja", "media": "🟡 Media", "alta": "🔴 Alta",
}
ROLES_VALIDOS = {"Asesor", "Estudiante", "Cliente Allianz", "Prospecto"}

# Encargado -> su ficha en "Directorio Babilonia" (relación `Encargado`) y su usuario de Notion.
# El select "Asignado a" NO notifica a nadie; la @mención al usuario sí (le llega a su bandeja).
COLABORADORES = {
    "Ceci":     {"pagina": "48908103-423c-49b5-b3a8-b00af4db3b48", "usuario": "732029ab-3634-4266-bd6b-fbb1ca87859b"},
    "Yans":     {"pagina": "391e7979-cda4-80de-a924-fa6560a27424", "usuario": "99bb24ed-d7fd-402c-aa89-677904b45979"},
    "Anayanci": {"pagina": "180e7979-cda4-8084-b32a-ed46a940d769", "usuario": "a41a6a41-4f06-4016-ad3b-c2f5cd4cd9f2"},
    "Jime":     {"pagina": "4a9cc007-b504-4de2-a6c2-806c0019be0b", "usuario": "37457563-647f-4782-a466-27770524b901"},
}


def _gen_ticket_id() -> str:
    """ID legible y único: TCK-YYMMDD-XXXX (XXXX de un uuid). Determinístico por llamada."""
    now = datetime.now(timezone.utc)
    sufijo = uuid.uuid4().hex[:4].upper()
    return f"TCK-{now:%y%m%d}-{sufijo}"


def _norm_encargado(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    v = v.strip().strip("[]").capitalize()
    # tolera "ceci", "[Ceci]", "CECI"
    for e in ENCARGADOS:
        if v.lower() == e.lower():
            return e
    return None


def _strip_prefijos(texto: str) -> str:
    """Quita prefijos tipo '[Yans] ' (uno o varios) al inicio. La descripción que llega
    de n8n suele venir con '[Encargado]' adelante, y al anteponer otro se duplicaba
    ('[Yans] [Yans] ...'). Además el encargado ya vive en la columna 'Asignado a'."""
    return re.sub(r"^(?:\s*\[[^\]]{1,24}\]\s*)+", "", texto or "").strip()


def _telefono(wa_id: Optional[str], telefono: Optional[str]) -> Optional[str]:
    """Número a quien responderle. Prioriza el wa_id del chat (viene del webhook de WATI, no
    del LLM, así que nunca falta); si no hay, usa el teléfono que haya mandado el agente."""
    d = re.sub(r"\D", "", str(wa_id or ""))
    if len(d) >= 8:
        return "+" + d
    t = (telefono or "").strip()
    return t or None


def _notificar(page_id: str, enc: Optional[str], titulo: str, ticket_id: str) -> bool:
    """@menciona al encargado en la página del ticket → Notion le manda la notificación.
    No-fatal: si falla, el ticket ya quedó creado igual."""
    col = COLABORADORES.get(enc or "")
    if not col or not page_id:
        return False
    try:
        nc._retry_429(
            nc._client().blocks.children.append,
            block_id=page_id,
            children=[{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [
                {"type": "mention", "mention": {"type": "user", "user": {"id": col["usuario"]}}},
                {"type": "text", "text": {"content": f" tenés un ticket nuevo para resolver ({ticket_id}): {titulo}"}},
            ]}}],
        )
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("crear_ticket: no se pudo notificar a %s (%s): %s", enc, ticket_id, e)
        return False


def _titulo_corto(asunto: Optional[str], descripcion: str, enc: Optional[str]) -> str:
    """Nombre del ticket = resumen CORTO del problema, no la descripción entera (que
    igual se guarda completa en el campo 'Descripción'). Evita que la vista se sature.

    Prioriza `asunto` (resumen breve que puede mandar el LLM). Si no viene, toma la
    primera oración de la descripción. Limpia prefijos '[Encargado]' y acota a ~60
    chars. Antepone un ÚNICO '[Encargado]' para escaneo rápido."""
    base = _strip_prefijos(asunto) if asunto else ""
    if not base:
        desc = _strip_prefijos(descripcion)
        base = re.split(r"(?<=[.!?])\s+", desc, maxsplit=1)[0]
    base = re.sub(r"\s+", " ", base).strip()[:60].rstrip(" ,;:.-")
    return f"[{enc}] {base}" if enc else (base or "Ticket sin descripción")


def crear_ticket(
    descripcion: str,
    asunto: Optional[str] = None,
    encargado: Optional[str] = None,
    nombre_cliente: Optional[str] = None,
    email: Optional[str] = None,
    telefono: Optional[str] = None,
    rol: Optional[str] = None,
    tipo: Optional[str] = None,
    prioridad: Optional[str] = None,
    medio: Optional[str] = None,
    wa_id: Optional[str] = None,
    nombre_whatsapp: Optional[str] = None,
) -> Dict[str, Any]:
    """Crea un ticket en Notion (Tickets Babilonia) asignado al admin encargado.

    Devuelve {ok, ticket_id, encargado, url, notion_page_id} o {ok:false, error}.
    """
    descripcion = (descripcion or "").strip()
    if not descripcion:
        return {"ok": False, "error": "descripcion vacía — no se creó ticket"}

    db_id = nc.DB_TICKETS_BABILONIA
    if not db_id:
        return {"ok": False, "error": "NOTION_DB_TICKETS_BABILONIA no configurado"}

    ticket_id = _gen_ticket_id()
    enc = _norm_encargado(encargado)

    # Título = resumen corto (no la descripción entera). El detalle completo va aparte
    # en el campo "Descripción". Evita el "[Yans] [Yans] <texto larguísimo>".
    titulo = _titulo_corto(asunto, descripcion, enc)
    desc_body = _strip_prefijos(descripcion) or descripcion
    tel = _telefono(wa_id, telefono)
    # Pie de contacto: a quién responderle (queda visible aunque la vista no muestre TELEFONO).
    contacto = " · ".join(x for x in (
        (nombre_cliente or nombre_whatsapp or "").strip(),
        f"WhatsApp {tel}" if tel else "",
    ) if x)
    if contacto:
        desc_body = f"{desc_body}\n\n📱 Contacto: {contacto}"

    props: Dict[str, Any] = {
        "Nombre": {"title": [{"text": {"content": titulo}}]},
        "Descripción": {"rich_text": [{"text": {"content": desc_body[:1900]}}]},
        "TICKET ID": {"rich_text": [{"text": {"content": ticket_id}}]},
        "Estado": {"status": {"name": "Por hacer"}},
    }
    if enc:
        props["Asignado a"] = {"select": {"name": enc}}
        if enc in COLABORADORES:
            props["Encargado"] = {"relation": [{"id": COLABORADORES[enc]["pagina"]}]}
    if email:
        props["Correo electrónico"] = {"email": email.strip()}
    if tel:
        props["TELEFONO"] = {"phone_number": tel}
    if rol and rol in ROLES_VALIDOS:
        props["Rol"] = {"select": {"name": rol}}
    if tipo and tipo in TIPOS_VALIDOS:
        props["Tipo de Solicitud"] = {"select": {"name": tipo}}
    pr = PRIORIDAD_MAP.get((prioridad or "media").lower().strip())
    if pr:
        props["Prioridad"] = {"select": {"name": pr}}
    if medio and medio in ("Teléfono", "Discord", "Correo"):
        props["Medio de Solicitud"] = {"select": {"name": medio}}
    elif wa_id:
        props["Medio de Solicitud"] = {"select": {"name": "Teléfono"}}  # entró por WhatsApp

    t0 = time.time()
    try:
        try:
            page = nc._retry_429(
                nc._client().pages.create,
                parent={"database_id": db_id},
                properties=props,
            )
        except APIResponseError as e:
            # Si falla solo por la relación al Directorio, no perdemos el ticket: reintento sin ella.
            if "Encargado" not in props:
                raise
            log.warning("crear_ticket: relación Encargado rechazada (%s); reintento sin ella", e)
            props.pop("Encargado", None)
            page = nc._retry_429(
                nc._client().pages.create,
                parent={"database_id": db_id},
                properties=props,
            )
    except APIResponseError as e:
        log.error("crear_ticket Notion falló: %s", e)
        return {"ok": False, "error": f"Notion: {e}", "ticket_id": ticket_id}
    except Exception as e:
        log.error("crear_ticket error: %s", e)
        return {"ok": False, "error": str(e), "ticket_id": ticket_id}

    notificado = _notificar(page.get("id"), enc, titulo, ticket_id)

    return {
        "ok": True,
        "ticket_id": ticket_id,
        "encargado": enc,
        "notificado": notificado,
        "telefono": tel,
        "url": page.get("url"),
        "notion_page_id": page.get("id"),
        "tiempo_ms": int((time.time() - t0) * 1000),
    }

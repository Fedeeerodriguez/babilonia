"""
Clasificador determinista de usuarios para Tomi.

Reemplaza al sub-agente n8n `AI Agent2` que decidía si el usuario es
asesor / estudiante / cliente / prospecto.

Flujo:
  1) Si viene user_id y existe en `tomi_clasificaciones` → cache hit, devolver.
  2) Si no hay email en el mensaje del usuario → "no registrado / prospecto".
  3) Consultar Notion en orden: Asesores → Estudiantes → Clientes General.
  4) Persistir el resultado en `tomi_clasificaciones` para evitar reconsultas.

Salida compatible con el AI Agent2:
  { "comando_1": "registrado"|"no registrado", "comando_2": "asesor|estudiante|cliente|prospecto" }

NIVEL FIJO (regla de negocio): el camino es estudiante → cliente Allianz → asesor. Una vez que
un número tiene un nivel real (estudiante/cliente/asesor) ese nivel queda FIJO en todas las
ejecuciones: nunca baja y nunca cambia por un email que aparezca en el mensaje (un asesor que
escribe el correo de un cliente sigue siendo el asesor). Solo puede SUBIR, cuando Notion lo
encuentra por su propio teléfono en un nivel más alto. Para corregir un error a mano:
DELETE /api/tomi/clasificar-usuario/{user_id}.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.tomi import notion_client as nc

# Nivel de cada categoría. prospecto/desconocido = 0 (todavía sin nivel fijo).
NIVEL = {"desconocido": 0, "prospecto": 0, "estudiante": 1, "cliente": 2, "asesor": 3}
# Cada cuánto se revisa si alguien con nivel fijo SUBIÓ (p. ej. un cliente que pasó a asesor).
HORAS_REVISION_ASCENSO = 24


def nivel(comando_2: Optional[str]) -> int:
    return NIVEL.get((comando_2 or "").strip().lower(), 0)


def es_fijo(comando_2: Optional[str]) -> bool:
    """True si la categoría ya es un nivel real (estudiante/cliente/asesor): no se puede bajar."""
    return nivel(comando_2) > 0


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def extraer_email(texto: str) -> Optional[str]:
    if not texto:
        return None
    m = EMAIL_RE.search(texto)
    return m.group(0).strip().lower() if m else None


def _table_exists(db: Session) -> bool:
    try:
        db.execute(text("SELECT 1 FROM tomi_clasificaciones LIMIT 1"))
        return True
    except Exception:
        db.rollback()
        return False


def buscar_cache(db: Session, user_id: Optional[str], email: Optional[str]) -> Optional[Dict[str, Any]]:
    if not _table_exists(db):
        return None
    row = None
    if user_id:
        row = db.execute(text("""
            SELECT user_id, email, comando_1, comando_2, user_nombre, data, updated_at
            FROM tomi_clasificaciones WHERE user_id = :uid
        """), {"uid": str(user_id)}).mappings().first()
    if not row and email:
        row = db.execute(text("""
            SELECT user_id, email, comando_1, comando_2, user_nombre, data, updated_at
            FROM tomi_clasificaciones WHERE email = :em ORDER BY updated_at DESC LIMIT 1
        """), {"em": email.lower()}).mappings().first()
    return dict(row) if row else None


def guardar_clasificacion(
    db: Session,
    user_id: str,
    email: str,
    comando_1: str,
    comando_2: str,
    user_nombre: Optional[str] = None,
    notion_page_id: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Guarda la clasificación del número. Devuelve False si NO se guardó porque bajaría de
    nivel: un número con nivel fijo nunca se pisa con uno menor (venga de donde venga)."""
    if not _table_exists(db):
        return False
    actual = db.execute(text("SELECT comando_2 FROM tomi_clasificaciones WHERE user_id = :uid"),
                        {"uid": str(user_id)}).scalar()
    if actual is not None and nivel(comando_2) < nivel(actual):
        return False
    db.execute(text("""
        INSERT INTO tomi_clasificaciones
          (user_id, email, comando_1, comando_2, user_nombre, notion_page_id, data, updated_at)
        VALUES (:uid, :em, :c1, :c2, :nom, :pid, CAST(:data AS jsonb), now())
        ON CONFLICT (user_id) DO UPDATE SET
          email = EXCLUDED.email,
          comando_1 = EXCLUDED.comando_1,
          comando_2 = EXCLUDED.comando_2,
          user_nombre = COALESCE(EXCLUDED.user_nombre, tomi_clasificaciones.user_nombre),
          notion_page_id = EXCLUDED.notion_page_id,
          data = EXCLUDED.data,
          updated_at = now()
    """), {
        "uid": str(user_id),
        "em": (email or "").lower(),
        "c1": comando_1,
        "c2": comando_2,
        "nom": user_nombre,
        "pid": notion_page_id,
        "data": json.dumps(data or {}, default=str, ensure_ascii=False),
    })
    db.commit()
    return True


def _marcar_revisado(db: Session, user_id: str) -> None:
    """Corre el reloj de la revisión de ascenso sin tocar la clasificación."""
    db.execute(text("UPDATE tomi_clasificaciones SET updated_at = now() WHERE user_id = :uid"),
               {"uid": str(user_id)})
    db.commit()


def _vencida(updated_at: Any) -> bool:
    if not isinstance(updated_at, datetime):
        return True
    ts = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - ts > timedelta(hours=HORAS_REVISION_ASCENSO)


def _datos_notion(bucket: Dict[str, Any]) -> Dict[str, Any]:
    data = bucket.get("data") if isinstance(bucket.get("data"), dict) else {}
    return {
        "data": data,
        "email": (data.get("Correo") or "").strip().lower(),
        "nombre": (data.get("Nombre Completo") or data.get("Nombre completo")
                   or data.get("Nombre del Cliente") or data.get("_title")),
        "page_id": data.get("id") or data.get("_id"),
    }


def _respuesta_cache(cached: Dict[str, Any], fuente: str = "cache") -> Dict[str, Any]:
    return {
        "comando_1": cached["comando_1"],
        "comando_2": cached["comando_2"],
        "email": cached["email"],
        "user_id": cached["user_id"],
        "user_nombre": cached.get("user_nombre"),
        "fuente": fuente,
        "data": cached.get("data"),
    }


def _revisar_ascenso(db: Session, cached: Dict[str, Any], user_nombre: Optional[str]) -> Dict[str, Any]:
    """Nivel fijo: se devuelve el guardado. Cada HORAS_REVISION_ASCENSO se mira en Notion (por
    el teléfono del propio número) si SUBIÓ de nivel; si subió, se guarda el nivel nuevo.
    Nunca baja: si Notion falla o devuelve menos, queda el que estaba."""
    uid = str(cached["user_id"])
    if nivel(cached.get("comando_2")) >= NIVEL["asesor"] or not _vencida(cached.get("updated_at")):
        return _respuesta_cache(cached)
    try:
        bucket = nc.clasificar_usuario_por_telefono(uid)
    except Exception:
        bucket = {"tipo": "prospecto", "data": None}
    tipo = bucket.get("tipo")
    if nivel(tipo) > nivel(cached.get("comando_2")):
        d = _datos_notion(bucket)
        guardar_clasificacion(db, user_id=uid, email=d["email"] or cached.get("email") or "",
                              comando_1="registrado", comando_2=tipo,
                              user_nombre=user_nombre or d["nombre"] or cached.get("user_nombre"),
                              notion_page_id=d["page_id"], data=d["data"] or None)
        return {"comando_1": "registrado", "comando_2": tipo,
                "email": d["email"] or cached.get("email"), "user_id": cached["user_id"],
                "user_nombre": user_nombre or d["nombre"] or cached.get("user_nombre"),
                "fuente": "ascenso", "data": d["data"] or None}
    _marcar_revisado(db, uid)
    return _respuesta_cache(cached)


def clasificar(
    db: Session,
    *,
    user_id: Optional[str] = None,
    mensaje_usuario: Optional[str] = None,
    email: Optional[str] = None,
    user_nombre: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Reglas (idénticas al prompt original):

      A) Si hay clasificación previa para user_id → devolverla.
      B) Sin email en el mensaje → "no registrado / prospecto".
      C) Buscar en Notion: asesores → estudiantes → clientes.
    """
    # Extraemos el email ANTES de mirar el caché, para detectar si el usuario está
    # dando un email NUEVO (distinto al que teníamos cacheado para su número).
    email_norm = (email or "").strip().lower() or extraer_email(mensaje_usuario or "")

    # A) NIVEL FIJO. Si el número ya tiene un nivel real (estudiante/cliente/asesor), ése
    #    es su nivel en TODAS las ejecuciones: un email en el mensaje NO lo re-clasifica
    #    (antes, un asesor que escribía el correo de un cliente quedaba guardado como ese
    #    cliente). Solo puede subir (ver _revisar_ascenso). `force` tampoco lo baja.
    #    Un prospecto guardado no es fijo: puede mejorar por email o teléfono.
    cache_previa: Optional[Dict[str, Any]] = None
    if user_id:
        cached = buscar_cache(db, user_id=str(user_id), email=None)
        if cached and es_fijo(cached.get("comando_2")):
            return _revisar_ascenso(db, cached, user_nombre)
        if cached and not force:
            cache_previa = cached  # prospecto: fallback si no mejoramos

    if not email_norm:
        # B.1) Identificar por TELÉFONO: el user_id ES el waId de WhatsApp. Muchos
        # usuarios reales (asesores/alumnos recurrentes) nunca escriben su correo —
        # sólo mandan mensajes operativos. Si su número está en Notion, los ubicamos
        # sin pedir nada y persistimos la identidad para los próximos mensajes.
        if user_id and not force:
            try:
                bucket = nc.clasificar_usuario_por_telefono(str(user_id))
            except Exception:
                bucket = {"tipo": "prospecto", "data": None}
            tipo = bucket.get("tipo")
            if tipo and tipo != "prospecto":
                d = _datos_notion(bucket)
                data, email_rec, nombre_rec, notion_page_id = d["data"], d["email"], d["nombre"], d["page_id"]
                guardar_clasificacion(
                    db,
                    user_id=str(user_id),
                    email=email_rec,
                    comando_1="registrado",
                    comando_2=tipo,
                    user_nombre=user_nombre or nombre_rec,
                    notion_page_id=notion_page_id,
                    data=data or None,
                )
                return {
                    "comando_1": "registrado",
                    "comando_2": tipo,
                    "email": email_rec or None,
                    "user_id": user_id,
                    "user_nombre": user_nombre or nombre_rec,
                    "fuente": "notion_telefono",
                    "data": data or None,
                }

        # B.2) Si ya lo conocíamos (aunque fuera como prospecto), mantenemos esa
        # clasificación en vez de volver a pedirle el correo — no lo pesteamos. Si más
        # adelante da un email, la rama C/D lo re-clasifica y actualiza la caché.
        if cache_previa:
            return {
                "comando_1": cache_previa.get("comando_1") or "registrado",
                "comando_2": cache_previa.get("comando_2") or "prospecto",
                "email": cache_previa.get("email"),
                "user_id": user_id,
                "user_nombre": user_nombre or cache_previa.get("user_nombre"),
                "fuente": "cache",
                "data": cache_previa.get("data"),
            }

        # Usuario nuevo del que no sabemos nada: NO asumir prospecto. Señalamos que
        # falta el email para que Tomi lo pida. No se cachea (no sabemos quién es).
        resultado = {"comando_1": "no registrado", "comando_2": "desconocido",
                     "email": None, "user_id": user_id, "user_nombre": user_nombre,
                     "fuente": "sin_email", "necesita_email": True, "data": None}
        return resultado

    # C) cache por email (otro chat con el mismo correo). Solo si ese correo ya tiene un nivel
    #    real: un 'prospecto' guardado puede venir de una falla momentánea de Notion, así que
    #    se vuelve a consultar (antes quedaba trabado como prospecto para siempre).
    if not force:
        cached = buscar_cache(db, user_id=None, email=email_norm)
        if cached and es_fijo(cached.get("comando_2")):
            # asociamos este user_id al mismo resultado
            if user_id:
                guardar_clasificacion(
                    db,
                    user_id=str(user_id),
                    email=email_norm,
                    comando_1=cached["comando_1"],
                    comando_2=cached["comando_2"],
                    user_nombre=user_nombre or cached.get("user_nombre"),
                    notion_page_id=None,
                    data=cached.get("data"),
                )
            return {
                "comando_1": cached["comando_1"],
                "comando_2": cached["comando_2"],
                "email": email_norm,
                "user_id": user_id,
                "user_nombre": user_nombre or cached.get("user_nombre"),
                "fuente": "cache_email",
                "data": cached.get("data"),
            }

    # D) consultar Notion en orden
    bucket = nc.clasificar_usuario_por_email(email_norm)
    tipo = bucket.get("tipo", "prospecto")
    data = bucket.get("data")
    notion_page_id = (data or {}).get("id") if isinstance(data, dict) else None

    if tipo == "prospecto":
        comando_1, comando_2 = "registrado", "prospecto"
    else:
        comando_1, comando_2 = "registrado", tipo

    if user_id:
        guardar_clasificacion(
            db,
            user_id=str(user_id),
            email=email_norm,
            comando_1=comando_1,
            comando_2=comando_2,
            user_nombre=user_nombre,
            notion_page_id=notion_page_id,
            data=data if isinstance(data, dict) else None,
        )

    return {
        "comando_1": comando_1,
        "comando_2": comando_2,
        "email": email_norm,
        "user_id": user_id,
        "user_nombre": user_nombre,
        "fuente": "notion",
        "data": data,
    }

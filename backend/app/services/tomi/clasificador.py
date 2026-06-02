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
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.tomi import notion_client as nc

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
) -> None:
    if not _table_exists(db):
        return
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
    # A) cache por user_id
    if not force and user_id:
        cached = buscar_cache(db, user_id=str(user_id), email=None)
        if cached:
            return {
                "comando_1": cached["comando_1"],
                "comando_2": cached["comando_2"],
                "email": cached["email"],
                "user_id": cached["user_id"],
                "user_nombre": cached.get("user_nombre"),
                "fuente": "cache",
                "data": cached.get("data"),
            }

    # B) extraer email del mensaje si no vino explícito
    email_norm = (email or "").strip().lower() or extraer_email(mensaje_usuario or "")

    if not email_norm:
        resultado = {"comando_1": "no registrado", "comando_2": "prospecto",
                     "email": None, "user_id": user_id, "user_nombre": user_nombre,
                     "fuente": "sin_email", "data": None}
        # no guardamos en cache: aún no sabemos quién es
        return resultado

    # C) cache por email (otro chat con el mismo correo)
    if not force:
        cached = buscar_cache(db, user_id=None, email=email_norm)
        if cached:
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

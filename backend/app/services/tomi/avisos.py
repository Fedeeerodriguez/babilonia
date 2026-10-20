"""Avisos temporales de Tommy: información que el equipo agrega y quita desde la plataforma.

Ejemplo: "La Liga Babilonia está cerrada por mantenimiento hasta el lunes 3". Cada aviso tiene
audiencia (todos / asesor / cliente / estudiante / prospecto), un interruptor `activo` y una
ventana opcional `desde`/`hasta` (se prende y se apaga solo).

Cómo llega al agente: `/api/tomi/clasificar-usuario` (el primer paso de CADA mensaje en n8n)
agrega el bloque de avisos vigentes a `nota_sistema`, que el AGENTE SOPORTE TOMMY ya recibe en su
input. No hay que tocar el flujo de n8n ni el RAG: cambiar un aviso en la plataforma vale para el
próximo mensaje (caché de 30 s).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app import models

AUDIENCIAS = ("todos", "asesor", "cliente", "estudiante", "prospecto")
UTC_OFFSET_MX = -6  # CDMX sin horario de verano: las fechas del bloque se escriben en hora de México
_TTL = 30.0
_cache: dict[str, tuple[float, str]] = {}


def _utc(d: Optional[datetime]) -> Optional[datetime]:
    """SQLite devuelve fechas sin zona: se toman como UTC."""
    if d is None:
        return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def estado(a: models.AvisoTomi, ahora: Optional[datetime] = None) -> str:
    """vigente | programado | vencido | apagado."""
    ahora = ahora or datetime.now(timezone.utc)
    if not a.activo:
        return "apagado"
    desde, hasta = _utc(a.desde), _utc(a.hasta)
    if desde and desde > ahora:
        return "programado"
    if hasta and hasta <= ahora:
        return "vencido"
    return "vigente"


def vigentes(db: Session, tipo: Optional[str] = None, ahora: Optional[datetime] = None) -> list[models.AvisoTomi]:
    """Los avisos que el agente tiene que ver ahora para este tipo de usuario."""
    tipo = (tipo or "").strip().lower()
    filas = db.query(models.AvisoTomi).filter(models.AvisoTomi.activo.is_(True)).all()
    return sorted((a for a in filas if estado(a, ahora) == "vigente"
                   and (a.audiencia or "todos") in ("todos", tipo)),
                  key=lambda a: (_utc(a.created_at) or datetime.min.replace(tzinfo=timezone.utc), a.id))


def _fecha_mx(d: datetime) -> str:
    return (_utc(d) + timedelta(hours=UTC_OFFSET_MX)).strftime("%d/%m/%Y %H:%M")


def armar_bloque(avisos: list[models.AvisoTomi]) -> str:
    if not avisos:
        return ""
    lineas = ["AVISOS VIGENTES DE BABILONIA (los cargó el equipo; son temporales y tienen PRIORIDAD sobre "
              "cualquier otra información, incluidas memorias y bases de datos. Úsalos solo si tienen que ver "
              "con lo que pide el usuario; no los menciones si no vienen al caso):"]
    for a in avisos:
        hasta = f" (vigente hasta el {_fecha_mx(a.hasta)}, hora de CDMX)" if a.hasta else ""
        lineas.append(f"- {a.titulo.strip()}: {' '.join(a.contenido.split())}{hasta}")
    return "\n".join(lineas)


def bloque(db: Session, tipo: Optional[str] = None) -> str:
    """Texto para `nota_sistema` (vacío si no hay avisos). Con caché corta por tipo de usuario."""
    clave = (tipo or "").strip().lower()
    hit = _cache.get(clave)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    texto = armar_bloque(vigentes(db, clave))
    _cache[clave] = (time.monotonic(), texto)
    return texto


def invalidar() -> None:
    """Después de crear/editar/borrar: el próximo mensaje ya ve el cambio."""
    _cache.clear()


def agregar_a_nota(res: dict, texto: str) -> dict:
    """Suma el bloque a `nota_sistema` sin pisar lo que ya traía (ej. el modo demo)."""
    if texto:
        previa = (res.get("nota_sistema") or "").strip()
        res["nota_sistema"] = f"{previa}\n\n{texto}" if previa else texto
        res["avisos_bloque"] = texto
    return res

"""Avisos temporales de Tommy — los carga el equipo desde la plataforma (JWT admin).

  GET    /api/tomi/avisos                      -> todos, con su estado (vigente/programado/vencido/apagado)
  POST   /api/tomi/avisos                      -> crear
  PUT    /api/tomi/avisos/{id}                 -> editar (también prender/apagar con {activo})
  DELETE /api/tomi/avisos/{id}                 -> borrar
  GET    /api/tomi/avisos/vista-previa?tipo=   -> exactamente lo que recibe el agente para ese tipo de usuario

El agente los recibe en `nota_sistema` de /api/tomi/clasificar-usuario (ver services/tomi/avisos.py).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.security import require_admin
from app.services.tomi import avisos as av

router = APIRouter(prefix="/api/tomi/avisos", tags=["tomi-avisos"])


class AvisoIn(BaseModel):
    titulo: Optional[str] = Field(default=None, max_length=120)
    contenido: Optional[str] = Field(default=None, max_length=1500)
    audiencia: Optional[str] = None
    activo: Optional[bool] = None
    desde: Optional[datetime] = None
    hasta: Optional[datetime] = None


def _iso(d: Optional[datetime]) -> Optional[str]:
    d = av._utc(d)
    return d.isoformat() if d else None


def _out(a: models.AvisoTomi) -> dict:
    return {"id": a.id, "titulo": a.titulo, "contenido": a.contenido, "audiencia": a.audiencia or "todos",
            "activo": bool(a.activo), "desde": _iso(a.desde), "hasta": _iso(a.hasta), "estado": av.estado(a),
            "creado_por": a.creado_por, "actualizado_por": a.actualizado_por,
            "created_at": _iso(a.created_at), "updated_at": _iso(a.updated_at)}


def _validar(a: models.AvisoTomi) -> None:
    if not (a.titulo or "").strip() or not (a.contenido or "").strip():
        raise HTTPException(status_code=400, detail="El aviso necesita título y contenido.")
    if (a.audiencia or "todos") not in av.AUDIENCIAS:
        raise HTTPException(status_code=400, detail=f"Audiencia: {', '.join(av.AUDIENCIAS)}.")
    if a.desde and a.hasta and av._utc(a.hasta) <= av._utc(a.desde):
        raise HTTPException(status_code=400, detail="La fecha de fin tiene que ser posterior a la de inicio.")


def _quien(user: models.User) -> str:
    return user.full_name or user.email


def _aplicar(a: models.AvisoTomi, body: AvisoIn, campos: set[str]) -> None:
    for k in campos:
        v = getattr(body, k)
        if isinstance(v, str):
            v = v.strip()
        if isinstance(v, datetime):
            v = av._utc(v)
        setattr(a, k, v)


@router.get("")
def listar(db: Session = Depends(get_db), _: models.User = Depends(require_admin)):
    orden = {"vigente": 0, "programado": 1, "apagado": 2, "vencido": 3}
    items = [_out(a) for a in db.query(models.AvisoTomi).all()]
    items.sort(key=lambda x: (orden.get(x["estado"], 9), -(x["id"] or 0)))
    return {"items": items, "vigentes": sum(1 for i in items if i["estado"] == "vigente")}


@router.get("/vista-previa")
def vista_previa(tipo: str = "cliente", db: Session = Depends(get_db), _: models.User = Depends(require_admin)):
    return {"tipo": tipo, "bloque": av.armar_bloque(av.vigentes(db, tipo))}


@router.post("")
def crear(body: AvisoIn, db: Session = Depends(get_db), user: models.User = Depends(require_admin)):
    a = models.AvisoTomi(audiencia="todos", activo=True, creado_por=_quien(user), actualizado_por=_quien(user),
                         created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    _aplicar(a, body, {k for k, v in body.model_dump().items() if v is not None} | {"desde", "hasta"})
    _validar(a)
    db.add(a)
    db.commit()
    db.refresh(a)
    av.invalidar()
    return _out(a)


@router.put("/{aviso_id}")
def editar(aviso_id: int, body: AvisoIn, db: Session = Depends(get_db), user: models.User = Depends(require_admin)):
    a = db.get(models.AvisoTomi, aviso_id)
    if not a:
        raise HTTPException(status_code=404, detail="Aviso no encontrado.")
    # Solo lo que vino en el pedido (así {activo:false} no borra las fechas; {hasta:null} sí la quita).
    _aplicar(a, body, set(body.model_fields_set))
    a.actualizado_por = _quien(user)
    a.updated_at = datetime.now(timezone.utc)
    _validar(a)
    db.commit()
    db.refresh(a)
    av.invalidar()
    return _out(a)


@router.delete("/{aviso_id}")
def borrar(aviso_id: int, db: Session = Depends(get_db), _: models.User = Depends(require_admin)):
    a = db.get(models.AvisoTomi, aviso_id)
    if not a:
        raise HTTPException(status_code=404, detail="Aviso no encontrado.")
    db.delete(a)
    db.commit()
    av.invalidar()
    return {"ok": True, "id": aviso_id}

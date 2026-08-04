"""Interruptor de la automatización de Tomi — control desde la plataforma.

Endpoints con auth de usuario (JWT admin), a diferencia de `tomi.py` que usa
`X-Tomi-Key` para los tools de n8n. El botón de la plataforma pega acá; el
clasificador lee el mismo flag vía `services.tomi.interruptor`.

  GET  /api/tomi/interruptor/estado   -> {enabled, updated_at, updated_by}
  POST /api/tomi/interruptor/estado   {enabled: bool} -> setea y devuelve estado
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.security import require_admin
from app.services.tomi import interruptor as sw

router = APIRouter(prefix="/api/tomi/interruptor", tags=["tomi-interruptor"])


@router.get("/estado")
def estado(db: Session = Depends(get_db), _: models.User = Depends(require_admin)):
    return sw.get_state(db)


class SetEstadoIn(BaseModel):
    enabled: bool


@router.post("/estado")
def set_estado(
    body: SetEstadoIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_admin),
):
    actor = user.full_name or user.email
    return sw.set_enabled(db, body.enabled, actor)

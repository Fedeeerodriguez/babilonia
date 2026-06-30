"""Higiene de datos en la plataforma (solo admins).

Vincular trámites Allianz huérfanos con su cliente probable:
  GET  /api/higiene/tickets-huerfanos  -> lista con sugerencia de cliente
  POST /api/higiene/vincular           -> confirma el vínculo (escribe en Notion)
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import models
from app.security import require_admin
from app.services.tomi import higiene as hig
from app.services.tomi import notion_client as nc

router = APIRouter(prefix="/api/higiene", tags=["higiene"])


@router.get("/tickets-huerfanos")
def tickets_huerfanos(_: models.User = Depends(require_admin)):
    items = hig.tickets_con_sugerencia()
    con = sum(1 for i in items if i.get("sugerencia"))
    return {"total": len(items), "con_sugerencia": con, "items": items}


class VincularIn(BaseModel):
    ticket_id: str
    cliente_id: str


@router.post("/vincular")
def vincular(body: VincularIn, _: models.User = Depends(require_admin)):
    ok = nc.vincular_ticket_a_cliente(body.ticket_id, body.cliente_id)
    if not ok:
        raise HTTPException(status_code=502, detail="No se pudo vincular en Notion")
    return {"ok": True, "ticket_id": body.ticket_id, "cliente_id": body.cliente_id}

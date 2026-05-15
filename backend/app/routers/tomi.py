"""Endpoints deterministicos para el sub-agente bases_datos de Tomi (n8n).

Estos endpoints reemplazan a los Notion tools del sub-agente bases_datos en n8n.
El AGENTE SOPORTE TOMMY los llama via HTTP Request (sin LLM intermedio que elija
filtros mal).

Auth: header `X-Tomi-Key` con TOMI_INTERNAL_KEY (env).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.tomi import notion_client as nc
from app.services.tomi import memorias as mem
from app.services.tomi import historial as hist

router = APIRouter(prefix="/api/tomi", tags=["tomi"])

INTERNAL_KEY = os.getenv("TOMI_INTERNAL_KEY", "")


def _auth(x_tomi_key: Optional[str]) -> None:
    if not INTERNAL_KEY:
        # Si no esta seteada, dejamos pasar (dev). En prod, configurar.
        return
    if x_tomi_key != INTERNAL_KEY:
        raise HTTPException(status_code=401, detail="invalid key")


# ---------- Schemas ----------

class ClasificarIn(BaseModel):
    email: str = Field(..., description="Email del usuario que escribe")


class ClasificarOut(BaseModel):
    tipo: str
    data: Optional[Dict[str, Any]] = None


class BuscarEmailIn(BaseModel):
    email: str


class EmisionesIn(BaseModel):
    cliente: Optional[str] = None
    poliza: Optional[str] = None


class CobranzasIn(BaseModel):
    poliza: str


class TicketsAllianzIn(BaseModel):
    tramite: Optional[str] = None


class TicketsBabiloniaIn(BaseModel):
    limit: int = 10


class CalendlyIn(BaseModel):
    cliente: Optional[str] = None
    limit: int = 10


# ---------- Endpoints ----------

@router.post("/clasificar", response_model=ClasificarOut)
def clasificar(body: ClasificarIn, x_tomi_key: Optional[str] = Header(default=None)):
    _auth(x_tomi_key)
    return nc.clasificar_usuario_por_email(body.email)


@router.post("/asesor")
def asesor(body: BuscarEmailIn, x_tomi_key: Optional[str] = Header(default=None)):
    _auth(x_tomi_key)
    return {"results": nc.buscar_asesor_por_email(body.email)}


@router.post("/estudiante")
def estudiante(body: BuscarEmailIn, x_tomi_key: Optional[str] = Header(default=None)):
    _auth(x_tomi_key)
    return {"results": nc.buscar_estudiante_por_email(body.email)}


@router.post("/cliente")
def cliente(body: BuscarEmailIn, x_tomi_key: Optional[str] = Header(default=None)):
    _auth(x_tomi_key)
    return {"results": nc.buscar_cliente_por_email(body.email)}


@router.post("/emisiones")
def emisiones(body: EmisionesIn, x_tomi_key: Optional[str] = Header(default=None)):
    _auth(x_tomi_key)
    return {"results": nc.buscar_emisiones(cliente=body.cliente, poliza=body.poliza)}


@router.post("/cobranzas")
def cobranzas(body: CobranzasIn, x_tomi_key: Optional[str] = Header(default=None)):
    _auth(x_tomi_key)
    return {"results": nc.buscar_cobranzas_por_poliza(body.poliza)}


@router.post("/tickets-allianz")
def tickets_allianz(body: TicketsAllianzIn, x_tomi_key: Optional[str] = Header(default=None)):
    _auth(x_tomi_key)
    return {"results": nc.buscar_tickets_allianz(tramite=body.tramite)}


@router.post("/tickets-babilonia")
def tickets_babilonia(body: TicketsBabiloniaIn, x_tomi_key: Optional[str] = Header(default=None)):
    _auth(x_tomi_key)
    return {"results": nc.buscar_tickets_babilonia(limit=body.limit)}


@router.post("/calendly")
def calendly(body: CalendlyIn, x_tomi_key: Optional[str] = Header(default=None)):
    _auth(x_tomi_key)
    return {"results": nc.buscar_eventos_calendly(cliente=body.cliente, limit=body.limit)}


# ---------- Memorias (vector store Supabase) ----------

class MemoriasIn(BaseModel):
    query: str
    categoria: Optional[str] = None
    wa_id: Optional[str] = None
    source: Optional[str] = None
    k: int = 4


@router.post("/memorias")
def memorias(
    body: MemoriasIn,
    db: Session = Depends(get_db),
    x_tomi_key: Optional[str] = Header(default=None),
):
    _auth(x_tomi_key)
    return {"results": mem.buscar_memorias(
        db, query=body.query, categoria=body.categoria,
        wa_id=body.wa_id, source=body.source, k=body.k,
    )}


# ---------- Historial WATI ----------

class HumanoIn(BaseModel):
    wa_id: str
    hours: int = 23


class HistorialIn(BaseModel):
    wa_id: str
    limit: int = 10


@router.post("/humano-reciente")
def humano_reciente(
    body: HumanoIn,
    db: Session = Depends(get_db),
    x_tomi_key: Optional[str] = Header(default=None),
):
    _auth(x_tomi_key)
    return hist.humano_respondio_recientemente(db, wa_id=body.wa_id, hours=body.hours)


@router.post("/historial")
def historial(
    body: HistorialIn,
    db: Session = Depends(get_db),
    x_tomi_key: Optional[str] = Header(default=None),
):
    _auth(x_tomi_key)
    return {"results": hist.ultimos_mensajes(db, wa_id=body.wa_id, limit=body.limit)}


@router.post("/correo-en-historial")
def correo_en_historial(
    body: HistorialIn,
    db: Session = Depends(get_db),
    x_tomi_key: Optional[str] = Header(default=None),
):
    _auth(x_tomi_key)
    email = hist.buscar_correo_en_historial(db, wa_id=body.wa_id, lookback=body.limit)
    return {"email": email}

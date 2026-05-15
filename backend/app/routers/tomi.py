"""Endpoints deterministicos para el sub-agente bases_datos de Tomi (n8n).

Estos endpoints reemplazan a los Notion tools del sub-agente bases_datos en n8n.
El AGENTE SOPORTE TOMMY los llama via HTTP Request (sin LLM intermedio que elija
filtros mal).

Auth: header `X-Tomi-Key` con TOMI_INTERNAL_KEY (env).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.services.tomi import notion_client as nc
from app.services.tomi import bases_datos as bd

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


# ---------- Sub-agente bases_datos orquestado (1 endpoint para todo) ----------

class BasesDatosIn(BaseModel):
    mensaje: str = ""
    wa_id: Optional[str] = None
    emails: Optional[List[str]] = None
    polizas: Optional[List[str]] = None
    clientes: Optional[List[str]] = None
    incluir: Optional[List[str]] = Field(
        default=None,
        description="Subset de: usuarios|emisiones|cobranzas|tickets_allianz|calendly. Si null, se infiere del mensaje.",
    )


@router.post("/bases-datos")
def bases_datos(body: BasesDatosIn, x_tomi_key: Optional[str] = Header(default=None)):
    _auth(x_tomi_key)
    return bd.consultar(
        mensaje=body.mensaje,
        emails=body.emails,
        polizas=body.polizas,
        clientes=body.clientes,
        incluir=body.incluir,
    )


# ---------- Debug: ver schema de una DB Notion ----------

@router.get("/debug/schema/{db_name}")
def debug_schema(db_name: str, x_tomi_key: Optional[str] = Header(default=None)):
    """Devuelve {property_name: type} de la DB indicada + 1 page de ejemplo aplanada."""
    _auth(x_tomi_key)
    db_map = {
        "asesores": nc.DB_ASESORES,
        "estudiantes": nc.DB_ESTUDIANTES,
        "clientes": nc.DB_CLIENTES,
        "emisiones": nc.DB_EMISIONES,
        "cobranzas": nc.DB_COBRANZAS,
        "tickets_allianz": nc.DB_TICKETS_ALLIANZ,
        "tickets_babilonia": nc.DB_TICKETS_BABILONIA,
        "calendly": nc.DB_EVENTOS_CALENDLY,
    }
    db_id = db_map.get(db_name)
    if not db_id:
        raise HTTPException(404, f"db {db_name} no encontrada. Opciones: {list(db_map.keys())}")
    try:
        client = nc._client()
        meta = client.databases.retrieve(database_id=db_id)
        props = {k: v.get("type") for k, v in (meta.get("properties") or {}).items()}
        sample = client.databases.query(database_id=db_id, page_size=1)
        ejemplo = nc._flatten_props(sample["results"][0]) if sample.get("results") else None
        return {"db_id": db_id, "properties": props, "ejemplo": ejemplo}
    except Exception as e:
        raise HTTPException(500, f"error: {e}")

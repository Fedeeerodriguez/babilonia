"""Endpoints deterministicos para el sub-agente bases_datos de Tomi (n8n).

Estos endpoints reemplazan a los Notion tools del sub-agente bases_datos en n8n.
El AGENTE SOPORTE TOMMY los llama via HTTP Request (sin LLM intermedio que elija
filtros mal).

Auth: header `X-Tomi-Key` con TOMI_INTERNAL_KEY (env).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

log = logging.getLogger("tomi.api")


class TomiSafeRoute(APIRoute):
    """Route class para los endpoints del bot: si la lógica tira una excepción
    inesperada (Notion caído, OpenAI, DB), devuelve 200 con un envelope de error
    en vez de 500. Así Tomi (n8n) siempre recibe una respuesta procesable y puede
    decirle algo al usuario en lugar de romperse.

    Las HTTPException (401/400/404) y errores de validación (422) se respetan.
    """

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except (HTTPException, RequestValidationError):
                raise
            except Exception as e:  # noqa: BLE001
                log.exception("Endpoint Tomi %s falló: %s", request.url.path, e)
                return JSONResponse(
                    status_code=200,
                    content={
                        "results": [],
                        "error": "servicio temporalmente no disponible, reintentá en unos segundos",
                        "detail": str(e),
                    },
                )

        return handler

from datetime import datetime, timezone

from app import models
from app.database import get_db, get_docs_db
from app.services.tomi import notion_client as nc
from app.services.tomi import bases_datos as bd
from app.services.tomi import agente as ag
from app.services.tomi import memorias as mem
from app.services.tomi import memorias_bd as mbd
from app.services.tomi import agente_memorias as ag_mem
from app.services.tomi import clasificador as clasif
from app.services.tomi import notion_scanner as nscan
from app.services.tomi.cache import notion_cache

router = APIRouter(prefix="/api/tomi", tags=["tomi"], route_class=TomiSafeRoute)

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


class DiasAtrasoIn(BaseModel):
    poliza: Optional[str] = Field(None, description="Número de póliza exacto, si se conoce")
    email_cliente: Optional[str] = Field(None, description="Email del cliente")
    cliente: Optional[str] = Field(None, description="Nombre del cliente (búsqueda parcial)")


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


class ClasificarUsuarioIn(BaseModel):
    user_id: Optional[str] = Field(None, description="chat_id de Telegram / wa_id de WhatsApp")
    mensaje_usuario: Optional[str] = Field(None, description="Texto del usuario; de aquí se extrae el email")
    email: Optional[str] = Field(None, description="Email explícito; si viene, no se parsea el mensaje")
    user_nombre: Optional[str] = None
    force: bool = Field(False, description="True para ignorar caché y reconsultar Notion")

    @field_validator("user_id", "user_nombre", mode="before")
    @classmethod
    def _coerce_to_str(cls, v):
        # n8n suele mandar el chat.id como número; lo aceptamos y lo pasamos a string.
        if v is None:
            return v
        return str(v)


@router.post("/clasificar-usuario")
def clasificar_usuario(
    body: ClasificarUsuarioIn,
    x_tomi_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """Clasifica al usuario (asesor/estudiante/cliente/prospecto) usando Notion +
    caché persistente en Supabase. Reemplaza al AI Agent2 de n8n.

    Respuesta:
        {
          "comando_1": "registrado" | "no registrado",
          "comando_2": "asesor" | "estudiante" | "cliente" | "prospecto",
          "email": "...",
          "user_id": "...",
          "user_nombre": "...",
          "fuente": "cache" | "cache_email" | "notion" | "sin_email"
        }
    """
    _auth(x_tomi_key)
    return clasif.clasificar(
        db,
        user_id=body.user_id,
        mensaje_usuario=body.mensaje_usuario,
        email=body.email,
        user_nombre=body.user_nombre,
        force=body.force,
    )


@router.get("/clasificar-usuario/{user_id}")
def obtener_clasificacion(
    user_id: str,
    x_tomi_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """Lookup directo a la caché. 404 si no está clasificado todavía."""
    _auth(x_tomi_key)
    cached = clasif.buscar_cache(db, user_id=user_id, email=None)
    if not cached:
        raise HTTPException(status_code=404, detail="no clasificado")
    return cached


@router.delete("/clasificar-usuario/{user_id}")
def borrar_clasificacion(
    user_id: str,
    x_tomi_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """Borra la fila de caché para que el próximo /clasificar-usuario reconsulte Notion."""
    _auth(x_tomi_key)
    from sqlalchemy import text as _text
    db.execute(_text("DELETE FROM tomi_clasificaciones WHERE user_id = :uid"), {"uid": user_id})
    db.commit()
    return {"deleted": user_id}


@router.get("/admin/tickets-huerfanos")
def tickets_huerfanos(x_tomi_key: Optional[str] = Header(default=None)):
    """Trámites Allianz SIN cliente vinculado (relación 'Clientes General' vacía).

    Métrica de higiene de datos: estos huérfanos son la causa #1 de que Tomi
    'no encuentre' trámites que sí existen. Devuelve total + lista para exportar.
    Llamar periódicamente para medir el avance del equipo al vincularlos.
    """
    _auth(x_tomi_key)
    rows = nc.tickets_allianz_sin_cliente()
    tramites = []
    for t in rows:
        ases = t.get("Asesores ") or t.get("Asesor")
        tramites.append({
            "tramite": t.get("Nombre del Trámite"),
            "tipo": t.get("Tipo de Trámite"),
            "estado": t.get("Estado"),
            "fecha_solicitud": (t.get("Fecha de Solicitud") or {}).get("start")
                if isinstance(t.get("Fecha de Solicitud"), dict) else t.get("Fecha de Solicitud"),
            "ticket_num": t.get("Ticket Allianz"),
            "tiene_asesor": bool(ases),
            "url": t.get("_url"),
        })
    sin_asesor = sum(1 for x in tramites if not x["tiene_asesor"])
    return {
        "total": len(tramites),
        "sin_asesor_tambien": sin_asesor,
        "tramites": tramites,
    }


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


@router.post("/dias-atraso")
def dias_atraso(body: DiasAtrasoIn, x_tomi_key: Optional[str] = Header(default=None)):
    """Cuántos días de atraso (y monto faltante) tiene un cliente o póliza."""
    _auth(x_tomi_key)
    if not (body.poliza or body.email_cliente or body.cliente):
        raise HTTPException(status_code=400, detail="Requiere poliza, email_cliente o cliente")
    return nc.dias_de_atraso(
        poliza=body.poliza,
        email_cliente=body.email_cliente,
        cliente=body.cliente,
    )


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
    clientes: Optional[List[str]] = Field(default=None, description="Nombres de clientes (no emails)")
    asesores: Optional[List[str]] = Field(default=None, description="Nombres de asesores")
    incluir: Optional[List[str]] = Field(
        default=None,
        description=("Subset de: usuarios|emisiones|cobranzas|tickets_allianz|calendly|"
                     "clientes_por_nombre|asesores_por_nombre. Si null, se infiere del modo."),
    )
    # Modos y filtros
    modo: str = Field(
        default="completo",
        description="perfil|polizas|clientes|cobranzas|eventos|completo|cartera",
    )
    email_asesor: Optional[str] = None
    email_cliente: Optional[str] = None
    solo_activas: bool = False
    limite: int = 100
    filtro_estado: Optional[str] = Field(default=None, description="(modo cartera) activos|en_proceso|perdidos")


@router.post("/bases-datos")
def bases_datos(body: BasesDatosIn, x_tomi_key: Optional[str] = Header(default=None)):
    _auth(x_tomi_key)
    return bd.consultar(
        mensaje=body.mensaje,
        emails=body.emails,
        polizas=body.polizas,
        clientes=body.clientes,
        asesores=body.asesores,
        incluir=body.incluir,
        modo=body.modo,
        email_asesor=body.email_asesor,
        email_cliente=body.email_cliente,
        solo_activas=body.solo_activas,
        limite=body.limite,
        filtro_estado=body.filtro_estado,
    )


# ---------- Agente LLM (tool calling sobre bases_datos) ----------

class HistMsg(BaseModel):
    role: str
    content: str


class AgenteIn(BaseModel):
    mensaje: str
    historial: Optional[List[HistMsg]] = None
    wa_id: Optional[str] = None
    max_iter: int = 5


@router.post("/agente")
def agente_llm(body: AgenteIn, x_tomi_key: Optional[str] = Header(default=None)):
    _auth(x_tomi_key)
    hist = [{"role": h.role, "content": h.content} for h in (body.historial or [])]
    return ag.responder(
        mensaje=body.mensaje,
        historial=hist,
        wa_id=body.wa_id,
        max_iter=body.max_iter,
    )


# ---------- Memorias técnicas (sub-agente vector store) ----------

class MemoriasIn(BaseModel):
    query: str
    categoria: Optional[str] = Field(default=None, description="plu3|patrimonial|proteccion|auto|educacion")
    k: int = 5


@router.post("/memorias")
def memorias_directa(
    body: MemoriasIn,
    db: Session = Depends(get_docs_db),
    x_tomi_key: Optional[str] = Header(default=None),
):
    """Búsqueda directa en pgvector (sin LLM intermedio). Para tests rápidos."""
    _auth(x_tomi_key)
    return mbd.consultar(db, query=body.query, categoria=body.categoria, k=body.k)


class MemoriasAgenteIn(BaseModel):
    mensaje: str
    historial: Optional[List[HistMsg]] = None
    max_iter: int = 4


@router.post("/memorias-agente")
def memorias_agente_llm(
    body: MemoriasAgenteIn,
    db: Session = Depends(get_docs_db),
    x_tomi_key: Optional[str] = Header(default=None),
):
    """Agente LLM que elige categoría y delega en memorias_bd. Devuelve informe verbatim."""
    _auth(x_tomi_key)
    hist = [{"role": h.role, "content": h.content} for h in (body.historial or [])]
    return ag_mem.responder(db, mensaje=body.mensaje, historial=hist, max_iter=body.max_iter)


@router.get("/memorias/categorias")
def memorias_categorias(
    db: Session = Depends(get_docs_db),
    x_tomi_key: Optional[str] = Header(default=None),
):
    """Cuántos chunks hay por categoría en Supabase."""
    _auth(x_tomi_key)
    return {"categorias": mem.listar_categorias_con_datos(db)}


@router.get("/memorias/debug")
def memorias_debug(
    db: Session = Depends(get_docs_db),
    x_tomi_key: Optional[str] = Header(default=None),
):
    """Debug: cuenta total de filas en `documents` y sample de las primeras 5."""
    _auth(x_tomi_key)
    from sqlalchemy import text
    from app.services.tomi.memorias import DOCUMENTS_TABLE
    try:
        total = db.execute(text(f"SELECT COUNT(*) AS n FROM {DOCUMENTS_TABLE}")).scalar()
        samples = db.execute(text(f"SELECT id, content, metadata FROM {DOCUMENTS_TABLE} LIMIT 5")).mappings().all()
        sample_list = []
        for r in samples:
            md = r["metadata"]
            if isinstance(md, str):
                import json as _j
                try:
                    md = _j.loads(md)
                except Exception:
                    md = {"_raw": md[:200]}
            sample_list.append({
                "id": str(r["id"]),
                "content_preview": (r["content"] or "")[:200],
                "metadata": md,
                "metadata_keys": list(md.keys()) if isinstance(md, dict) else None,
            })
        return {"total_rows": total, "sample": sample_list}
    except Exception as e:
        return {"error": str(e)}


@router.get("/memorias/tablas")
def memorias_listar_tablas(
    db: Session = Depends(get_docs_db),
    x_tomi_key: Optional[str] = Header(default=None),
):
    """Lista las tablas disponibles en el schema public de la DB conectada.
    Útil para detectar el nombre real de la tabla de vectores."""
    _auth(x_tomi_key)
    from sqlalchemy import text
    try:
        rows = db.execute(text("""
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY table_schema, table_name
        """)).mappings().all()
        return {"tablas": [{"schema": r["table_schema"], "table": r["table_name"]} for r in rows]}
    except Exception as e:
        return {"error": str(e)}


# ---------- Cache management ----------

@router.get("/cache/stats")
def cache_stats(x_tomi_key: Optional[str] = Header(default=None)):
    _auth(x_tomi_key)
    return {"cache": notion_cache.stats(), "notion_circuit": nc.notion_breaker.state()}


@router.post("/cache/clear")
def cache_clear(x_tomi_key: Optional[str] = Header(default=None)):
    _auth(x_tomi_key)
    notion_cache.clear()
    return {"cleared": True}


# ---------- Dead-letter: disparos de Tomi que fallaron (trigger 23h) ----------

class DispatchFailedIn(BaseModel):
    wa_id: str
    sender_name: Optional[str] = None
    last_user_message: Optional[str] = None
    reason: Optional[str] = None


@router.post("/dispatch-failed")
def dispatch_failed(
    body: DispatchFailedIn,
    db: Session = Depends(get_db),
    x_tomi_key: Optional[str] = Header(default=None),
):
    """n8n llama acá cuando un disparo del trigger 23h falla definitivamente.
    Hace upsert por wa_id sin resolver: incrementa intentos en vez de duplicar."""
    _auth(x_tomi_key)
    existing = (
        db.query(models.FailedDispatch)
        .filter(models.FailedDispatch.wa_id == body.wa_id,
                models.FailedDispatch.resolved == False)  # noqa: E712
        .order_by(models.FailedDispatch.created_at.desc())
        .first()
    )
    now = datetime.now(timezone.utc)
    if existing:
        existing.attempts = (existing.attempts or 1) + 1
        existing.reason = body.reason
        existing.last_attempt_at = now
        existing.last_user_message = body.last_user_message or existing.last_user_message
    else:
        existing = models.FailedDispatch(
            wa_id=body.wa_id,
            sender_name=body.sender_name,
            last_user_message=body.last_user_message,
            reason=body.reason,
            attempts=1,
            last_attempt_at=now,
        )
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return {"id": existing.id, "wa_id": existing.wa_id, "attempts": existing.attempts}


@router.get("/dispatch-failed")
def list_dispatch_failed(
    include_resolved: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db),
    x_tomi_key: Optional[str] = Header(default=None),
):
    """Lista los disparos fallidos pendientes (para seguimiento humano)."""
    _auth(x_tomi_key)
    q = db.query(models.FailedDispatch)
    if not include_resolved:
        q = q.filter(models.FailedDispatch.resolved == False)  # noqa: E712
    rows = q.order_by(models.FailedDispatch.last_attempt_at.desc()).limit(min(limit, 200)).all()
    return {
        "count": len(rows),
        "items": [
            {
                "id": r.id, "wa_id": r.wa_id, "sender_name": r.sender_name,
                "last_user_message": r.last_user_message, "reason": r.reason,
                "attempts": r.attempts, "resolved": r.resolved,
                "last_attempt_at": r.last_attempt_at.isoformat() if r.last_attempt_at else None,
            }
            for r in rows
        ],
    }


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
        # sub-DBs de clientes
        "clientes_auto": nc.DB_CLIENTES_AUTO,
        "clientes_patrimonial": nc.DB_CLIENTES_PATRIMONIAL,
        "clientes_educacional": nc.DB_CLIENTES_EDUCACIONAL,
        "clientes_gmm": nc.DB_CLIENTES_GMM,
        "clientes_rentas_privadas": nc.DB_CLIENTES_RENTAS_PRIVADAS,
        "clientes_residencial": nc.DB_CLIENTES_RESIDENCIAL,
        "clientes_proteccion": nc.DB_CLIENTES_PROTECCION,
        "clientes_elite": nc.DB_CLIENTES_ELITE,
        "clientes_plu3": nc.DB_CLIENTES_PLU3,
        "migracion_clientes": nc.DB_MIGRACION_CLIENTES,
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


# ──────────────── Notion Scanner & Allowlist ────────────────

class AllowlistItemIn(BaseModel):
    db_id: str
    slug: Optional[str] = None
    title: Optional[str] = None
    enabled: bool = True
    descripcion: Optional[str] = None


class AllowlistBulkIn(BaseModel):
    items: List[AllowlistItemIn]


class QueryDbIn(BaseModel):
    slug_or_id: str
    filtros: Optional[Dict[str, Any]] = None
    limit: int = 20


class SearchIn(BaseModel):
    query: str
    limit: int = 10


@router.get("/notion/relaciones-conocidas")
def notion_relaciones_conocidas(
    x_tomi_key: Optional[str] = Header(default=None),
):
    """Mapa de qué DBs están enganchadas (vía columnas `relation`) a las DBs
    que Tomi YA tiene mapeadas (NOTION_DB_*).

    Devuelve `tablas` con cada DB conocida y sus relaciones, y `descubiertas`
    con las DBs nuevas que aparecen referenciadas y aún no están integradas.
    """
    _auth(x_tomi_key)
    try:
        return nscan.mapear_relaciones_conocidas()
    except Exception as e:
        raise HTTPException(500, f"error: {e}")


@router.get("/notion/discover")
def notion_discover(
    persistir: bool = False,
    x_tomi_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """Lista TODAS las DBs que la integración Notion de Tomi tiene compartidas.

    Si persistir=true, vuelca cada DB en `tomi_notion_allowlist` con enabled=false
    para que después marques cuáles habilitar.
    """
    _auth(x_tomi_key)
    try:
        dbs = nscan.discover_databases()
    except Exception as e:
        raise HTTPException(500, f"error Notion search: {e}")

    if persistir:
        existing = {r["db_id"]: r for r in nscan.listar_allowlist(db)}
        for d in dbs:
            prev = existing.get(d["id"])
            nscan.upsert_allowlist(
                db,
                db_id=d["id"],
                slug=d["slug"],
                title=d["title"],
                enabled=bool(prev["enabled"]) if prev else False,
                descripcion=(prev or {}).get("descripcion"),
                schema=d["schema"],
            )
    return {"total": len(dbs), "databases": dbs}


@router.get("/notion/allowlist")
def notion_allowlist_list(
    x_tomi_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    _auth(x_tomi_key)
    return {"items": nscan.listar_allowlist(db)}


@router.post("/notion/allowlist")
def notion_allowlist_upsert(
    body: AllowlistBulkIn,
    x_tomi_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    _auth(x_tomi_key)
    for it in body.items:
        nscan.upsert_allowlist(
            db,
            db_id=it.db_id,
            slug=it.slug or nscan._slugify(it.title or it.db_id),
            title=it.title or it.db_id,
            enabled=it.enabled,
            descripcion=it.descripcion,
        )
    return {"updated": len(body.items)}


@router.post("/notion/query")
def notion_query(
    body: QueryDbIn,
    x_tomi_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """Query genérico sobre una DB habilitada en la allowlist."""
    _auth(x_tomi_key)
    try:
        return nscan.query_db_filtered(db, body.slug_or_id, body.filtros, body.limit)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except Exception as e:
        raise HTTPException(500, f"error query: {e}")


@router.get("/notion/pagina/{page_id}")
def notion_pagina(
    page_id: str,
    x_tomi_key: Optional[str] = Header(default=None),
):
    """Lee el contenido completo de una página de Notion en markdown."""
    _auth(x_tomi_key)
    try:
        return nscan.get_page_content(page_id)
    except Exception as e:
        raise HTTPException(500, f"error lectura: {e}")


@router.post("/notion/search")
def notion_search(
    body: SearchIn,
    x_tomi_key: Optional[str] = Header(default=None),
):
    """Búsqueda global tipo Cmd+K en todo Notion (lo que ve la integración)."""
    _auth(x_tomi_key)
    try:
        return {"results": nscan.search_notion(body.query, body.limit)}
    except Exception as e:
        raise HTTPException(500, f"error search: {e}")


# ──────────── Endpoints curados: 10 DBs Allianz adicionales ────────────

class RenovacionesIn(BaseModel):
    poliza: Optional[str] = None
    email_asesor: Optional[str] = None
    estado: Optional[str] = Field(None, description="Not started | In progress | Done")
    limit: int = 20


class SiniestrosIn(BaseModel):
    poliza: Optional[str] = None
    email_asesor: Optional[str] = None
    estado: Optional[str] = Field(None, description="Por iniciar | En progreso | Terminado")
    limit: int = 20


class ComisionesIn(BaseModel):
    poliza: Optional[str] = None
    tipo_pago: Optional[str] = Field(None, description="Comisión Regular | ChargeBack | Bono | Mes 13 PLU3 | Ajuste")
    concepto: Optional[str] = None
    desde: Optional[str] = Field(None, description="YYYY-MM-DD")
    hasta: Optional[str] = Field(None, description="YYYY-MM-DD")
    limit: int = 30


class BonosAgentesIn(BaseModel):
    clave_agente: Optional[str] = None
    limit: int = 20


class BonosPromotoriaIn(BaseModel):
    nombre: Optional[str] = None
    limit: int = 20


class Mes13In(BaseModel):
    cliente: Optional[str] = None
    limit: int = 30


class PuntosConvencionIn(BaseModel):
    clave_agente: Optional[str] = None
    limit: int = 20


class ProductosIn(BaseModel):
    nombre: Optional[str] = None
    tipo_producto: Optional[str] = None
    id_allianz: Optional[str] = None
    limit: int = 20


class ClientesPPRIn(BaseModel):
    email_cliente: Optional[str] = None
    email_asesor: Optional[str] = None
    poliza: Optional[str] = None
    estado: Optional[str] = None
    producto: Optional[str] = Field(None, description="Optimaxx Plus | Seguro Médico")
    limit: int = 30


class MigracionCarteraIn(BaseModel):
    emision: Optional[str] = None
    migrado: Optional[bool] = None
    limit: int = 30


@router.post("/renovaciones")
def renovaciones(body: RenovacionesIn, x_tomi_key: Optional[str] = Header(default=None)):
    """Renovaciones de pólizas. Filtros: póliza, asesor (email), estado."""
    _auth(x_tomi_key)
    return {"results": nc.buscar_renovaciones(
        poliza=body.poliza, email_asesor=body.email_asesor,
        estado=body.estado, limit=body.limit,
    )}


@router.post("/siniestros")
def siniestros(body: SiniestrosIn, x_tomi_key: Optional[str] = Header(default=None)):
    """Siniestros / reclamos en curso."""
    _auth(x_tomi_key)
    return {"results": nc.buscar_siniestros(
        poliza=body.poliza, email_asesor=body.email_asesor,
        estado=body.estado, limit=body.limit,
    )}


@router.post("/comisiones")
def comisiones(body: ComisionesIn, x_tomi_key: Optional[str] = Header(default=None)):
    """Comisiones de agentes por póliza y/o tipo de pago. Ordenado por fecha desc."""
    _auth(x_tomi_key)
    return {"results": nc.buscar_comisiones(
        poliza=body.poliza, tipo_pago=body.tipo_pago, concepto=body.concepto,
        desde=body.desde, hasta=body.hasta, limit=body.limit,
    )}


@router.post("/bonos-agentes")
def bonos_agentes(body: BonosAgentesIn, x_tomi_key: Optional[str] = Header(default=None)):
    """Bonos Allianz para agentes individuales."""
    _auth(x_tomi_key)
    return {"results": nc.buscar_bonos_agentes(clave_agente=body.clave_agente, limit=body.limit)}


@router.post("/bonos-promotoria")
def bonos_promotoria(body: BonosPromotoriaIn, x_tomi_key: Optional[str] = Header(default=None)):
    """Bonos Allianz Promotoría (equipo)."""
    _auth(x_tomi_key)
    return {"results": nc.buscar_bonos_promotoria(nombre=body.nombre, limit=body.limit)}


@router.post("/mes-13-plu3")
def mes_13_plu3(body: Mes13In, x_tomi_key: Optional[str] = Header(default=None)):
    """Comisión recurrente Mes 13 PLU3 por cliente."""
    _auth(x_tomi_key)
    return {"results": nc.buscar_mes_13_plu3(cliente=body.cliente, limit=body.limit)}


@router.post("/puntos-convencion")
def puntos_convencion(body: PuntosConvencionIn, x_tomi_key: Optional[str] = Header(default=None)):
    """Puntos Convención por clave de agente."""
    _auth(x_tomi_key)
    return {"results": nc.buscar_puntos_convencion(clave_agente=body.clave_agente, limit=body.limit)}


@router.post("/productos")
def productos(body: ProductosIn, x_tomi_key: Optional[str] = Header(default=None)):
    """Catálogo de productos (Allianz + cursos)."""
    _auth(x_tomi_key)
    return {"results": nc.buscar_productos(
        nombre=body.nombre, tipo_producto=body.tipo_producto,
        id_allianz=body.id_allianz, limit=body.limit,
    )}


@router.post("/clientes-ppr")
def clientes_ppr(body: ClientesPPRIn, x_tomi_key: Optional[str] = Header(default=None)):
    """Clientes PPR Allianz (cartera principal PLU3)."""
    _auth(x_tomi_key)
    return {"results": nc.buscar_clientes_ppr(
        email_cliente=body.email_cliente, email_asesor=body.email_asesor,
        poliza=body.poliza, estado=body.estado, producto=body.producto,
        limit=body.limit,
    )}


@router.post("/migracion-cartera")
def migracion_cartera(body: MigracionCarteraIn, x_tomi_key: Optional[str] = Header(default=None)):
    """Migración de Cartera entre asesores."""
    _auth(x_tomi_key)
    return {"results": nc.buscar_migracion_cartera(
        emision=body.emision, migrado=body.migrado, limit=body.limit,
    )}

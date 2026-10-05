"""Avisos al asesor y al centinela cuando un prospecto cancela o reagenda su cita.

Contexto de negocio: el asesor L1 no da citas solo; la cita la da el CENTINELA, que es
quien entra a la reunión (en la base de Notion figura como "Cerrador"). Si el prospecto
cancela o quiere cambiar, el contacto tiene que ser DIRECTO entre el prospecto, el asesor
y el centinela, sin pasar por Ceci ni Jime.

Fuente: base Notion "Eventos Calendly". Una automatización externa (Calendly → Notion)
marca `Estado` = Cancelada / Reagendada. Tomi vigila esa base y avisa por WhatsApp
(plantilla de WATI) al asesor y, si existe, al centinela, con los datos del prospecto.

Dos disparadores:
  1. `escanear()`              — vigilante periódico (cambios de estado en Notion).
  2. `avisar_por_whatsapp()`   — cuando el prospecto le escribe a Tommy que no puede ir.

Seguridad / operación (variables de entorno):
  AVISOS_CITAS_ACTIVO=0           el vigilante no corre (default)
  AVISOS_CITAS_DRY_RUN=1          registra el mensaje pero NO lo envía (default)
  AVISOS_CITAS_INTERVALO_MIN=10   cada cuántos minutos revisa Notion
  AVISOS_CITAS_VENTANA_HORAS=6    solo eventos modificados en las últimas N horas
  WATI_PLANTILLA_CITA=aviso_cita_prospecto
Dedup: tabla `tomi_avisos_citas` (clave única evento+motivo+rol). Cada aviso se reserva
antes de enviarse, así varios workers no lo duplican. Un error se reintenta hasta 3 veces.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.services.tomi import notion_client as nc
from app.services.tomi import wati

log = logging.getLogger("tomi.avisos_citas")

ESTADOS_AVISO = ("Cancelada", "Reagendada")

# CONTRATO con la plantilla de WATI `aviso_cita_prospecto`: estos nombres tienen que ser
# IDÉNTICOS a las variables {{...}} de la plantilla (y de docs/AVISOS_CITAS.md). Si se cambia
# uno, cambiarlo en los tres lugares — el test test_contrato_plantilla lo verifica.
VARIABLES_PLANTILLA = ("name", "prospecto", "accion", "fecha_cita", "detalle", "telefono_prospecto", "correo_prospecto")

EJEMPLO_PLANTILLA = {
    "name": "Kevin", "prospecto": "Monica Ake (PRUEBA)", "accion": "canceló",
    "fecha_cita": "mar 06/10 10:00 h",
    "detalle": "Link para reagendar: https://calendly.com/reschedulings/ejemplo",
    "telefono_prospecto": "+52 999 123 4567", "correo_prospecto": "prospecto@ejemplo.com",
}
MAX_INTENTOS = 3
_DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


def _flag(nombre: str, default: str) -> bool:
    return os.getenv(nombre, default).strip().lower() in ("1", "true", "si", "sí", "yes")


def activo() -> bool:
    return _flag("AVISOS_CITAS_ACTIVO", "0")


def dry_run() -> bool:
    return _flag("AVISOS_CITAS_DRY_RUN", "1")


def _plantilla() -> str:
    return os.getenv("WATI_PLANTILLA_CITA", "aviso_cita_prospecto")


# ------------------------------------------------------------------ helpers de datos
def _uno(v: Any) -> str:
    """Rollups pueden venir como escalar o lista → primer valor no vacío, como texto."""
    if isinstance(v, list):
        v = next((x for x in v if x not in (None, "")), None)
    return str(v).strip() if v not in (None, "") else ""


def _fecha(ev: Dict[str, Any]) -> Optional[datetime]:
    d = ev.get("Fecha de Evento") or {}
    s = d.get("start") if isinstance(d, dict) else d
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def fecha_legible(dt: Optional[datetime]) -> str:
    """'lun 06/10 10:00 h' en la hora local del evento (la que trae Calendly)."""
    if not dt:
        return "fecha sin dato"
    return f"{_DIAS[dt.weekday()]} {dt:%d/%m %H:%M} h"


def _query_todo(filtro: Dict[str, Any], orden: Optional[List[Dict[str, Any]]] = None,
                max_paginas: int = 5) -> List[Dict[str, Any]]:
    """Consulta 'Eventos Calendly' SIN caché (el vigilante necesita datos frescos)."""
    if not nc.DB_EVENTOS_CALENDLY:
        return []
    out: List[Dict[str, Any]] = []
    cursor = None
    for _ in range(max_paginas):
        kw: Dict[str, Any] = {"database_id": nc.DB_EVENTOS_CALENDLY, "page_size": 100, "filter": filtro}
        if orden:
            kw["sorts"] = orden
        if cursor:
            kw["start_cursor"] = cursor
        resp = nc._retry_429(nc._client().databases.query, **kw)
        for p in resp.get("results", []):
            fp = nc._flatten_props(p)
            fp["_last_edited"] = p.get("last_edited_time")
            out.append(fp)
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return out


def eventos_cambiados(ventana_horas: float) -> List[Dict[str, Any]]:
    desde = (datetime.now(timezone.utc) - timedelta(hours=ventana_horas)).isoformat()
    filtro = {"and": [
        {"or": [{"property": "Estado", "select": {"equals": e}} for e in ESTADOS_AVISO]},
        {"timestamp": "last_edited_time", "last_edited_time": {"on_or_after": desde}},
    ]}
    return _query_todo(filtro)


def nueva_cita(correo: str, evento_id: str) -> Optional[str]:
    """Para una cita Reagendada: la próxima cita Activa del mismo invitado (si ya existe)."""
    if not correo:
        return None
    hoy = datetime.now(timezone.utc).date().isoformat()
    filtro = {"and": [
        {"property": "Correo invitado", "rich_text": {"equals": correo}},
        {"property": "Estado", "select": {"equals": "Activo"}},
        {"property": "Fecha de Evento", "date": {"on_or_after": hoy}},
    ]}
    evs = [e for e in _query_todo(filtro, max_paginas=1) if e.get("_id") != evento_id]
    evs = [(f, e) for e in evs if (f := _fecha(e))]
    if not evs:
        return None
    return fecha_legible(min(evs, key=lambda x: x[0])[0])


def destinatarios(ev: Dict[str, Any]) -> List[Dict[str, str]]:
    """Asesor siempre; centinela (= "Cerrador", quien entra a la reunión) si existe."""
    out = [{"rol": "asesor", "nombre": _uno(ev.get("Nombre de Asesor")),
            "numero": wati.numero_whatsapp(_uno(ev.get("Teléfono Asesor"))) or ""}]
    centinela = _uno(ev.get("Nombre de Cerrador"))
    num_c = wati.numero_whatsapp(_uno(ev.get("Teléfono Cerrador"))) or ""
    if centinela or num_c:
        if not (num_c and num_c == out[0]["numero"]):     # misma persona → un solo aviso
            out.append({"rol": "centinela", "nombre": centinela, "numero": num_c})
    return out


def parametros(dest: Dict[str, str], ev: Dict[str, Any], accion: str, detalle: str) -> Dict[str, str]:
    """Variables de la plantilla WATI `aviso_cita_prospecto` (ver VARIABLES_PLANTILLA)."""
    p = {
        "name": (dest.get("nombre") or "").split(" ")[0] or "equipo",
        "prospecto": _uno(ev.get("Nombre del invitado")) or "Un prospecto",
        "accion": accion,
        "fecha_cita": fecha_legible(_fecha(ev)),
        "detalle": detalle,
        "telefono_prospecto": _uno(ev.get("Teléfono")) or "sin teléfono",
        "correo_prospecto": _uno(ev.get("Correo invitado")) or "sin correo",
    }
    return {k: p[k] for k in VARIABLES_PLANTILLA}


def enviar_prueba(numero: str) -> Dict[str, Any]:
    """Manda la plantilla REAL con datos de ejemplo a un número (p. ej. el tuyo) para
    verificar que cada variable cae en su lugar. Ignora DRY_RUN a propósito."""
    num = wati.numero_whatsapp(numero)
    if not num:
        return {"ok": False, "detalle": "número inválido"}
    r = wati.enviar_plantilla(num, _plantilla(), dict(EJEMPLO_PLANTILLA), broadcast="avisos_citas_prueba")
    return {**r, "numero": num, "plantilla": _plantilla(), "variables": dict(EJEMPLO_PLANTILLA)}


# ------------------------------------------------------------------ envío con dedup
def _reservar(db: Session, ev_id: str, motivo: str, dest: Dict[str, str], ev: Dict[str, Any]
              ) -> Optional[models.AvisoCita]:
    """Reserva el aviso (insert con clave única). None si otro worker ya lo tiene o ya se hizo.
    Un aviso en 'error' con menos de MAX_INTENTOS se vuelve a reservar de forma atómica."""
    fila = models.AvisoCita(
        evento_id=ev_id, motivo=motivo, rol=dest["rol"], destinatario=dest.get("nombre"),
        numero=dest.get("numero"), prospecto=_uno(ev.get("Nombre del invitado")),
        fecha_cita=fecha_legible(_fecha(ev)), estado="reservado", intentos=0)
    db.add(fila)
    try:
        db.commit()
        return fila
    except IntegrityError:
        db.rollback()
    existente = (db.query(models.AvisoCita)
                 .filter_by(evento_id=ev_id, motivo=motivo, rol=dest["rol"]).first())
    if not existente or existente.estado != "error" or (existente.intentos or 0) >= MAX_INTENTOS:
        return None
    res = db.execute(update(models.AvisoCita)
                     .where(models.AvisoCita.id == existente.id, models.AvisoCita.estado == "error")
                     .values(estado="reservado"))
    db.commit()
    return existente if res.rowcount == 1 else None


def _enviar(db: Session, fila: models.AvisoCita, params: Dict[str, str], simular: bool) -> str:
    fila.mensaje = " | ".join(f"{k}={v}" for k, v in params.items())
    fila.intentos = (fila.intentos or 0) + 1
    if not fila.numero:
        fila.estado, fila.resultado = "sin_numero", "el destinatario no tiene teléfono en Notion"
    elif simular:
        fila.estado, fila.resultado = "simulado", "DRY_RUN: no se envió"
    else:
        r = wati.enviar_plantilla(fila.numero, _plantilla(), params, broadcast="avisos_citas")
        fila.estado = "enviado" if r["ok"] else "error"
        fila.resultado = str(r.get("detalle"))[:1000]
    db.commit()
    return fila.estado


def _avisar_evento(db: Session, ev: Dict[str, Any], motivo: str, accion: str, detalle: str,
                   simular: bool) -> List[Dict[str, str]]:
    hechos = []
    for dest in destinatarios(ev):
        fila = _reservar(db, ev["_id"], motivo, dest, ev)
        if fila is None:
            continue
        estado = _enviar(db, fila, parametros(dest, ev, accion, detalle), simular)
        hechos.append({"rol": dest["rol"], "nombre": dest.get("nombre", ""), "estado": estado})
    return hechos


# ------------------------------------------------------------------ disparador 1: vigilante
def escanear(db: Session, ventana_horas: Optional[float] = None,
             simular: Optional[bool] = None) -> Dict[str, Any]:
    """Revisa los eventos Cancelados/Reagendados recientes y avisa a asesor y centinela."""
    ventana = float(ventana_horas if ventana_horas is not None
                    else os.getenv("AVISOS_CITAS_VENTANA_HORAS", "6"))
    simular = dry_run() if simular is None else simular
    limite_pasado = datetime.now(timezone.utc) - timedelta(days=1)
    resumen: Dict[str, Any] = {"revisados": 0, "avisos": [], "omitidos_pasados": 0, "dry_run": simular}
    for ev in eventos_cambiados(ventana):
        resumen["revisados"] += 1
        f = _fecha(ev)
        if f and f < limite_pasado:            # cita que ya pasó: no tiene sentido avisar
            resumen["omitidos_pasados"] += 1
            continue
        estado = ev.get("Estado")
        if estado == "Reagendada":
            nueva = nueva_cita(_uno(ev.get("Correo invitado")), ev["_id"])
            accion = "reagendó"
            detalle = (f"Nueva fecha: {nueva}" if nueva
                       else f"Todavía no eligió nueva fecha. Link para reagendar: {_uno(ev.get('Link para Reagendar')) or 'sin link'}")
        else:
            accion = "canceló"
            detalle = f"Link para reagendar: {_uno(ev.get('Link para Reagendar')) or 'sin link'}"
        for h in _avisar_evento(db, ev, estado, accion, detalle, simular):
            resumen["avisos"].append({"evento": ev["_id"], "estado_cita": estado, **h})
    if resumen["avisos"]:
        log.info("avisos_citas: %s", resumen)
    return resumen


# ------------------------------------------------------------------ disparador 2: WhatsApp
def _cita_del_prospecto(wa_id: str, correo: str = "") -> Optional[Dict[str, Any]]:
    """Próxima cita Activa del prospecto: por teléfono (últimos 10 dígitos del WhatsApp) o,
    si agendó con otro número, por el correo con el que agendó."""
    num = wati.numero_whatsapp(wa_id) or ""
    sufijo = num[-10:] if len(num) >= 10 else None
    correo = (correo or "").strip().lower()
    if not sufijo and not correo:
        return None
    hoy = datetime.now(timezone.utc).date().isoformat()
    filtro = {"and": [
        {"property": "Estado", "select": {"equals": "Activo"}},
        {"property": "Fecha de Evento", "date": {"on_or_after": hoy}},
    ]}
    candidatos = []
    for ev in _query_todo(filtro, orden=[{"property": "Fecha de Evento", "direction": "ascending"}]):
        tel = (wati.numero_whatsapp(_uno(ev.get("Teléfono"))) or "")
        mail = _uno(ev.get("Correo invitado")).lower()
        if _fecha(ev) and ((sufijo and tel.endswith(sufijo)) or (correo and mail == correo)):
            candidatos.append(ev)
    return min(candidatos, key=_fecha) if candidatos else None


def avisar_por_whatsapp(db: Session, wa_id: str, mensaje: str = "", correo: str = "",
                        simular: Optional[bool] = None) -> Dict[str, Any]:
    """El prospecto le escribió a Tommy que no puede ir / quiere cambiar la cita.

    Avisa a asesor y centinela (una vez por día y cita) y devuelve lo que Tommy necesita
    para responderle al prospecto: fecha, link para reagendar y quiénes lo van a contactar.
    """
    simular = dry_run() if simular is None else simular
    ev = _cita_del_prospecto(wa_id, correo)
    if not ev:
        return {"encontrado": False,
                "detalle": "No hay una cita próxima con este WhatsApp"
                           + (" ni con ese correo." if correo else ". Pedile el correo con el que agendó.")}
    motivo = f"whatsapp:{datetime.now(timezone.utc).date().isoformat()}"
    texto = " ".join((mensaje or "").split())[:140]
    detalle = f"Le escribió a Tommy: \"{texto}\"" if texto else "Le escribió a Tommy por WhatsApp."
    avisos = _avisar_evento(db, ev, motivo, "pidió cancelar o cambiar", detalle, simular)
    dest = destinatarios(ev)
    return {
        "encontrado": True,
        "fecha_cita": fecha_legible(_fecha(ev)),
        "link_reagendar": _uno(ev.get("Link para Reagendar")) or None,
        "asesor": next((d["nombre"] for d in dest if d["rol"] == "asesor"), ""),
        "centinela": next((d["nombre"] for d in dest if d["rol"] == "centinela"), ""),
        "avisados": avisos,
        "ya_avisado_hoy": not avisos,
    }


# ------------------------------------------------------------------ hilo vigilante
_hilo: Optional[threading.Thread] = None


def iniciar_vigilante() -> None:
    """Arranca el vigilante en segundo plano si AVISOS_CITAS_ACTIVO=1 (uno por worker;
    la reserva con clave única evita avisos duplicados)."""
    global _hilo
    if not activo() or (_hilo and _hilo.is_alive()):
        return
    intervalo = max(1.0, float(os.getenv("AVISOS_CITAS_INTERVALO_MIN", "10"))) * 60

    def _loop():
        from app.database import SessionLocal
        time.sleep(30)  # dejar que el servicio termine de levantar
        while True:
            db = SessionLocal()
            try:
                escanear(db)
            except Exception as e:  # noqa: BLE001 — el vigilante nunca debe morir
                log.error("vigilante avisos_citas falló: %s", e)
            finally:
                db.close()
            time.sleep(intervalo)

    _hilo = threading.Thread(target=_loop, name="avisos-citas", daemon=True)
    _hilo.start()
    log.info("Vigilante de avisos de citas activo (cada %.0f min, dry_run=%s)", intervalo / 60, dry_run())

"""QA OFFLINE — avisos al asesor / centinela cuando un prospecto cancela o reagenda.

Sin red: Notion y WATI se simulan; la base es SQLite en memoria.
Correr:  pytest -v tests/test_avisos_citas.py
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.services.tomi import avisos_citas as avc
from app.services.tomi import wati


def _iso(dias: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=dias)).isoformat()


def _evento(eid="ev1", estado="Cancelada", dias=1, centinela=True, tel_cent="+52 999 222 3333"):
    ev = {
        "_id": eid, "Estado": estado, "Fecha de Evento": {"start": _iso(dias)},
        "Nombre del invitado": "Laura Prospecto", "Teléfono": "+52 1 999 111 2222",
        "Correo invitado": "laura@mail.com", "Link para Reagendar": "https://calendly.com/x/reagendar",
        "Nombre de Asesor": "Gibran Oziel Moo", "Teléfono Asesor": "9991234567",
    }
    if centinela:
        ev["Nombre de Cerrador"] = "Kevin Serrato"
        ev["Teléfono Cerrador"] = tel_cent
    return ev


@pytest.fixture()
def db():
    eng = create_engine("sqlite://")
    models.AvisoCita.__table__.create(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


@pytest.fixture()
def enviados(monkeypatch):
    log = []

    def fake_enviar(numero, plantilla, params, broadcast="x"):
        log.append({"numero": numero, "plantilla": plantilla, "params": params})
        return {"ok": True, "status": 200, "detalle": {"result": True}}

    monkeypatch.setattr(wati, "enviar_plantilla", fake_enviar)
    monkeypatch.setattr(avc, "nueva_cita", lambda correo, eid: None)
    return log


# ---------------------------------------------------------------- reglas de destinatarios
def test_numero_whatsapp_normaliza_mexico():
    assert wati.numero_whatsapp("999 123 4567") == "529991234567"
    assert wati.numero_whatsapp("+52 1 999 111 2222") == "5219991112222"
    assert wati.numero_whatsapp("123") is None


def test_destinatarios_asesor_y_centinela():
    d = avc.destinatarios(_evento())
    assert [x["rol"] for x in d] == ["asesor", "centinela"]


def test_destinatarios_sin_centinela_solo_asesor():
    assert [x["rol"] for x in avc.destinatarios(_evento(centinela=False))] == ["asesor"]


def test_destinatarios_misma_persona_un_solo_aviso():
    d = avc.destinatarios(_evento(tel_cent="9991234567"))  # mismo número que el asesor
    assert [x["rol"] for x in d] == ["asesor"]


# ---------------------------------------------------------------- vigilante
def test_escanear_dry_run_registra_sin_enviar(db, enviados, monkeypatch):
    monkeypatch.setattr(avc, "eventos_cambiados", lambda v: [_evento()])
    r = avc.escanear(db, ventana_horas=6, simular=True)
    assert [a["estado"] for a in r["avisos"]] == ["simulado", "simulado"]
    assert enviados == []                                   # nada salió por WhatsApp


def test_escanear_envia_y_no_duplica(db, enviados, monkeypatch):
    monkeypatch.setattr(avc, "eventos_cambiados", lambda v: [_evento()])
    avc.escanear(db, ventana_horas=6, simular=False)
    avc.escanear(db, ventana_horas=6, simular=False)        # segunda vuelta: ya avisado
    assert len(enviados) == 2                               # asesor + centinela, una sola vez
    p = enviados[0]["params"]
    assert p["accion"] == "canceló" and p["prospecto"] == "Laura Prospecto"
    assert "reagendar" in p["detalle"] and p["telefono"].startswith("+52")
    assert enviados[0]["numero"] == "529991234567" and p["nombre"] == "Gibran"


def test_escanear_omite_citas_pasadas(db, enviados, monkeypatch):
    monkeypatch.setattr(avc, "eventos_cambiados", lambda v: [_evento(dias=-3)])
    r = avc.escanear(db, ventana_horas=6, simular=False)
    assert r["omitidos_pasados"] == 1 and enviados == []


def test_reagendada_informa_nueva_fecha(db, enviados, monkeypatch):
    monkeypatch.setattr(avc, "eventos_cambiados", lambda v: [_evento(estado="Reagendada")])
    monkeypatch.setattr(avc, "nueva_cita", lambda correo, eid: "mar 07/10 10:00 h")
    avc.escanear(db, ventana_horas=6, simular=False)
    assert enviados[0]["params"]["accion"] == "reagendó"
    assert enviados[0]["params"]["detalle"] == "Nueva fecha: mar 07/10 10:00 h"


def test_error_de_wati_se_reintenta_hasta_3(db, monkeypatch):
    llamadas = []
    monkeypatch.setattr(wati, "enviar_plantilla",
                        lambda *a, **k: llamadas.append(1) or {"ok": False, "status": 400, "detalle": "x"})
    monkeypatch.setattr(avc, "eventos_cambiados", lambda v: [_evento(centinela=False)])
    for _ in range(5):
        avc.escanear(db, ventana_horas=6, simular=False)
    assert len(llamadas) == 3                               # MAX_INTENTOS
    fila = db.query(models.AvisoCita).one()
    assert fila.estado == "error" and fila.intentos == 3


def test_reserva_concurrente_un_solo_ganador(db):
    eng = db.get_bind()
    otra = sessionmaker(bind=eng)()
    ev, dest = _evento(), {"rol": "asesor", "nombre": "A", "numero": "529991234567"}
    assert avc._reservar(db, "ev1", "Cancelada", dest, ev) is not None
    assert avc._reservar(otra, "ev1", "Cancelada", dest, ev) is None   # el otro worker no lo toma
    otra.close()


# ---------------------------------------------------------------- disparador WhatsApp
def test_avisar_por_whatsapp_encuentra_cita_y_avisa_una_vez_por_dia(db, enviados, monkeypatch):
    activo = _evento(estado="Activo")
    otro = dict(_evento(eid="ev2", estado="Activo"), **{"Teléfono": "+52 55 0000 0000"})
    monkeypatch.setattr(avc, "_query_todo", lambda *a, **k: [otro, activo])
    r = avc.avisar_por_whatsapp(db, "5219991112222", "no voy a poder ir mañana", simular=False)
    assert r["encontrado"] and r["link_reagendar"].startswith("https://")
    assert r["asesor"] == "Gibran Oziel Moo" and r["centinela"] == "Kevin Serrato"
    assert len(enviados) == 2 and "no voy a poder ir" in enviados[0]["params"]["detalle"]
    r2 = avc.avisar_por_whatsapp(db, "5219991112222", "otra vez", simular=False)
    assert r2["ya_avisado_hoy"] and len(enviados) == 2


def test_avisar_por_whatsapp_sin_cita(db, enviados, monkeypatch):
    monkeypatch.setattr(avc, "_query_todo", lambda *a, **k: [])
    r = avc.avisar_por_whatsapp(db, "5219991112222", "no puedo", simular=False)
    assert r["encontrado"] is False and enviados == []


def test_avisar_por_whatsapp_por_correo_si_el_numero_no_coincide(db, enviados, monkeypatch):
    ev = dict(_evento(estado="Activo"), **{"Teléfono": "+52 55 0000 0000"})
    monkeypatch.setattr(avc, "_query_todo", lambda *a, **k: [ev])
    assert avc.avisar_por_whatsapp(db, "5219991112222", "no puedo", simular=False)["encontrado"] is False
    r = avc.avisar_por_whatsapp(db, "5219991112222", "no puedo", correo="Laura@Mail.com", simular=False)
    assert r["encontrado"] and len(enviados) == 2

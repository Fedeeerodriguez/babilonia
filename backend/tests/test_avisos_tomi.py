"""Avisos temporales de Tommy: se cargan en la plataforma y le llegan al agente en `nota_sistema`."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, get_db
from app.routers import avisos_tomi, tomi
from app.security import require_admin
from app.services.tomi import avisos as av

AHORA = datetime.now(timezone.utc)


@pytest.fixture
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng, tables=[models.AvisoTomi.__table__])
    s = sessionmaker(bind=eng)()
    av.invalidar()
    yield s
    s.close()


@pytest.fixture
def cli(db):
    app = FastAPI()
    app.include_router(avisos_tomi.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_admin] = lambda: models.User(email="ceci@babilonia.ai", full_name="Ceci")
    return TestClient(app)


LIGA = {"titulo": "Liga Babilonia en mantenimiento",
        "contenido": "La Liga Babilonia está cerrada por mantenimiento. Vuelve a abrir el lunes 3 de noviembre."}


# ------------------------------------------------------------------ servicio
def aviso(db, **kw):
    a = models.AvisoTomi(**{"titulo": "T", "contenido": "C", "audiencia": "todos", "activo": True, **kw})
    db.add(a)
    db.commit()
    return a


def test_estado_segun_interruptor_y_fechas(db):
    assert av.estado(aviso(db)) == "vigente"
    assert av.estado(aviso(db, activo=False)) == "apagado"
    assert av.estado(aviso(db, desde=AHORA + timedelta(days=1))) == "programado"
    assert av.estado(aviso(db, hasta=AHORA - timedelta(minutes=1))) == "vencido"


def test_vigentes_por_audiencia(db):
    aviso(db, titulo="A todos")
    aviso(db, titulo="Solo asesores", audiencia="asesor")
    aviso(db, titulo="Apagado", activo=False)
    assert [a.titulo for a in av.vigentes(db, "asesor")] == ["A todos", "Solo asesores"]
    assert [a.titulo for a in av.vigentes(db, "cliente")] == ["A todos"]
    assert [a.titulo for a in av.vigentes(db, "desconocido")] == ["A todos"]


def test_bloque_para_el_agente(db):
    aviso(db, **LIGA, hasta=datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc))
    texto = av.armar_bloque(av.vigentes(db, "cliente", ahora=datetime(2026, 10, 25, tzinfo=timezone.utc)))
    assert texto.startswith("AVISOS VIGENTES DE BABILONIA")
    assert "PRIORIDAD" in texto
    assert ("- Liga Babilonia en mantenimiento: La Liga Babilonia está cerrada por mantenimiento. Vuelve a abrir "
            "el lunes 3 de noviembre. (vigente hasta el 03/11/2026 09:00, hora de CDMX)") in texto
    assert av.armar_bloque([]) == ""


def test_nota_sistema_no_pisa_lo_que_habia():
    res = {"nota_sistema": "MODO DEMO"}
    av.agregar_a_nota(res, "AVISOS …")
    assert res["nota_sistema"] == "MODO DEMO\n\nAVISOS …" and res["avisos_bloque"] == "AVISOS …"
    assert av.agregar_a_nota({}, "") == {}


# ------------------------------------------------------------------ plataforma (admin)
def test_crear_editar_apagar_y_borrar(cli):
    r = cli.post("/api/tomi/avisos", json=LIGA)
    assert r.status_code == 200, r.text
    a = r.json()
    assert (a["estado"], a["audiencia"], a["creado_por"]) == ("vigente", "todos", "Ceci")
    assert "Liga Babilonia" in cli.get("/api/tomi/avisos/vista-previa", params={"tipo": "asesor"}).json()["bloque"]

    r = cli.put(f"/api/tomi/avisos/{a['id']}", json={"contenido": "Abre el martes 4.", "audiencia": "asesor"})
    assert r.json()["contenido"] == "Abre el martes 4." and r.json()["audiencia"] == "asesor"
    assert cli.get("/api/tomi/avisos/vista-previa", params={"tipo": "cliente"}).json()["bloque"] == ""

    r = cli.put(f"/api/tomi/avisos/{a['id']}", json={"activo": False})
    assert r.json()["estado"] == "apagado" and r.json()["titulo"] == LIGA["titulo"]  # no borra lo demás
    assert cli.get("/api/tomi/avisos").json()["vigentes"] == 0

    assert cli.delete(f"/api/tomi/avisos/{a['id']}").status_code == 200
    assert cli.get("/api/tomi/avisos").json()["items"] == []
    assert cli.delete(f"/api/tomi/avisos/{a['id']}").status_code == 404


def test_programado_con_fechas(cli):
    desde = (AHORA + timedelta(days=2)).isoformat()
    hasta = (AHORA + timedelta(days=5)).isoformat()
    a = cli.post("/api/tomi/avisos", json={**LIGA, "desde": desde, "hasta": hasta}).json()
    assert a["estado"] == "programado"
    # Quitar la fecha de inicio → vigente ya; la de fin se mantiene.
    a = cli.put(f"/api/tomi/avisos/{a['id']}", json={"desde": None}).json()
    assert a["estado"] == "vigente" and a["hasta"]


@pytest.mark.parametrize("body,detalle", [
    ({"titulo": "x"}, "título y contenido"),
    ({**LIGA, "audiencia": "jefes"}, "Audiencia"),
    ({**LIGA, "desde": "2026-11-05T10:00:00Z", "hasta": "2026-11-01T10:00:00Z"}, "posterior"),
])
def test_validaciones(cli, body, detalle):
    r = cli.post("/api/tomi/avisos", json=body)
    assert r.status_code == 400 and detalle in r.json()["detail"]


def test_solo_admin(db):
    app = FastAPI()
    app.include_router(avisos_tomi.router)
    app.dependency_overrides[get_db] = lambda: db
    assert TestClient(app).get("/api/tomi/avisos").status_code == 401


# ------------------------------------------------------------------ lo que recibe el agente (n8n)
def test_clasificar_usuario_suma_los_avisos_a_nota_sistema(db, cli, monkeypatch):
    cli.post("/api/tomi/avisos", json=LIGA)
    monkeypatch.setattr(tomi, "_auth", lambda key: None)
    monkeypatch.setattr(tomi.sw, "is_enabled", lambda db: True)
    monkeypatch.setattr(tomi.clasif, "clasificar", lambda db, **kw: {"comando_2": "cliente", "user_id": "52155"})
    monkeypatch.setattr(tomi.aprend, "bloque_directrices", lambda db, ambito: "")
    res = tomi.clasificar_usuario(tomi.ClasificarUsuarioIn(user_id="52155", mensaje_usuario="hola"), None, db)
    assert res["comando_2"] == "cliente"
    assert "Liga Babilonia en mantenimiento" in res["nota_sistema"]
    # Pausado (interruptor apagado): no se agrega nada.
    monkeypatch.setattr(tomi.sw, "is_enabled", lambda db: False)
    res = tomi.clasificar_usuario(tomi.ClasificarUsuarioIn(user_id="52155", mensaje_usuario="hola"), None, db)
    assert res["pausado"] and "nota_sistema" not in res


def test_si_los_avisos_fallan_la_clasificacion_sale_igual(db, monkeypatch):
    monkeypatch.setattr(tomi, "_auth", lambda key: None)
    monkeypatch.setattr(tomi.sw, "is_enabled", lambda db: True)
    monkeypatch.setattr(tomi.clasif, "clasificar", lambda db, **kw: {"comando_2": "asesor"})
    monkeypatch.setattr(tomi.aprend, "bloque_directrices", lambda db, ambito: "")
    monkeypatch.setattr(tomi.aprend, "procesar_con_sesion", lambda db, **kw: {})
    monkeypatch.setattr(av, "bloque", lambda db, tipo: 1 / 0)
    res = tomi.clasificar_usuario(tomi.ClasificarUsuarioIn(user_id="1", mensaje_usuario="hola"), None, db)
    assert res["comando_2"] == "asesor" and "nota_sistema" not in res

"""Usuario DEMO: registro por WhatsApp con usuario/contraseña, cliente fijo y aislado.

Reusa la DB falsa y el Notion simulado de test_clasificacion_nivel_fijo.
"""
import pytest

from app.services.tomi import agente as ag
from app.services.tomi import bases_datos as bd
from app.services.tomi import clasificador as clf
from app.services.tomi import demo
from tests.test_clasificacion_nivel_fijo import WA, FakeDB, notion  # noqa: F401  (fixture)

CLAVE = "Pru3ba-Demo-2026"


@pytest.fixture
def db():
    return FakeDB()


@pytest.fixture(autouse=True)
def demo_env(monkeypatch):
    monkeypatch.setenv("TOMI_DEMO_USUARIO", "demo.babilonia")
    monkeypatch.setenv("TOMI_DEMO_PASSWORD", CLAVE)
    monkeypatch.delenv("TOMI_DEMO_EMAIL", raising=False)


def _c(db, msg):
    return clf.clasificar(db, user_id=WA, mensaje_usuario=msg)


# ------------------------------------------------------------------ registro
def test_registro_demo_lo_deja_como_cliente_demo(db, notion):
    r = _c(db, f"DEMO demo.babilonia {CLAVE}")
    assert r["comando_2"] == "cliente" and r["demo"] and r["email"] == demo.EMAIL_DEFAULT
    assert "MODO DEMO" in r["nota_sistema"]
    # y queda fijo en las siguientes ejecuciones, aunque escriba otros correos
    assert _c(db, "hola")["comando_2"] == "cliente"
    assert _c(db, "mostrame lo de juan@cliente.com")["email"] == demo.EMAIL_DEFAULT


def test_registro_entre_otros_mensajes_juntados_por_n8n(db, notion):
    assert _c(db, f"hola\nDEMO demo.babilonia {CLAVE}\ngracias")["comando_2"] == "cliente"


def test_clave_incorrecta_no_registra(db, notion):
    r = _c(db, "DEMO demo.babilonia otra-clave")
    assert r["comando_2"] == "desconocido" and "no son correctos" in r["nota_sistema"]
    assert WA not in db.filas


def test_demo_apagado_sin_variables(db, notion, monkeypatch):
    monkeypatch.delenv("TOMI_DEMO_PASSWORD")
    r = _c(db, f"DEMO demo.babilonia {CLAVE}")
    assert r["comando_2"] == "desconocido" and "nota_sistema" not in r


def test_cada_numero_tiene_su_propia_fila(db, notion):
    for wa in ("5211111111111", "5212222222222"):
        clf.clasificar(db, user_id=wa, mensaje_usuario=f"DEMO demo.babilonia {CLAVE}")
    assert set(db.filas) == {"5211111111111", "5212222222222"}


# ------------------------------------------------------------------ salir y nivel fijo
def test_asesor_prueba_el_demo_y_al_salir_vuelve_a_asesor(db, notion):
    notion["por_email"] = {"asesora@babilonia.ai": "asesor"}
    assert _c(db, "asesora@babilonia.ai")["comando_2"] == "asesor"
    assert _c(db, f"DEMO demo.babilonia {CLAVE}")["comando_2"] == "cliente"
    r = _c(db, "SALIR DEMO")
    assert r["comando_2"] == "asesor" and r["email"] == "asesora@babilonia.ai"


def test_desconocido_al_salir_vuelve_a_desconocido(db, notion):
    _c(db, f"DEMO demo.babilonia {CLAVE}")
    assert _c(db, "salir del demo")["comando_2"] == "desconocido"
    assert WA not in db.filas


def test_demo_no_sube_de_nivel_por_telefono(db, notion):
    from datetime import timedelta
    _c(db, f"DEMO demo.babilonia {CLAVE}")
    db.filas[WA]["updated_at"] -= timedelta(days=3)
    notion["por_tel"] = {WA: "asesor"}
    assert _c(db, "hola")["comando_2"] == "cliente"


def test_registrarse_dos_veces_conserva_el_nivel_original(db, notion):
    notion["por_email"] = {"a@x.com": "asesor"}
    _c(db, "a@x.com")
    _c(db, f"DEMO demo.babilonia {CLAVE}")
    _c(db, f"DEMO demo.babilonia {CLAVE}")
    assert _c(db, "SALIR DEMO")["comando_2"] == "asesor"


# ------------------------------------------------------------------ privacidad
def test_cliente_solo_consulta_su_propio_correo(monkeypatch):
    llamadas = []
    monkeypatch.setattr(bd, "consultar", lambda **kw: llamadas.append(kw) or {"ok": True})
    alcance = ag.alcance_de({"comando_2": "cliente", "email": "cliente.demo@example.com"})
    # La IA intenta buscar a otro cliente por correo, póliza, nombre y cartera de asesor.
    ag._dispatch("consultar_bases", {
        "mensaje": "dame las pólizas de juan@otro.com y la PLU3-999 de Pedro Pérez",
        "modo": "cartera", "emails": ["juan@otro.com"], "polizas": ["PLU3-999"],
        "clientes": ["Pedro Pérez"], "email_asesor": "asesor@babilonia.ai",
        "incluir": ["clientes_por_nombre", "emisiones"]}, wa_id=WA, alcance=alcance)
    kw = llamadas[0]
    assert kw["email_cliente"] == "cliente.demo@example.com"
    assert kw["mensaje"] == "" and kw["modo"] == "polizas" and kw["incluir"] == ["emisiones"]
    for campo in ("emails", "polizas", "clientes", "asesores", "email_asesor"):
        assert not kw.get(campo), campo


def test_cliente_no_puede_abrir_paginas_de_notion(monkeypatch):
    monkeypatch.setattr(ag.nc, "_resolve_page_full", lambda pid: pytest.fail("no debía abrirla"))
    alcance = ag.alcance_de({"comando_2": "cliente", "email": "c@x.com"})
    assert "error" in ag._dispatch("expandir_pagina", {"page_id": "abc"}, alcance=alcance)


def test_asesor_sin_restriccion():
    assert ag.alcance_de({"comando_2": "asesor", "email": "a@x.com"}) is None
    assert ag.alcance_de(None) is None

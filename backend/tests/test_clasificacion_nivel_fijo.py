"""Nivel fijo de las personas: estudiante → cliente → asesor; una vez fijo, nunca baja.

Usa una DB falsa que responde las mismas consultas SQL que `clasificador` (tabla
`tomi_clasificaciones`), así corre el código real sin Postgres. Notion se simula.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.tomi import clasificador as clf
from app.services.tomi import notion_client as nc

WA = "5215512345678"


class _Res:
    def __init__(self, row=None, scalar=None):
        self._row, self._scalar = row, scalar

    def mappings(self):
        return self

    def first(self):
        return self._row

    def scalar(self):
        return self._scalar


class FakeDB:
    """Responde las consultas de clasificador.py sobre un dict {user_id: fila}."""

    def __init__(self):
        self.filas = {}

    def execute(self, sql, params=None):
        q, p = " ".join(str(sql).split()), params or {}
        if q.startswith("SELECT 1 FROM tomi_clasificaciones"):
            return _Res()
        if q.startswith("SELECT comando_2 FROM"):
            f = self.filas.get(p["uid"])
            return _Res(scalar=f and f["comando_2"])
        if "WHERE user_id = :uid" in q and q.startswith("SELECT"):
            return _Res(row=self.filas.get(p["uid"]))
        if "WHERE email = :em" in q:
            fs = [f for f in self.filas.values() if f["email"] == p["em"]]
            return _Res(row=max(fs, key=lambda f: f["updated_at"]) if fs else None)
        if q.startswith("INSERT INTO tomi_clasificaciones"):
            previo = self.filas.get(p["uid"], {})
            self.filas[p["uid"]] = {"user_id": p["uid"], "email": p["em"], "comando_1": p["c1"],
                                    "comando_2": p["c2"], "user_nombre": p["nom"] or previo.get("user_nombre"),
                                    "data": p["data"], "updated_at": datetime.now(timezone.utc)}
            return _Res()
        if q.startswith("UPDATE tomi_clasificaciones SET updated_at"):
            self.filas[p["uid"]]["updated_at"] = datetime.now(timezone.utc)
            return _Res()
        raise AssertionError(f"consulta no esperada: {q}")

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.fixture
def db():
    return FakeDB()


@pytest.fixture
def notion(monkeypatch):
    """Notion simulado: {email: tipo} y {wa_id: tipo}. Cuenta las consultas por teléfono."""
    estado = {"por_email": {}, "por_tel": {}, "consultas_tel": 0}

    def por_email(email):
        tipo = estado["por_email"].get(email, "prospecto")
        return {"tipo": tipo, "data": {"Correo": email} if tipo != "prospecto" else None}

    def por_tel(wa):
        estado["consultas_tel"] += 1
        tipo = estado["por_tel"].get(wa, "prospecto")
        return {"tipo": tipo, "data": {"Correo": f"{tipo}@x.com"} if tipo != "prospecto" else None}

    monkeypatch.setattr(nc, "clasificar_usuario_por_email", por_email)
    monkeypatch.setattr(nc, "clasificar_usuario_por_telefono", por_tel)
    return estado


def _clasificar(db, msg="hola", **kw):
    return clf.clasificar(db, user_id=WA, mensaje_usuario=msg, **kw)["comando_2"]


# ------------------------------------------------------------------ orden de niveles
def test_orden_de_niveles():
    assert clf.nivel("estudiante") < clf.nivel("cliente") < clf.nivel("asesor")
    assert clf.nivel("prospecto") == clf.nivel("desconocido") == 0
    assert nc.NIVELES_DE_MAYOR_A_MENOR == ("asesor", "cliente", "estudiante")


# ------------------------------------------------------------------ nunca baja
def test_asesor_que_escribe_el_correo_de_un_cliente_sigue_siendo_asesor(db, notion):
    # Bug real: el asesor quedaba guardado como el cliente cuyo correo mencionaba.
    notion["por_email"] = {"asesora@babilonia.ai": "asesor", "juan@cliente.com": "cliente"}
    assert _clasificar(db, "mi correo es asesora@babilonia.ai") == "asesor"
    assert _clasificar(db, "revisá las pólizas de juan@cliente.com") == "asesor"
    assert db.filas[WA]["email"] == "asesora@babilonia.ai"      # tampoco le cambia la identidad


def test_un_correo_desconocido_no_baja_a_prospecto(db, notion):
    notion["por_email"] = {"asesora@babilonia.ai": "asesor"}
    _clasificar(db, "asesora@babilonia.ai")
    assert _clasificar(db, "escribile a alguien@nuevo.com") == "asesor"


def test_force_no_baja_de_nivel(db, notion):
    notion["por_email"] = {"cli@x.com": "cliente"}
    _clasificar(db, "cli@x.com")
    notion["por_email"] = {}                                    # Notion "lo pierde"
    assert _clasificar(db, "cli@x.com", force=True) == "cliente"


def test_guardar_no_pisa_un_nivel_mayor(db):
    clf.guardar_clasificacion(db, user_id=WA, email="a@x.com", comando_1="registrado", comando_2="asesor")
    assert clf.guardar_clasificacion(db, user_id=WA, email="b@x.com", comando_1="registrado",
                                     comando_2="estudiante") is False
    assert db.filas[WA]["comando_2"] == "asesor"


def test_nivel_fijo_se_mantiene_en_todas_las_ejecuciones(db, notion):
    notion["por_email"] = {"est@x.com": "estudiante"}
    _clasificar(db, "est@x.com")
    for msg in ("hola", "otro@x.com", "quiero cancelar", "cli@x.com"):
        assert _clasificar(db, msg) == "estudiante"


# ------------------------------------------------------------------ solo sube
def test_estudiante_sube_a_cliente_y_despues_a_asesor(db, notion):
    notion["por_email"] = {"p@x.com": "estudiante"}
    _clasificar(db, "p@x.com")
    vencer = lambda: db.filas[WA].update(updated_at=datetime.now(timezone.utc) - timedelta(hours=25))

    notion["por_tel"] = {WA: "cliente"}; vencer()
    assert _clasificar(db) == "cliente"
    notion["por_tel"] = {WA: "asesor"}; vencer()
    assert _clasificar(db) == "asesor"
    notion["por_tel"] = {WA: "estudiante"}; vencer()             # aunque Notion diga menos
    assert _clasificar(db) == "asesor"


def test_revision_de_ascenso_una_vez_por_dia(db, notion):
    notion["por_email"] = {"c@x.com": "cliente"}
    _clasificar(db, "c@x.com")
    db.filas[WA]["updated_at"] -= timedelta(hours=25)
    _clasificar(db); _clasificar(db); _clasificar(db)
    assert notion["consultas_tel"] == 1                         # no golpea Notion en cada mensaje


def test_asesor_no_consulta_notion_para_subir(db, notion):
    notion["por_email"] = {"a@x.com": "asesor"}
    _clasificar(db, "a@x.com")
    db.filas[WA]["updated_at"] -= timedelta(days=30)
    _clasificar(db)
    assert notion["consultas_tel"] == 0


def test_cliente_y_estudiante_a_la_vez_gana_cliente(monkeypatch):
    # Prioridad de Notion: asesor > cliente > estudiante (antes estudiante ganaba a cliente).
    filas = {"asesor": [], "estudiante": [{"id": "e"}], "cliente": [{"id": "c"}]}
    monkeypatch.setattr(nc, "_query", lambda db_id, filtro: filas[{"A": "asesor", "E": "estudiante",
                                                                   "C": "cliente"}[db_id]])
    monkeypatch.setattr(nc, "DB_ASESORES", "A"); monkeypatch.setattr(nc, "DB_ESTUDIANTES", "E")
    monkeypatch.setattr(nc, "DB_CLIENTES", "C")
    assert nc.clasificar_usuario_por_email("x@x.com")["tipo"] == "cliente"


# ------------------------------------------------------------------ prospecto no queda trabado
def test_prospecto_por_falla_de_notion_se_reintenta(db, notion):
    notion["por_email"] = {}                                    # Notion falla → prospecto
    assert _clasificar(db, "ana@x.com") == "prospecto"
    notion["por_email"] = {"ana@x.com": "cliente"}              # Notion vuelve
    assert _clasificar(db, "ana@x.com") == "cliente"

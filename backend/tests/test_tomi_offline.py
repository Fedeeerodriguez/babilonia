"""QA OFFLINE — funciones deterministas de Tomi (sin red, sin credenciales).

Cubre: clasificador de email, clasificador de categorías por keywords, taxonomía
categoria→clave, selección de días de atraso (vivo vs guardado), extracción regex
del sub-agente de bases de datos y detección de intención.

Correr con el runner:  python tests/run_qa.py
O con pytest:          pytest -v tests/test_tomi_offline.py
"""
from __future__ import annotations

from app.services.tomi import clasificador as clf
from app.services.tomi import memorias as mem
from app.services.tomi import notion_client as nc
from app.services.tomi import bases_datos as bd


# ---------------------------------------------------------------- clasificador email
def test_extraer_email_simple():
    assert clf.extraer_email("mi correo es juan.perez@mail.com dale") == "juan.perez@mail.com"


def test_extraer_email_normaliza_mayus():
    assert clf.extraer_email("Escribime a Juan@Gmail.COM") == "juan@gmail.com"


def test_extraer_email_sin_email():
    assert clf.extraer_email("hola no tengo correo") is None
    assert clf.extraer_email("") is None


# ---------------------------------------------------------------- keywords memorias
def test_keywords_plu3():
    assert mem.clasificar_por_keywords("quiero un plan de retiro ppr")[0] == "plu3"


def test_keywords_elite_detectado():
    # 'elite' fue agregado hoy — antes no existía como categoría
    cats = mem.clasificar_por_keywords("me interesa optimaxx elite en dolares y euros")
    assert "elite" in cats, f"esperaba 'elite' en {cats}"


def test_keywords_auto():
    assert "auto" in mem.clasificar_por_keywords("necesito seguro de auto")


def test_keywords_proteccion():
    assert "proteccion" in mem.clasificar_por_keywords("un seguro de vida por fallecimiento")


def test_keywords_patrimonial():
    assert "patrimonial" in mem.clasificar_por_keywords("inversion patrimonial de allianz")


def test_keywords_educacion():
    assert "educacion" in mem.clasificar_por_keywords("informacion de la academia y los cursos")


def test_keywords_vacio():
    assert mem.clasificar_por_keywords("") == []
    assert mem.clasificar_por_keywords("hola que tal como andas") == []


# ---------------------------------------------------------------- taxonomia categoria->clave
def test_categoria_a_clave_cubre_todas():
    # Toda categoría válida debe tener una clave Allianz mapeada (para el filtro del RAG)
    assert set(mem.CATEGORIA_A_CLAVE.keys()) == set(mem.CATEGORIAS_VALIDAS)


def test_categoria_a_clave_valores():
    esperado = {"plu3": "PLU3", "educacion": "OP3D", "patrimonial": "OPPT",
                "elite": "SVIP", "proteccion": "VIPP", "auto": "AUIN"}
    assert mem.CATEGORIA_A_CLAVE == esperado


# ---------------------------------------------------------------- dias de atraso (bug fix)
def test_atraso_vivo_gana_al_guardado():
    c = {"Días de Atraso Actuales": 5, "Días de atraso": 30}
    assert nc.pick_dias_atraso(c) == 5


def test_atraso_cero_es_valido_no_cae_al_viejo():
    # 0 = cliente regularizado. NO debe caer al valor guardado (30).
    c = {"Días de Atraso Actuales": 0, "Días de atraso": 30}
    assert nc.pick_dias_atraso(c) == 0


def test_atraso_fallback_cuando_vivo_none():
    c = {"Días de Atraso Actuales": None, "Días de atraso": 30}
    assert nc.pick_dias_atraso(c) == 30


def test_atraso_fallback_cuando_vivo_vacio():
    c = {"Días de Atraso Actuales": "", "Días de atraso": 12}
    assert nc.pick_dias_atraso(c) == 12


def test_atraso_sin_datos():
    assert nc.pick_dias_atraso({}) is None


def test_to_int_parsers():
    assert nc._to_int("5") == 5
    assert nc._to_int("5.0") == 5
    assert nc._to_int(3.9) == 3
    assert nc._to_int(None) == 0
    assert nc._to_int("abc") == 0


# ---------------------------------------------------------------- bases_datos extracción
def test_extraer_email_y_poliza():
    emails, polizas, cli, ase = bd._extraer("el cliente Juan con poliza PLU3-408444 y mail a@b.com")
    assert "a@b.com" in emails
    assert "PLU3-408444" in polizas


def test_extraer_poliza_varios_formatos():
    _, polizas, _, _ = bd._extraer("tengo Auto-9876543 y Vida-12345")
    assert "Auto-9876543" in polizas and "Vida-12345" in polizas


def test_detectar_intent_cobranza():
    assert bd._detectar_intents("cuánto debo de mi cuota, tengo un pago vencido")["cobranza"] is True


def test_detectar_intent_tickets():
    assert bd._detectar_intents("quiero hacer una denuncia de siniestro")["tickets"] is True


def test_detectar_intent_calendly():
    assert bd._detectar_intents("quiero agendar un turno")["calendly"] is True


def test_detectar_intent_daf():
    assert bd._detectar_intents("cuál es mi número de agente / DAF")["daf"] is True


def test_detectar_intent_productos():
    assert bd._detectar_intents("¿tienen seguro de mascotas? qué productos ofrecen")["productos"] is True


def test_detectar_intent_ninguno():
    ints = bd._detectar_intents("hola buenos días")
    assert not any(ints.values())


def test_prioridad_estado_orden():
    assert bd._prioridad_estado("Activa") < bd._prioridad_estado("Cancelada")
    assert bd._prioridad_estado("estado inventado") == 99

"""Crea (o verifica) las cuentas DEMO en Notion para probar a Tommy de punta a punta.

Uso (desde backend/, con el .env de producción):
    python -m scripts.demo_seed              # crea/completa lo que falte (idempotente)
    python -m scripts.demo_seed --verificar  # solo muestra lo que encuentra

Qué crea, todo con "DEMO" en el nombre y datos ficticios:
  - Asesores: "DEMO Asesor Prueba" (TOMI_DEMO_ASESOR_EMAIL).
  - Clientes General: 3 clientes de la cartera del asesor demo ("DEMO María Prueba" es el
    cliente con el que se entra con `DEMO <usuario> <clave>`).
  - Emisiones: 4 pólizas ACTIVAS, con "Correo Asesor" = el asesor demo (así arma su cartera).
  - Cobranza: el cobro de la PLU3 de María con el pago APLICADO.

Cuidados para no ensuciar la operación real:
  - Asesor demo: Estado "Inactivo", "Eliminado de Avisos" y "Eliminado de Nivel" marcados,
    Liga desactivada, sin teléfono ni líder → no entra en rankings, niveles ni difusiones.
  - Sin Producto ni Líder relacionados → no suma puntos ni bonos a nadie real.
  - Pólizas Activas y cobranza "Pago hecho - aplicado" → no entra en colas de trabajo.
  - Sin teléfonos: cada tester entra con su propio WhatsApp vía el comando DEMO.
"""
from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv(".env")

from app.services.tomi import demo  # noqa: E402
from app.services.tomi import notion_client as nc  # noqa: E402

NOTA = "REGISTRO DEMO — datos ficticios para probar a Tommy. No contactar ni modificar."

CLIENTES = [
    {"correo": None, "nombre": None, "nacimiento": "1990-05-12"},  # el cliente demo (env)
    {"correo": demo.OTROS_CLIENTES[0], "nombre": "DEMO Carlos Ejemplo", "nacimiento": "1984-11-03"},
    {"correo": demo.OTROS_CLIENTES[1], "nombre": "DEMO Lucía Muestra", "nacimiento": "1996-02-27"},
]
POLIZAS = [
    {"cliente": 0, "numero": "DEMO-PLU3-000001", "producto": "PLU3 Plan de Retiro (demo)",
     "prima": 2500, "periodicidad": "Mensual", "emision": "2026-03-01"},
    {"cliente": 0, "numero": "DEMO-GMM-000002", "producto": "Gastos Médicos Mayores (demo)",
     "prima": 18000, "periodicidad": "Anual", "emision": "2026-01-15"},
    {"cliente": 1, "numero": "DEMO-PROT-000003", "producto": "Seguro de Vida Protección (demo)",
     "prima": 1200, "periodicidad": "Mensual", "emision": "2025-11-20"},
    {"cliente": 2, "numero": "DEMO-EDU-000004", "producto": "Plan Educacional (demo)",
     "prima": 9000, "periodicidad": "Semestral", "emision": "2026-06-10"},
]


def _txt(v: str) -> dict:
    return {"rich_text": [{"text": {"content": v}}]}


def _titulo(v: str) -> dict:
    return {"title": [{"text": {"content": v}}]}


def _buscar(db_id: str, prop: str, tipo: str, valor: str) -> list:
    r = nc._retry_429(nc._client().databases.query, database_id=db_id,
                      filter={"property": prop, tipo: {"equals": valor}})
    return r.get("results", [])


def _crear(db_id: str, props: dict) -> str:
    return nc._retry_429(nc._client().pages.create, parent={"database_id": db_id},
                         properties=props)["id"]


def _actualizar(page_id: str, props: dict) -> None:
    nc._retry_429(nc._client().pages.update, page_id=page_id, properties=props)


def _texto(page: dict, prop: str) -> str:
    return "".join(t.get("plain_text", "") for t in page["properties"].get(prop, {}).get("rich_text", []))


def asesor(verificar: bool) -> str | None:
    hay = _buscar(nc.DB_ASESORES, "Correo", "rich_text", demo.asesor_email())
    if hay or verificar:
        print(f"asesor   : {'OK ' + hay[0]['id'] if hay else 'FALTA'}  ({demo.asesor_email()})")
        return hay[0]["id"] if hay else None
    pid = _crear(nc.DB_ASESORES, {
        "Nombre Completo": _titulo(demo.asesor_nombre()),
        "Primer Nombre": _txt("DEMO"),
        "Correo": _txt(demo.asesor_email()),
        "Estado de Asesor": {"select": {"name": "Inactivo"}},
        "Eliminado de Avisos": {"checkbox": True},
        "Eliminado de Nivel": {"checkbox": True},
        "Liga Activada": {"checkbox": False},
        "Activación Liga": {"checkbox": False},
    })
    print(f"asesor   : CREADO {pid}")
    return pid


def cliente(c: dict, verificar: bool) -> str | None:
    correo, nombre = c["correo"] or demo.email(), c["nombre"] or demo.nombre()
    hay = _buscar(nc.DB_CLIENTES, "Correo", "rich_text", correo)
    if hay or verificar:
        print(f"cliente  : {'OK ' + hay[0]['id'] if hay else 'FALTA'}  ({correo})")
        return hay[0]["id"] if hay else None
    pid = _crear(nc.DB_CLIENTES, {
        "Nombre del Cliente": _titulo(nombre),
        "Correo": _txt(correo),
        "Fecha de Nacimiento": {"date": {"start": c["nacimiento"]}},
        "Notas General": _txt(NOTA),
    })
    print(f"cliente  : CREADO {pid}  ({correo})")
    return pid


def poliza(p: dict, cliente_id: str | None, asesor_id: str | None, verificar: bool) -> str | None:
    c = CLIENTES[p["cliente"]]
    correo, nombre = c["correo"] or demo.email(), c["nombre"] or demo.nombre()
    hay = _buscar(nc.DB_EMISIONES, "Número de Póliza", "rich_text", p["numero"])
    if hay:
        pag = hay[0]
        falta_asesor = _texto(pag, "Correo Asesor").strip().lower() != demo.asesor_email()
        if falta_asesor and not verificar and asesor_id:
            _actualizar(pag["id"], {"Correo Asesor": _txt(demo.asesor_email()),
                                    "Asesor": {"relation": [{"id": asesor_id}]}})
            print(f"póliza   : OK {pag['id']}  {p['numero']} (+ asesor demo)")
        else:
            print(f"póliza   : OK {pag['id']}  {p['numero']}"
                  f"{' (SIN asesor demo)' if falta_asesor else ''}")
        return pag["id"]
    if verificar or not cliente_id:
        print(f"póliza   : FALTA  {p['numero']}")
        return None
    props = {
        "Solicitud": _titulo(p["numero"]),
        "Número de Póliza": _txt(p["numero"]),
        "Estado": {"status": {"name": "Activa"}},
        "Tipo de Solicitud": {"select": {"name": "Emisión"}},
        "Periodicidad": {"select": {"name": p["periodicidad"]}},
        "Prima": {"number": p["prima"]},
        "Fecha de Emisión": {"date": {"start": p["emision"]}},
        "Correo Cliente": _txt(correo),
        "Nombre Cliente": _txt(nombre),
        "Correo Asesor": _txt(demo.asesor_email()),
        "Producto (nombre)": _txt(p["producto"]),
        "Notas de Emisión": _txt(NOTA),
        "Clientes General": {"relation": [{"id": cliente_id}]},
    }
    if asesor_id:
        props["Asesor"] = {"relation": [{"id": asesor_id}]}
    pid = _crear(nc.DB_EMISIONES, props)
    print(f"póliza   : CREADA {pid}  {p['numero']}")
    return pid


def cobranza(p: dict, emision_id: str | None, verificar: bool) -> None:
    hay = _buscar(nc.DB_COBRANZAS, "Póliza", "title", p["numero"])
    if hay or verificar or not emision_id:
        print(f"cobranza : {'OK ' + hay[0]['id'] if hay else 'FALTA'}  {p['numero']}")
        return
    pid = _crear(nc.DB_COBRANZAS, {
        "Póliza": _titulo(p["numero"]),
        "Emisiones": {"relation": [{"id": emision_id}]},
        "Estado de Cobranza": {"status": {"name": "Pago hecho - aplicado"}},
        "Monto de Prima": {"number": p["prima"]},
        "Días de atraso": {"number": 0},
        "Periodicidad": {"select": {"name": p["periodicidad"]}},
        "Tipo de Cobro": {"select": {"name": "Cobro Regular"}},
        "Notas Cobranza": _txt(NOTA),
    })
    print(f"cobranza : CREADA {pid}  {p['numero']}")


def main() -> None:
    verificar = "--verificar" in sys.argv
    aid = asesor(verificar)
    cids = [cliente(c, verificar) for c in CLIENTES]
    eids = [poliza(p, cids[p["cliente"]], aid, verificar) for p in POLIZAS]
    cobranza(POLIZAS[0], eids[0], verificar)


if __name__ == "__main__":
    main()

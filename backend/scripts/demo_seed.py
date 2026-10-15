"""Crea (o verifica) el CLIENTE DEMO en Notion para probar a Tommy de punta a punta.

Uso (desde backend/, con el .env de producción):
    python -m scripts.demo_seed            # crea lo que falte (idempotente)
    python -m scripts.demo_seed --verificar  # solo muestra lo que encuentra

Qué crea, todo con "DEMO" en el nombre y datos ficticios:
  - Clientes General: "DEMO María Prueba" con el correo TOMI_DEMO_EMAIL.
  - Emisiones: 2 pólizas ACTIVAS (PLU3 mensual y Gastos Médicos anual) ligadas al cliente.
  - Cobranza: el cobro de la PLU3 con el pago APLICADO.

Cuidados para no ensuciar la operación real:
  - Sin Asesor/Cerrador/Producto/Líder relacionados → no suma cierres, comisiones ni puntos
    de Liga a nadie.
  - Pólizas Activas y cobranza "Pago hecho - aplicado" → no entra en colas de trabajo
    (revisión de emisiones, cobranza por contactar).
  - Sin teléfono: cada tester entra con su propio WhatsApp vía "DEMO <usuario> <clave>".
"""
from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv()

from app.services.tomi import demo  # noqa: E402
from app.services.tomi import notion_client as nc  # noqa: E402

NOTA = "REGISTRO DEMO — datos ficticios para probar a Tommy. No contactar ni modificar."

POLIZAS = [
    {"numero": "DEMO-PLU3-000001", "producto": "PLU3 Plan de Retiro (demo)", "prima": 2500,
     "periodicidad": "Mensual", "emision": "2026-03-01"},
    {"numero": "DEMO-GMM-000002", "producto": "Gastos Médicos Mayores (demo)", "prima": 18000,
     "periodicidad": "Anual", "emision": "2026-01-15"},
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


def cliente(verificar: bool) -> str | None:
    hay = _buscar(nc.DB_CLIENTES, "Correo", "rich_text", demo.email())
    if hay or verificar:
        print(f"cliente  : {'OK ' + hay[0]['id'] if hay else 'FALTA'}  ({demo.email()})")
        return hay[0]["id"] if hay else None
    pid = _crear(nc.DB_CLIENTES, {
        "Nombre del Cliente": _titulo(demo.nombre()),
        "Correo": _txt(demo.email()),
        "Fecha de Nacimiento": {"date": {"start": "1990-05-12"}},
        "Notas General": _txt(NOTA),
    })
    print(f"cliente  : CREADO {pid}")
    return pid


def poliza(p: dict, cliente_id: str | None, verificar: bool) -> str | None:
    hay = _buscar(nc.DB_EMISIONES, "Número de Póliza", "rich_text", p["numero"])
    if hay or verificar or not cliente_id:
        print(f"póliza   : {'OK ' + hay[0]['id'] if hay else 'FALTA'}  {p['numero']}")
        return hay[0]["id"] if hay else None
    pid = _crear(nc.DB_EMISIONES, {
        "Solicitud": _titulo(p["numero"]),
        "Número de Póliza": _txt(p["numero"]),
        "Estado": {"status": {"name": "Activa"}},
        "Tipo de Solicitud": {"select": {"name": "Emisión"}},
        "Periodicidad": {"select": {"name": p["periodicidad"]}},
        "Prima": {"number": p["prima"]},
        "Fecha de Emisión": {"date": {"start": p["emision"]}},
        "Correo Cliente": _txt(demo.email()),
        "Nombre Cliente": _txt(demo.nombre()),
        "Producto (nombre)": _txt(p["producto"]),
        "Notas de Emisión": _txt(NOTA),
        "Clientes General": {"relation": [{"id": cliente_id}]},
    })
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
    cid = cliente(verificar)
    ids = [poliza(p, cid, verificar) for p in POLIZAS]
    cobranza(POLIZAS[0], ids[0], verificar)


if __name__ == "__main__":
    main()

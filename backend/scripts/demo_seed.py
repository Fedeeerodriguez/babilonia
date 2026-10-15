"""Crea (o verifica) el CLIENTE DEMO en Notion, con todo su mundo ficticio.

Uso (desde backend/, con el .env de producción):
    python -m scripts.demo_seed              # crea/completa lo que falte (idempotente)
    python -m scripts.demo_seed --verificar  # solo muestra lo que encuentra

El demo es SOLO un cliente. Todo lo que lo rodea es ficticio y empieza con "DEMO":
  - Clientes General: "DEMO María Prueba" (TOMI_DEMO_EMAIL), el cliente con el que se entra
    por WhatsApp con `DEMO <usuario> <clave>`.
  - Asesores: "DEMO Laura Méndez", su asesora ficticia. Es solo un registro: nadie puede
    entrar como ella (su correo está bloqueado en el clasificador).
  - Productos: "DEMO Plan de Retiro" y "DEMO Gastos Médicos" (fuera del catálogo real:
    `buscar_productos` descarta todo lo que empieza con DEMO).
  - Emisiones: 2 pólizas ACTIVAS de María, con su asesora y sus productos ficticios.
  - Cobranza: el cobro de la PLU3 con el pago APLICADO.

Cuidados para no ensuciar la operación real:
  - Asesora ficticia: Estado "Inactivo", "Eliminado de Avisos" y "Eliminado de Nivel",
    Liga desactivada, sin teléfono ni líder → fuera de rankings, niveles y difusiones.
  - Nada ficticio se relaciona con asesores, líderes ni productos REALES → no suma cierres,
    comisiones, puntos ni bonos a nadie.
  - Pólizas Activas y cobranza "Pago hecho - aplicado" → no entra en colas de trabajo.
"""
from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv(".env")

from app.services.tomi import demo  # noqa: E402
from app.services.tomi import notion_client as nc  # noqa: E402

NOTA = "REGISTRO DEMO — datos ficticios para probar a Tommy. No contactar ni modificar."

PRODUCTOS = [
    {"nombre": "DEMO Plan de Retiro", "tipo": "Producto de Ahorro"},
    {"nombre": "DEMO Gastos Médicos", "tipo": "Seguro de Gastos Médicos"},
]
POLIZAS = [
    {"numero": "DEMO-PLU3-000001", "producto": 0, "prima": 2500, "periodicidad": "Mensual",
     "emision": "2026-03-01"},
    {"numero": "DEMO-GMM-000002", "producto": 1, "prima": 18000, "periodicidad": "Anual",
     "emision": "2026-01-15"},
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


def _rel(page: dict, prop: str) -> list:
    return [r["id"] for r in page["properties"].get(prop, {}).get("relation", [])]


def _asegurar(etiqueta: str, db_id: str, prop: str, tipo: str, valor: str, props: dict,
              verificar: bool) -> str | None:
    """Busca el registro por (prop == valor); si no está, lo crea (salvo --verificar)."""
    hay = _buscar(db_id, prop, tipo, valor)
    if hay:
        print(f"{etiqueta:<9}: OK     {valor}")
        return hay[0]["id"]
    if verificar:
        print(f"{etiqueta:<9}: FALTA  {valor}")
        return None
    pid = _crear(db_id, props)
    print(f"{etiqueta:<9}: CREADO {valor}")
    return pid


def _vincular(etiqueta: str, page_id: str | None, props: dict, verificar: bool) -> None:
    """Completa relaciones/campos que falten en un registro existente."""
    if not page_id:
        return
    page = nc._retry_429(nc._client().pages.retrieve, page_id=page_id)
    faltan = {k: v for k, v in props.items()
              if ("relation" in v and _rel(page, k) != [r["id"] for r in v["relation"]])
              or ("rich_text" in v and "".join(t.get("plain_text", "") for t in
                                               page["properties"].get(k, {}).get("rich_text", []))
                  != v["rich_text"][0]["text"]["content"])}
    if not faltan:
        return
    if verificar:
        print(f"{etiqueta:<9}: sin vincular: {', '.join(faltan)}")
        return
    _actualizar(page_id, faltan)
    print(f"{etiqueta:<9}: vinculado ({', '.join(faltan)})")


def main() -> None:
    v = "--verificar" in sys.argv

    asesora = _asegurar("asesora", nc.DB_ASESORES, "Correo", "rich_text", demo.ASESOR_EMAIL, {
        "Nombre Completo": _titulo(demo.ASESOR_NOMBRE),
        "Primer Nombre": _txt("Laura"),
        "Correo": _txt(demo.ASESOR_EMAIL),
        "Estado de Asesor": {"select": {"name": "Inactivo"}},
        "Eliminado de Avisos": {"checkbox": True},
        "Eliminado de Nivel": {"checkbox": True},
        "Liga Activada": {"checkbox": False},
        "Activación Liga": {"checkbox": False},
    }, v)

    productos = [_asegurar("producto", nc.DB_PRODUCTOS, "Nombre", "title", p["nombre"], {
        "Nombre": _titulo(p["nombre"]),
        "Tipo de producto": {"select": {"name": p["tipo"]}},
        "Tipo de plan": {"select": {"name": "Suscripción"}},
        "Descripción": _txt("Producto FICTICIO del cliente demo. No es parte del catálogo."),
    }, v) for p in PRODUCTOS]

    cliente = _asegurar("cliente", nc.DB_CLIENTES, "Correo", "rich_text", demo.email(), {
        "Nombre del Cliente": _titulo(demo.nombre()),
        "Correo": _txt(demo.email()),
        "Fecha de Nacimiento": {"date": {"start": "1990-05-12"}},
        "Notas General": _txt(NOTA),
    }, v)
    if asesora:
        _vincular("cliente", cliente, {"Asesor": {"relation": [{"id": asesora}]}}, v)

    for p in POLIZAS:
        prod = productos[p["producto"]]
        nombre_prod = PRODUCTOS[p["producto"]]["nombre"]
        props = {
            "Solicitud": _titulo(p["numero"]),
            "Número de Póliza": _txt(p["numero"]),
            "Estado": {"status": {"name": "Activa"}},
            "Tipo de Solicitud": {"select": {"name": "Emisión"}},
            "Periodicidad": {"select": {"name": p["periodicidad"]}},
            "Prima": {"number": p["prima"]},
            "Fecha de Emisión": {"date": {"start": p["emision"]}},
            "Correo Cliente": _txt(demo.email()),
            "Nombre Cliente": _txt(demo.nombre()),
            "Notas de Emisión": _txt(NOTA),
        }
        enlaces = {"Correo Asesor": _txt(demo.ASESOR_EMAIL), "Producto (nombre)": _txt(nombre_prod)}
        if cliente:
            enlaces["Clientes General"] = {"relation": [{"id": cliente}]}
        if asesora:
            enlaces["Asesor"] = {"relation": [{"id": asesora}]}
        if prod:
            enlaces["Producto"] = {"relation": [{"id": prod}]}
        eid = _asegurar("póliza", nc.DB_EMISIONES, "Número de Póliza", "rich_text", p["numero"],
                        {**props, **enlaces}, v) if cliente else None
        _vincular("póliza", eid, enlaces, v)
        if p is POLIZAS[0] and eid:
            _asegurar("cobranza", nc.DB_COBRANZAS, "Póliza", "title", p["numero"], {
                "Póliza": _titulo(p["numero"]),
                "Emisiones": {"relation": [{"id": eid}]},
                "Estado de Cobranza": {"status": {"name": "Pago hecho - aplicado"}},
                "Monto de Prima": {"number": p["prima"]},
                "Días de atraso": {"number": 0},
                "Periodicidad": {"select": {"name": p["periodicidad"]}},
                "Tipo de Cobro": {"select": {"name": "Cobro Regular"}},
                "Notas Cobranza": _txt(NOTA),
            }, v)


if __name__ == "__main__":
    main()

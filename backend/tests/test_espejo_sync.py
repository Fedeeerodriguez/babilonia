"""QA OFFLINE — espejo de Notion: conversión de páginas, carga completa, incremental y webhook.

Sin red: Notion se simula con un http falso y la base con un repo en memoria.
Correr:  pytest -v tests/test_espejo_sync.py
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.espejo.notion_api import NotionAPI
from app.services.espejo.sync import Sincronizador, bases_configuradas, pagina_a_fila

DB_EMI = "aaaaaaaa-0000-0000-0000-000000000001"
DB_CLI = "aaaaaaaa-0000-0000-0000-000000000002"


def pagina(pid, editada, poliza="PLU3-408444", cliente_rel=(), db=DB_EMI, archivada=False):
    return {
        "id": pid, "url": f"https://notion.so/{pid}", "created_time": "2026-10-01T00:00:00.000Z",
        "last_edited_time": editada, "archived": archivada, "parent": {"database_id": db},
        "properties": {
            "Número de Póliza": {"type": "title", "title": [{"plain_text": poliza}]},
            "Correo Cliente": {"type": "email", "email": "ana@mail.com"},
            "Días de Atraso Actuales": {"type": "formula", "formula": {"type": "number", "number": 12}},
            "Cliente": {"type": "relation", "relation": [{"id": r} for r in cliente_rel]},
            "Estado ": {"type": "status", "status": {"name": "Vigente"}},
        },
    }


class HttpFalso:
    """Imita la API de Notion: una base con páginas; registra cada pedido."""

    def __init__(self, paginas, por_pagina=2):
        self.paginas = paginas
        self.por_pagina = por_pagina
        self.pedidos = []
        self.errores = []  # códigos a devolver antes de responder bien

    def __call__(self, metodo, url, cuerpo):
        self.pedidos.append((metodo, url, cuerpo))
        if self.errores:
            return self.errores.pop(0), {"message": "lento"}, {"Retry-After": "0"}
        ruta = url.split("/v1/", 1)[1]
        if ruta.startswith("databases/") and metodo == "GET":
            return 200, {"title": [{"plain_text": "Emisiones"}], "properties": {
                "Número de Póliza": {"type": "title"}, "Cliente": {"type": "relation",
                                                                   "relation": {"database_id": DB_CLI}}}}, {}
        if ruta.startswith("pages/"):
            pid = ruta.split("/")[1]
            for p in self.paginas:
                if p["id"] == pid:
                    return 200, p, {}
            return 404, {"message": "no existe"}, {}
        filas = sorted(self.paginas, key=lambda p: p["last_edited_time"])
        desde = ((cuerpo or {}).get("filter") or {}).get("last_edited_time", {}).get("on_or_after")
        if desde:
            filas = [p for p in filas if p["last_edited_time"] >= desde.replace("+00:00", "Z")]
        ini = int((cuerpo or {}).get("start_cursor") or 0)
        trozo = filas[ini:ini + self.por_pagina]
        mas = ini + self.por_pagina < len(filas)
        return 200, {"results": trozo, "has_more": mas, "next_cursor": str(ini + self.por_pagina) if mas else None}, {}


class RepoMemoria:
    def __init__(self):
        self.bases, self.paginas, self.relaciones, self.pendientes, self.corridas = {}, {}, {}, {}, []

    def upsert_base(self, slug, db_id, titulo, esquema, relaciones):
        self.bases.setdefault(slug, {}).update(slug=slug, db_id=db_id, titulo=titulo, esquema=esquema,
                                               relaciones=relaciones)

    def marcar_base(self, slug, **campos):
        self.bases.setdefault(slug, {"slug": slug}).update(campos)

    def obtener_base(self, slug):
        return self.bases.get(slug)

    def upsert_paginas(self, filas):
        for f in filas:
            self.paginas[f["page_id"]] = f
            self.relaciones[f["page_id"]] = list(f["relaciones"])

    def archivar_faltantes(self, slug, vistos):
        n = 0
        for f in self.paginas.values():
            if f["base_slug"] == slug and not f["archivada"] and f["page_id"] not in vistos:
                f["archivada"] = True
                n += 1
        return n

    def archivar(self, pid):
        if pid in self.paginas:
            self.paginas[pid]["archivada"] = True

    def tomar_pendientes(self, limite):
        return list(self.pendientes)[:limite]

    def quitar_pendiente(self, pid):
        self.pendientes.pop(pid, None)

    def reintentar_pendiente(self, pid):
        self.pendientes[pid] = self.pendientes.get(pid, 0) + 1

    def abrir_corrida(self, tipo, slug):
        self.corridas.append({"tipo": tipo, "slug": slug})
        return len(self.corridas) - 1

    def cerrar_corrida(self, i, paginas, pedidos, error=None):
        self.corridas[i].update(paginas=paginas, pedidos=pedidos, error=error)


def armar(paginas, **kw):
    http = HttpFalso(paginas, **kw)
    repo = RepoMemoria()
    sync = Sincronizador(repo, NotionAPI(token="x", rps=0, http=http), bases={"emisiones": DB_EMI, "clientes": DB_CLI})
    return sync, repo, http


def test_pagina_a_fila_mismo_formato_que_tommy_y_relaciones():
    f = pagina_a_fila(pagina("p1", "2026-10-29T10:00:00.000Z", cliente_rel=["c1", "c2"]), "emisiones")
    assert f["titulo"] == "PLU3-408444" and f["props"]["Correo Cliente"] == "ana@mail.com"
    assert f["props"]["Días de Atraso Actuales"] == 12 and f["props"]["Estado "] == "Vigente"
    assert f["relaciones"] == [("Cliente", "c1"), ("Cliente", "c2")]
    assert "PLU3-408444" in f["texto_busqueda"] and "c1" not in f["texto_busqueda"]
    assert "_id" not in f["props"]
    # El hash solo cambia si cambian los datos.
    assert pagina_a_fila(pagina("p1", "2026-10-30T10:00:00.000Z", cliente_rel=["c1", "c2"]), "emisiones")["hash_props"] \
        == f["hash_props"]
    assert pagina_a_fila(pagina("p1", "2026-10-29T10:00:00.000Z", poliza="PLU3-1"), "emisiones")["hash_props"] \
        != f["hash_props"]


def test_carga_completa_pagina_y_archiva_las_que_ya_no_estan():
    ps = [pagina(f"p{i}", f"2026-10-2{i}T10:00:00.000Z") for i in range(1, 6)]
    sync, repo, http = armar(ps)
    r = sync.carga_completa("emisiones")
    assert r["ok"] and r["paginas"] == 5 and len(repo.paginas) == 5
    b = repo.bases["emisiones"]
    assert b["estado"] == "ok" and b["filas"] == 5 and b["relaciones"] == {"Cliente": "clientes"}
    assert b["ultimo_edit_visto"] == datetime(2026, 10, 25, 10, tzinfo=timezone.utc)
    http.paginas = ps[:3]  # p4 y p5 se borraron en Notion
    assert sync.carga_completa("emisiones")["archivadas"] == 2
    assert repo.paginas["p4"]["archivada"] and not repo.paginas["p1"]["archivada"]
    assert repo.corridas[-1]["pedidos"] == 3  # 1 esquema + 2 páginas de resultados


def test_incremental_trae_solo_lo_editado_con_solape():
    ps = [pagina("p1", "2026-10-29T10:00:00.000Z"), pagina("p2", "2026-10-29T12:00:00.000Z")]
    sync, repo, http = armar(ps)
    sync.carga_completa("emisiones")
    http.paginas = ps + [pagina("p3", "2026-10-29T12:05:00.000Z")]
    http.pedidos.clear()
    r = sync.incremental("emisiones")
    filtro = http.pedidos[0][2]["filter"]["last_edited_time"]["on_or_after"]
    assert filtro.startswith("2026-10-29T11:58")  # 2 min antes de lo último visto
    assert r["ok"] and r["paginas"] == 2 and "p3" in repo.paginas  # p2 (solape) + p3
    assert repo.bases["emisiones"]["ultimo_edit_visto"] == datetime(2026, 10, 29, 12, 5, tzinfo=timezone.utc)


def test_incremental_sin_carga_previa_hace_la_completa():
    sync, repo, _ = armar([pagina("p1", "2026-10-29T10:00:00.000Z")])
    sync.incremental("emisiones")
    assert repo.corridas[0]["tipo"] == "completa" and "p1" in repo.paginas


def test_rate_limit_de_notion_se_reintenta_y_se_cuenta():
    sync, repo, http = armar([pagina("p1", "2026-10-29T10:00:00.000Z")])
    http.errores = [429, 503]
    assert sync.carga_completa("emisiones")["ok"]
    assert sync.api.pedidos == 4  # 2 fallidos + esquema + resultados


def test_error_en_una_base_no_frena_la_ronda():
    sync, repo, http = armar([pagina("p1", "2026-10-29T10:00:00.000Z")])
    http.errores = [400]
    r = sync.ronda()
    assert r["emisiones"]["ok"] is False and repo.bases["emisiones"]["estado"] == "error"
    assert r["clientes"]["ok"] is True


def test_pendientes_del_webhook_se_releen_de_notion():
    ps = [pagina("p1", "2026-10-29T10:00:00.000Z")]
    sync, repo, http = armar(ps)
    repo.pendientes = {"p1": 0, "borrada": 0}
    repo.paginas["borrada"] = {"page_id": "borrada", "base_slug": "emisiones", "archivada": False}
    r = sync.procesar_pendientes()
    assert r["paginas"] == 1 and repo.paginas["p1"]["titulo"] == "PLU3-408444"
    assert repo.paginas["borrada"]["archivada"] and repo.pendientes == {}


def test_bases_configuradas_lee_todas_las_notion_db():
    env = {"NOTION_DB_EMISIONES": "x1", "NOTION_DB_CLIENTES_PLU3": " x2 ", "NOTION_DB_VACIA": "", "OTRA": "y"}
    assert bases_configuradas(env) == {"emisiones": "x1", "clientes_plu3": "x2"}


def test_corte_de_red_se_reintenta():
    sync, repo, http = armar([pagina("p1", "2026-10-29T10:00:00.000Z")])
    llamadas = []
    real = sync.api._http

    def con_corte(metodo, url, cuerpo):
        llamadas.append(url)
        if len(llamadas) == 2:
            return 503, {"message": "red: IncompleteRead"}, {"Retry-After": "0"}
        return real(metodo, url, cuerpo)
    sync.api._http = con_corte
    assert sync.carga_completa("emisiones")["ok"] and "p1" in repo.paginas

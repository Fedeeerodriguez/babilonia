"""Acceso al esquema notion_espejo (backend/sql/notion_espejo.sql) en ESPEJO_DATABASE_URL.

El worker usa el puerto 5432 (sesión) para cargas largas; las lecturas del backend pueden ir por el
6543 (pooler de transacción). psycopg2 no usa prepared statements del lado del servidor, así que
funciona con los dos. Una sola conexión por proceso: el pooler de Supabase tiene pocas.
"""
from __future__ import annotations

import os
from typing import Iterable, Optional

import psycopg2
from psycopg2.extras import Json, RealDictCursor, execute_values

ESQUEMA_SQL = os.path.join(os.path.dirname(__file__), "..", "..", "..", "sql", "notion_espejo.sql")


def dsn() -> str:
    return os.getenv("ESPEJO_DATABASE_URL", "").replace("postgresql+psycopg2", "postgresql")


class RepoEspejo:
    def __init__(self, url: Optional[str] = None):
        self.url = url or dsn()
        if not self.url:
            raise RuntimeError("ESPEJO_DATABASE_URL no configurado")
        self._conn = None

    @property
    def conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.url, connect_timeout=20)
            self._conn.autocommit = True
        return self._conn

    def _ejecutar(self, sql: str, args=None, filas: bool = False):
        for intento in (1, 2):  # el pooler corta conexiones ociosas: se reconecta una vez
            try:
                with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, args)
                    return cur.fetchall() if filas else cur.rowcount
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                if intento == 2:
                    raise
                self._conn = None

    def crear_esquema(self) -> None:
        with open(ESQUEMA_SQL, encoding="utf-8") as f:
            self._ejecutar(f.read())

    # ------------------------------------------------------------------ bases
    def upsert_base(self, slug: str, db_id: str, titulo: str, esquema: dict, relaciones: dict) -> None:
        self._ejecutar(
            "insert into notion_espejo.bases (slug, db_id, titulo, esquema, relaciones) values (%s,%s,%s,%s,%s) "
            "on conflict (slug) do update set db_id=excluded.db_id, titulo=excluded.titulo, "
            "esquema=excluded.esquema, relaciones=excluded.relaciones, actualizado_en=now()",
            (slug, db_id, titulo, Json(esquema), Json(relaciones)))

    def marcar_base(self, slug: str, **campos) -> None:
        if not campos:
            return
        sets = ", ".join(f"{k}=%s" for k in campos)
        self._ejecutar(f"update notion_espejo.bases set {sets}, actualizado_en=now() where slug=%s",
                       (*campos.values(), slug))

    def obtener_base(self, slug: str) -> Optional[dict]:
        r = self._ejecutar("select * from notion_espejo.bases where slug=%s", (slug,), filas=True)
        return dict(r[0]) if r else None

    def listar_bases(self) -> list[dict]:
        return [dict(r) for r in self._ejecutar("select slug, titulo, filas, estado, error, ultimo_sync, "
                                                "ultimo_edit_visto, ultima_carga from notion_espejo.bases "
                                                "order by slug", filas=True)]

    # ------------------------------------------------------------------ páginas
    def upsert_paginas(self, filas: list[dict]) -> None:
        if not filas:
            return
        valores = [(f["page_id"], f["base_slug"], f["titulo"], Json(f["props"]), Json(f["props_raw"]),
                    f["texto_busqueda"], f["url"], f["created_time"], f["last_edited_time"], f["archivada"],
                    f["hash_props"]) for f in filas]
        with self.conn.cursor() as cur:
            execute_values(cur,
                "insert into notion_espejo.paginas (page_id, base_slug, titulo, props, props_raw, texto_busqueda, "
                "url, created_time, last_edited_time, archivada, hash_props) values %s "
                "on conflict (page_id) do update set base_slug=excluded.base_slug, titulo=excluded.titulo, "
                "props=excluded.props, props_raw=excluded.props_raw, texto_busqueda=excluded.texto_busqueda, "
                "url=excluded.url, last_edited_time=excluded.last_edited_time, archivada=excluded.archivada, "
                "version=notion_espejo.paginas.version + (notion_espejo.paginas.hash_props is distinct from "
                "excluded.hash_props)::int, hash_props=excluded.hash_props, synced_at=now()", valores)
            ids = [f["page_id"] for f in filas]
            cur.execute("delete from notion_espejo.relaciones where desde_page = any(%s::uuid[])", (ids,))
            rel = [(f["page_id"], prop, destino) for f in filas for prop, destino in f["relaciones"]]
            if rel:
                execute_values(cur, "insert into notion_espejo.relaciones (desde_page, propiedad, hacia_page) "
                                    "values %s on conflict do nothing", rel)

    def archivar_faltantes(self, slug: str, vistos: Iterable[str]) -> int:
        """Las páginas de la base que no vinieron en la carga completa quedan archivadas."""
        return self._ejecutar("update notion_espejo.paginas set archivada=true, synced_at=now() "
                              "where base_slug=%s and not archivada and not (page_id = any(%s::uuid[]))",
                              (slug, list(vistos)))

    def archivar(self, page_id: str) -> None:
        self._ejecutar("update notion_espejo.paginas set archivada=true, synced_at=now() where page_id=%s",
                       (page_id,))

    # ------------------------------------------------------------------ webhook
    def encolar_pendiente(self, page_id: str, evento: Optional[str]) -> None:
        self._ejecutar("insert into notion_espejo.pendientes (page_id, evento) values (%s,%s) "
                       "on conflict (page_id) do update set evento=excluded.evento, recibido_en=now()",
                       (page_id, evento))

    def tomar_pendientes(self, limite: int) -> list[str]:
        r = self._ejecutar("select page_id from notion_espejo.pendientes where intentos < 5 "
                           "order by recibido_en limit %s", (limite,), filas=True)
        return [str(x["page_id"]) for x in r]

    def quitar_pendiente(self, page_id: str) -> None:
        self._ejecutar("delete from notion_espejo.pendientes where page_id=%s", (page_id,))

    def reintentar_pendiente(self, page_id: str) -> None:
        self._ejecutar("update notion_espejo.pendientes set intentos=intentos+1 where page_id=%s", (page_id,))

    # ------------------------------------------------------------------ ajustes
    def guardar_ajuste(self, clave: str, valor: str) -> None:
        self._ejecutar("insert into notion_espejo.ajustes (clave, valor) values (%s,%s) on conflict (clave) "
                       "do update set valor=excluded.valor, actualizado_en=now()", (clave, valor))

    def leer_ajuste(self, clave: str) -> Optional[str]:
        r = self._ejecutar("select valor from notion_espejo.ajustes where clave=%s", (clave,), filas=True)
        return r[0]["valor"] if r else None

    # ------------------------------------------------------------------ corridas
    def abrir_corrida(self, tipo: str, slug: Optional[str]) -> int:
        r = self._ejecutar("insert into notion_espejo.corridas (tipo, base_slug) values (%s,%s) returning id",
                           (tipo, slug), filas=True)
        return int(r[0]["id"])

    def cerrar_corrida(self, corrida: int, paginas: int, pedidos: int, error: Optional[str] = None) -> None:
        self._ejecutar("update notion_espejo.corridas set fin=now(), paginas=%s, pedidos=%s, error=%s where id=%s",
                       (paginas, pedidos, error, corrida))

    def pedidos_ultima_hora(self) -> int:
        r = self._ejecutar("select coalesce(sum(pedidos),0) as n from notion_espejo.corridas "
                           "where inicio > now() - interval '1 hour'", filas=True)
        return int(r[0]["n"])

    def contar_paginas(self) -> dict:
        r = self._ejecutar("select base_slug, count(*) filter (where not archivada) as vivas, count(*) as total "
                           "from notion_espejo.paginas group by 1", filas=True)
        return {x["base_slug"]: {"vivas": x["vivas"], "total": x["total"]} for x in r}


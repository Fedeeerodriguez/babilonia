"""Sincronización Notion → espejo.

- `carga_completa(slug)`: baja todas las páginas de la base, las guarda y marca como archivadas las
  que ya no vienen (borradas o archivadas en Notion).
- `incremental(slug)`: solo las editadas desde `ultimo_edit_visto` (con 2 min de solape por la
  deriva de reloj de Notion). Es lo que corre cada 2 minutos.
- `procesar_pendientes()`: las páginas que avisó el webhook; se vuelven a leer de Notion (el aviso
  nunca se toma como dato).

La conversión de página → fila reutiliza `notion_client._flatten_props`, así el espejo devuelve
exactamente el mismo formato que hoy usa Tommy.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from app.services.tomi.notion_client import _flatten_props

from .notion_api import NotionAPI

log = logging.getLogger(__name__)

SOLAPE = timedelta(minutes=2)
_META = ("_id", "_url", "_title")


def bases_configuradas(env: Optional[dict] = None) -> dict[str, str]:
    """{slug: db_id} de todas las variables NOTION_DB_* con valor (slug = sufijo en minúsculas)."""
    env = os.environ if env is None else env
    return {k[len("NOTION_DB_"):].lower(): v.strip() for k, v in env.items()
            if k.startswith("NOTION_DB_") and v and v.strip()}


def _texto(v) -> list[str]:
    if v is None or isinstance(v, bool):
        return []
    if isinstance(v, (str, int, float)):
        return [str(v)]
    if isinstance(v, dict):
        return [x for k in ("name", "start") if v.get(k) for x in [str(v[k])]]
    if isinstance(v, list):
        return [x for i in v for x in _texto(i)]
    return []


def pagina_a_fila(page: dict, slug: str) -> dict:
    plano = _flatten_props(page)
    props = {k: v for k, v in plano.items() if k not in _META}
    tipos = {n: p.get("type") for n, p in (page.get("properties") or {}).items()}
    relaciones = [(n, destino) for n, t in tipos.items() if t == "relation"
                  for destino in (props.get(n) or []) if destino]
    texto = " ".join(t for n, v in props.items() if tipos.get(n) not in ("relation", "files")
                     for t in _texto(v))
    canon = json.dumps(props, sort_keys=True, ensure_ascii=False, default=str)
    return {
        "page_id": page["id"], "base_slug": slug, "titulo": plano.get("_title"), "props": props,
        "props_raw": page.get("properties") or {}, "texto_busqueda": texto[:20000] or None,
        "url": page.get("url"), "created_time": page.get("created_time"),
        "last_edited_time": page.get("last_edited_time"),
        "archivada": bool(page.get("archived") or page.get("in_trash")),
        "hash_props": hashlib.sha256(canon.encode()).hexdigest()[:32], "relaciones": relaciones,
    }


def _esquema(meta: dict, ids_a_slug: dict[str, str]) -> tuple[dict, dict]:
    props = meta.get("properties") or {}
    esquema = {n: p.get("type") for n, p in props.items()}
    rel = {}
    for n, p in props.items():
        if p.get("type") == "relation":
            destino = (p.get("relation") or {}).get("database_id", "").replace("-", "")
            rel[n] = ids_a_slug.get(destino, destino)
    return esquema, rel


class Sincronizador:
    def __init__(self, repo, api: Optional[NotionAPI] = None, bases: Optional[dict[str, str]] = None):
        self.repo = repo
        self.api = api or NotionAPI()
        self.bases = bases if bases is not None else bases_configuradas()
        self._ids_a_slug = {v.replace("-", ""): k for k, v in self.bases.items()}

    def _guardar(self, slug: str, paginas: Iterable[dict], lote: int = 200) -> tuple[int, Optional[str], set]:
        n, ultimo, vistos, buf = 0, None, set(), []
        for p in paginas:
            fila = pagina_a_fila(p, slug)
            buf.append(fila)
            vistos.add(str(fila["page_id"]))
            if fila["last_edited_time"] and (ultimo is None or fila["last_edited_time"] > ultimo):
                ultimo = fila["last_edited_time"]
            if len(buf) >= lote:
                self.repo.upsert_paginas(buf)
                n += len(buf)
                buf = []
        if buf:
            self.repo.upsert_paginas(buf)
            n += len(buf)
        return n, ultimo, vistos

    def _correr(self, tipo: str, slug: str, fn) -> dict:
        antes = self.api.pedidos
        corrida = self.repo.abrir_corrida(tipo, slug)
        try:
            r = fn()
            self.repo.cerrar_corrida(corrida, r.get("paginas", 0), self.api.pedidos - antes)
            return {"ok": True, **r}
        except Exception as ex:  # noqa: BLE001 — una base rota no frena a las demás
            log.exception("espejo: %s de %s falló", tipo, slug)
            self.repo.cerrar_corrida(corrida, 0, self.api.pedidos - antes, error=str(ex)[:500])
            self.repo.marcar_base(slug, estado="error", error=str(ex)[:500])
            return {"ok": False, "error": str(ex)}

    def carga_completa(self, slug: str) -> dict:
        db_id = self.bases[slug]

        def hacer():
            meta = self.api.base(db_id)
            esquema, rel = _esquema(meta, self._ids_a_slug)
            titulo = "".join(x.get("plain_text", "") for x in meta.get("title") or [])
            self.repo.upsert_base(slug, db_id, titulo, esquema, rel)
            n, ultimo, vistos = self._guardar(slug, self.api.paginas(db_id))
            archivadas = self.repo.archivar_faltantes(slug, vistos)
            ahora = datetime.now(timezone.utc)
            self.repo.marcar_base(slug, estado="ok", error=None, filas=len(vistos), ultimo_edit_visto=_iso(ultimo) if ultimo else None,
                                  ultimo_sync=ahora, ultima_carga=ahora)
            return {"paginas": n, "archivadas": archivadas}
        return self._correr("completa", slug, hacer)

    def incremental(self, slug: str) -> dict:
        db_id = self.bases[slug]
        base = self.repo.obtener_base(slug)
        if not base or not base.get("ultimo_edit_visto"):
            return self.carga_completa(slug)

        def hacer():
            desde = _iso(base["ultimo_edit_visto"]) - SOLAPE
            n, ultimo, _ = self._guardar(slug, self.api.paginas(db_id, desde.isoformat().replace("+00:00", "Z")))
            campos = {"estado": "ok", "error": None, "ultimo_sync": datetime.now(timezone.utc)}
            if ultimo:
                campos["ultimo_edit_visto"] = max(_iso(ultimo), _iso(base["ultimo_edit_visto"]))
            self.repo.marcar_base(slug, **campos)
            return {"paginas": n}
        return self._correr("incremental", slug, hacer)

    def procesar_pendientes(self, limite: int = 50) -> dict:
        hechos = 0
        for pid in self.repo.tomar_pendientes(limite):
            try:
                page = self.api.pagina(pid)
            except Exception as ex:  # noqa: BLE001
                if "404" in str(ex):          # borrada o sin acceso: se archiva
                    self.repo.archivar(pid)
                    self.repo.quitar_pendiente(pid)
                else:
                    self.repo.reintentar_pendiente(pid)
                continue
            db = ((page.get("parent") or {}).get("database_id") or "").replace("-", "")
            slug = self._ids_a_slug.get(db)
            if slug:
                self.repo.upsert_paginas([pagina_a_fila(page, slug)])
                hechos += 1
            self.repo.quitar_pendiente(pid)
        return {"paginas": hechos}

    def ronda(self) -> dict:
        """Lo que corre el worker cada 2 minutos: avisos del webhook primero, después el incremental."""
        res = {"pendientes": self.procesar_pendientes()}
        for slug in self.bases:
            res[slug] = self.incremental(slug)
        return res


def _iso(v) -> datetime:
    if isinstance(v, datetime):
        return v
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))

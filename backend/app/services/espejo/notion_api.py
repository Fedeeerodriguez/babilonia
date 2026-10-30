"""Pedidos a la API de Notion para el espejo, con un límite global de ~3 por segundo (el de Notion) y
conteo de pedidos, así el sincronizador nunca puede quemar la cuota sin que se vea."""
from __future__ import annotations

import http.client
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Iterator, Optional

log = logging.getLogger(__name__)

NOTION_VERSION = "2022-06-28"
PEDIDOS_POR_SEGUNDO = float(os.getenv("ESPEJO_NOTION_RPS", "2.5"))  # Notion permite 3; dejamos margen


class NotionAPI:
    def __init__(self, token: Optional[str] = None, rps: float = PEDIDOS_POR_SEGUNDO, http=None):
        self.token = token if token is not None else os.getenv("NOTION_TOKEN", "")
        self.intervalo = 1.0 / rps if rps > 0 else 0.0
        self._http = http or self._urllib
        self._lock = threading.Lock()
        self._ultimo = 0.0
        self.pedidos = 0

    def _urllib(self, metodo: str, url: str, cuerpo: Optional[dict]) -> tuple[int, dict, dict]:
        req = urllib.request.Request(
            url, method=metodo, data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Notion-Version": NOTION_VERSION,
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read()), dict(r.headers)
        except urllib.error.HTTPError as e:
            try:
                cuerpo_err = json.loads(e.read())
            except Exception:  # noqa: BLE001
                cuerpo_err = {}
            return e.code, cuerpo_err, dict(e.headers or {})
        except (http.client.IncompleteRead, urllib.error.URLError, TimeoutError, ConnectionError) as e:
            # Corte de red a mitad de la respuesta (pasa con bases grandes): se reintenta como un 503.
            return 503, {"message": f"red: {type(e).__name__}"}, {}

    def _esperar_turno(self) -> None:
        with self._lock:
            espera = self.intervalo - (time.monotonic() - self._ultimo)
            if espera > 0:
                time.sleep(espera)
            self._ultimo = time.monotonic()

    def pedir(self, metodo: str, ruta: str, cuerpo: Optional[dict] = None, intentos: int = 6) -> dict:
        for i in range(intentos):
            self._esperar_turno()
            self.pedidos += 1
            estado, datos, cab = self._http(metodo, f"https://api.notion.com/v1/{ruta}", cuerpo)
            if estado < 300:
                return datos
            if estado in (429, 500, 502, 503, 504) and i < intentos - 1:
                espera = float((cab or {}).get("Retry-After") or min(2 ** i, 30))
                log.warning("Notion %s en %s; reintento %d en %.1fs", estado, ruta, i + 1, espera)
                time.sleep(espera)
                continue
            raise RuntimeError(f"Notion {estado} en {ruta}: {(datos or {}).get('message', '')}"[:300])
        raise RuntimeError(f"Notion sin respuesta en {ruta}")

    def base(self, db_id: str) -> dict:
        return self.pedir("GET", f"databases/{db_id}")

    def pagina(self, page_id: str) -> dict:
        return self.pedir("GET", f"pages/{page_id}")

    def paginas(self, db_id: str, editadas_desde: Optional[str] = None) -> Iterator[dict]:
        """Todas las páginas de la base (o las editadas desde una fecha ISO), de a 100."""
        cuerpo: dict[str, Any] = {"page_size": 100,
                                  "sorts": [{"timestamp": "last_edited_time", "direction": "ascending"}]}
        if editadas_desde:
            cuerpo["filter"] = {"timestamp": "last_edited_time",
                                "last_edited_time": {"on_or_after": editadas_desde}}
        cursor = None
        while True:
            if cursor:
                cuerpo["start_cursor"] = cursor
            r = self.pedir("POST", f"databases/{db_id}/query", cuerpo)
            yield from r.get("results", [])
            if not r.get("has_more"):
                return
            cursor = r.get("next_cursor")

"""Worker del espejo: corre aparte de la API (servicio espejo-worker en EasyPanel, misma imagen).

    python -m app.services.espejo.worker              # bucle: ronda cada ESPEJO_INTERVALO_SEG (120)
    python -m app.services.espejo.worker --esquema    # crea/actualiza el esquema notion_espejo y sale
    python -m app.services.espejo.worker --completa   # carga completa de todas las bases y sale
    python -m app.services.espejo.worker --completa emisiones cobranzas

Cada noche (ESPEJO_HORA_COMPLETA, hora UTC, default 8 = 2 a.m. de México) rehace la carga completa:
detecta borrados y refresca fórmulas y rollups que Notion recalcula sin marcar la página como editada.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from .repo import RepoEspejo  # noqa: E402
from .sync import Sincronizador  # noqa: E402

log = logging.getLogger("espejo")


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    repo = RepoEspejo()
    if "--esquema" in argv:
        repo.crear_esquema()
        log.info("esquema notion_espejo listo")
        return 0
    sync = Sincronizador(repo)
    if "--completa" in argv:
        pedidas = [a for a in argv if not a.startswith("--")] or list(sync.bases)
        for slug in pedidas:
            t0 = time.time()
            r = sync.carga_completa(slug)
            log.info("completa %-28s %s (%.0fs, %d pedidos acumulados)", slug, r, time.time() - t0, sync.api.pedidos)
        return 0

    intervalo = int(os.getenv("ESPEJO_INTERVALO_SEG", "120"))
    hora_completa = int(os.getenv("ESPEJO_HORA_COMPLETA", "8"))
    ultima_completa = None
    log.info("espejo: %d bases, ronda cada %ds, carga completa diaria a las %02d UTC",
             len(sync.bases), intervalo, hora_completa)
    while True:
        t0 = time.time()
        hoy = datetime.now(timezone.utc)
        try:
            if hoy.hour == hora_completa and ultima_completa != hoy.date():
                for slug in sync.bases:
                    sync.carga_completa(slug)
                ultima_completa = hoy.date()
            else:
                r = sync.ronda()
                cambios = sum(v.get("paginas", 0) for v in r.values() if isinstance(v, dict))
                errores = [k for k, v in r.items() if isinstance(v, dict) and v.get("ok") is False]
                log.info("ronda: %d páginas actualizadas, %d pedidos a Notion%s", cambios, sync.api.pedidos,
                         f", errores en {errores}" if errores else "")
        except Exception:  # noqa: BLE001 — el worker no se cae: reintenta en la próxima ronda
            log.exception("espejo: la ronda falló")
        time.sleep(max(5, intervalo - (time.time() - t0)))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Verifica el espejo contra Notion (F1). Solo lee. No imprime datos de personas.

  python scripts/verificar_espejo.py              # conteos por base + muestra de 50 páginas
  python scripts/verificar_espejo.py --muestra 200

1. Conteo: páginas vivas en el espejo vs. páginas que devuelve Notion hoy, por base.
2. Muestra: N páginas al azar del espejo, se releen de Notion y se comparan las propiedades
   aplanadas. Las fórmulas que dependen de la fecha (p. ej. "Días de Atraso Actuales") pueden
   diferir si la página se copió otro día: se informan aparte.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app.services.espejo.notion_api import NotionAPI  # noqa: E402
from app.services.espejo.repo import RepoEspejo  # noqa: E402
from app.services.espejo.sync import bases_configuradas, pagina_a_fila  # noqa: E402


def main() -> int:
    n_muestra = int(sys.argv[sys.argv.index("--muestra") + 1]) if "--muestra" in sys.argv else 50
    repo, api = RepoEspejo(), NotionAPI()
    bases = bases_configuradas()
    espejo = repo.contar_paginas()
    print(f"{'base':28s} {'notion':>7s} {'espejo':>7s}")
    mal = 0
    for slug, db_id in sorted(bases.items()):
        try:
            en_notion = sum(1 for _ in api.paginas(db_id))
        except RuntimeError as ex:  # p. ej. Notion no puede calcular una fórmula de la base
            print(f"{slug:28s}  Notion no la devuelve: {str(ex)[-80:]}", flush=True)
            continue
        vivas = espejo.get(slug, {}).get("vivas", 0)
        marca = "" if en_notion == vivas else "  ← distinto"
        mal += bool(marca)
        print(f"{slug:28s} {en_notion:7d} {vivas:7d}{marca}", flush=True)

    filas = repo._ejecutar("select page_id, base_slug, props, last_edited_time from notion_espejo.paginas "
                           "where not archivada", filas=True)
    muestra = random.sample(filas, min(n_muestra, len(filas)))
    iguales, por_fecha, editadas, distintas = 0, 0, 0, []
    tipos_cache: dict[str, dict] = {}
    for f in muestra:
        nueva = pagina_a_fila(api.pagina(str(f["page_id"])), f["base_slug"])
        guardadas = f["props"] if isinstance(f["props"], dict) else json.loads(f["props"])
        dif = [k for k in set(guardadas) | set(nueva["props"])
               if json.dumps(guardadas.get(k), sort_keys=True, default=str)
               != json.dumps(nueva["props"].get(k), sort_keys=True, default=str)]
        if not dif:
            iguales += 1
            continue
        if str(nueva["last_edited_time"]) > f["last_edited_time"].isoformat().replace("+00:00", ".000Z"):
            editadas += 1  # alguien la editó después de copiarla: la toma el incremental
            continue
        if f["base_slug"] not in tipos_cache:
            tipos_cache[f["base_slug"]] = (repo.obtener_base(f["base_slug"]) or {}).get("esquema") or {}
        tipos = tipos_cache[f["base_slug"]]
        if all(tipos.get(k) in ("formula", "rollup") for k in dif):
            por_fecha += 1  # fórmulas/rollups que Notion recalculó (se refrescan en la carga nocturna)
        else:
            distintas.append((f["base_slug"], sorted(dif)[:5]))
    print(f"\nmuestra {len(muestra)}: {iguales} iguales · {por_fecha} solo con fórmulas/rollups recalculados · "
          f"{editadas} editadas después de copiar · {len(distintas)} distintas")
    for slug, campos in distintas:
        print(f"  {slug}: {campos}")
    print(f"\nbases con conteo distinto: {mal} · pedidos a Notion: {api.pedidos}")
    return 1 if (mal or distintas) else 0


if __name__ == "__main__":
    sys.exit(main())

"""Runner QA standalone — NO requiere pytest.

Descubre y ejecuta todas las funciones `test_*` de los módulos de test, captura
PASS / FAIL / SKIP y arma un reporte legible con resumen final.

Uso (desde backend/):
    venv/Scripts/python.exe tests/run_qa.py            # offline + live
    venv/Scripts/python.exe tests/run_qa.py --offline  # solo offline (sin red)

Salida ASCII (segura para la consola de Windows).
"""
from __future__ import annotations

import importlib
import os
import sys
import time
import traceback

# Asegurar que 'app' y 'tests' sean importables corriendo desde backend/
BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from tests._qautil import Skipped  # noqa: E402

OFFLINE_MODULES = ["tests.test_tomi_offline"]
LIVE_MODULES = ["tests.test_tomi_rag_live"]


def _is_skip(exc: BaseException) -> bool:
    return isinstance(exc, Skipped) or type(exc).__name__ in ("Skipped", "Skipped_")


def run_module(modname: str, results: list) -> None:
    try:
        mod = importlib.import_module(modname)
    except Exception as e:
        results.append((modname, "<import>", "FAIL", f"no se pudo importar: {e}", 0.0))
        return
    fns = sorted(n for n in dir(mod) if n.startswith("test_") and callable(getattr(mod, n)))
    for name in fns:
        fn = getattr(mod, name)
        t0 = time.time()
        try:
            fn()
            results.append((modname, name, "PASS", "", (time.time() - t0) * 1000))
        except AssertionError as e:
            results.append((modname, name, "FAIL", str(e) or "assert falló", (time.time() - t0) * 1000))
        except BaseException as e:  # noqa: BLE001
            if _is_skip(e):
                results.append((modname, name, "SKIP", str(e), (time.time() - t0) * 1000))
            else:
                tb = traceback.format_exc().strip().splitlines()[-1]
                results.append((modname, name, "FAIL", f"ERROR: {tb}", (time.time() - t0) * 1000))


def main() -> int:
    only_offline = "--offline" in sys.argv
    modules = list(OFFLINE_MODULES) + ([] if only_offline else LIVE_MODULES)

    results: list = []
    print("=" * 68)
    print(" PAQUETE QA TOMI - resultados")
    print("=" * 68)
    for m in modules:
        run_module(m, results)

    # Detalle
    grupo_actual = None
    for modname, name, status, msg, ms in results:
        if modname != grupo_actual:
            grupo_actual = modname
            etiqueta = "OFFLINE" if "offline" in modname else "LIVE (RAG)"
            print(f"\n[{etiqueta}]  {modname}")
        linea = f"  [{status}] {name} ({ms:.0f} ms)"
        if status != "PASS" and msg:
            linea += f"\n         -> {msg}"
        print(linea)

    # Resumen
    n_pass = sum(1 for r in results if r[2] == "PASS")
    n_fail = sum(1 for r in results if r[2] == "FAIL")
    n_skip = sum(1 for r in results if r[2] == "SKIP")
    print("\n" + "=" * 68)
    print(f" RESUMEN:  {n_pass} PASS   {n_fail} FAIL   {n_skip} SKIP   (total {len(results)})")
    print("=" * 68)
    if n_skip and not only_offline:
        print(" Nota: los SKIP de LIVE ocurren si faltan DOCUMENTS_DATABASE_URL / OPENAI_API_KEY.")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())

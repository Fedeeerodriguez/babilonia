# Paquete QA — Tomi/Babilonia

Tests de las funciones del bot. Dos capas:

- **OFFLINE** (`test_tomi_offline.py`) — deterministas, sin red ni credenciales.
  Clasificador de email, ruteo por keywords, taxonomía `categoria→clave`, selección
  de días de atraso (vivo vs guardado), extracción regex y detección de intención.
- **LIVE (RAG)** (`test_tomi_rag_live.py`) — pegan a Supabase pgvector + OpenAI.
  Integridad de la metadata, filtro por `clave`, Elite alcanzable, desambiguación
  Plus/Educación. Se **saltean** solos si faltan `DOCUMENTS_DATABASE_URL` /
  `OPENAI_API_KEY` en `backend/.env`.

## Cómo correr

Desde `backend/`:

```bash
# Runner standalone (NO necesita pytest) — recomendado
PYTHONPATH=. venv/Scripts/python.exe tests/run_qa.py            # offline + live
PYTHONPATH=. venv/Scripts/python.exe tests/run_qa.py --offline  # solo offline (sin red)

# O con pytest, si está instalado
pytest -v tests/
```

El runner imprime PASS/FAIL/SKIP por test y un resumen final. Sale con código != 0
si algún test falla (sirve para CI).

## Qué cubre cada test

| Test | Verifica |
|---|---|
| `test_atraso_*` | `pick_dias_atraso` prioriza el valor VIVO; respeta 0 (regularizado); cae al guardado si el vivo es None/"" |
| `test_keywords_*` | El clasificador rutea cada producto; **Elite** se detecta (agregado en el fix) |
| `test_categoria_a_clave_*` | Toda categoría válida tiene su clave Allianz mapeada |
| `test_extraer_*` / `test_detectar_intent_*` | Regex de email/póliza/nombre e intención (cobranza/tickets/calendly/daf/productos) |
| `test_rag_filtro_clave_alcanza_elite` | El fix: `categoria='elite'` trae la ficha (antes = 0 chunks) |
| `test_rag_desambiguacion_top_es_ficha_curada` | La ficha curada gana en "diferencia Plus vs Educación" |
| `test_rag_metadata_integridad_categoria` | 0 registros sin `categoria` en el RAG |

> Los tests LIVE leen la contraseña del RAG de `backend/.env`
> (`DOCUMENTS_DATABASE_URL`). Si están en SKIP por auth, revisá que esa contraseña
> esté vigente.

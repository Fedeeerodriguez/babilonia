# Plan de estabilidad — Tomi

Objetivo: que Tomi responda de forma constante y degrade con gracia cuando una
dependencia externa (Notion, OpenAI, DB) falla, en vez de caerse o quedar mudo.

## ✅ P0 — Estabilidad básica (HECHO)

- [x] **Multi-worker + timeouts en uvicorn** (`run.py`): `WEB_CONCURRENCY` workers en
      prod + `timeout_keep_alive`. Un request lento ya no congela todo el backend.
- [x] **Timeout en OpenAI** (30s, antes 600s) + `max_retries` en los 5 sitios que
      crean clientes (agente, agente_memorias, memorias, documents, agent).
- [x] **Timeout en Notion** (`timeout_ms`) en el cliente + fix del último intento de
      `_retry_429` (ya no deja escapar la excepción cruda).
- [x] **Degradación a 200 en `/api/tomi/*`** vía `TomiSafeRoute`: ante fallo inesperado
      devuelve `{"results": [], "error": ...}` con 200, así n8n siempre puede responder.
      Respeta 401/400/422.
- [x] **Handler global de excepciones** en FastAPI: ningún 500 sale sin loguear.
- [x] **Pool de DB configurado** en ambas conexiones (`pool_size`, `max_overflow`,
      `pool_recycle`, `pool_timeout`) — antes default 5, se agotaba en picos.

Env vars nuevas (todas opcionales, ver `backend/.env.example`): `WEB_CONCURRENCY`,
`KEEP_ALIVE`, `OPENAI_TIMEOUT`, `OPENAI_MAX_RETRIES`, `NOTION_TIMEOUT_MS`,
`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE`, `DB_POOL_TIMEOUT`.

## ✅ P1 — Robustez de n8n (HECHO)

- [x] **Lock real anti-doble-disparo** (`tomi_trigger_23h.json`): la query ahora hace
      *claim atómico* en `tomi_locks` con `INSERT ... ON CONFLICT DO NOTHING RETURNING`,
      así dos ticks simultáneos no disparan dos respuestas. Se agregó nodo
      **Limpiar locks viejos** (borra locks > 2h → permite reintento si un disparo quedó colgado).
- [x] **Retry + timeout en `Disparar Tomi`**: timeout 30s (antes 60s con `neverError`),
      3 reintentos. Si falla definitivamente, una rama de error **libera el lock** para
      reintentar en el próximo tick.
- [x] **Ingesta tolerante a fallos** (`actualizacion_contexto_wati.json`): los 6 nodos
      Postgres tienen `retryOnFail` (3 intentos) + `onError: continue`, así un hipo de la
      DB no tira toda la ingesta.
- [x] **WATI multimedia por `$env`** (`tomi_wati_multimedia.json`): URLs/token ya no
      hardcodeados (`$env.WATI_SERVER` / `$env.WATI_TOKEN`), descargas con timeout 20s +
      3 reintentos, y `Normalizar mensaje` ya no devuelve vacío en silencio.

Env vars nuevas en n8n: `WATI_SERVER`, `WATI_TOKEN` (además de `TOMI_API_URL`, `TOMI_INTERNAL_KEY`).
Pendiente de setup manual: reemplazar la credencial Postgres `REEMPLAZAR_POR_CREDENCIAL_SUPABASE`
en los 3 nodos del trigger (no se puede dejar resuelto en el JSON).

## 🟡 P2 — Observabilidad (parcial)
- [x] **`/health/ready`** (`routers/health.py`): chequea las 2 DBs (con latencia) +
      config de Notion/OpenAI. Devuelve **503** si una DB está caída → un monitor
      (EasyPanel/uptime) puede alertar. `/health` queda como liveness simple.
- [x] **Caché de Notion más agresivo**: TTL 90→300s, tamaño 1000→2000 y eviction
      **LRU** (antes FIFO ingenua que descartaba lo más consultado). Stats ya expuestas
      en `/api/tomi/cache/stats`.
- [ ] Alerta a un canal (Slack/WhatsApp) ante fallos — requiere webhook del cliente.
      Recomendado: apuntar un uptime monitor a `/health/ready`.

## 🟢 P3 — Resiliencia avanzada (pendiente)
- [ ] Circuit breaker para Notion/OpenAI.
- [ ] Dead-letter / reintento para respuestas del trigger 23h.
- [ ] "No sé / escalar a humano" cuando la confianza es baja.

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

## 🟠 P1 — Robustez de n8n (pendiente)
- [ ] Retry + timeout en `Disparar Tomi` y nodos HTTP/Postgres de ingesta.
- [ ] Lock real anti-doble-disparo con tabla `tomi_locks` (hoy hay race en ventana 23-24h).
- [ ] Resolver credenciales placeholder y URLs hardcodeadas de WATI (multimedia).

## 🟡 P2 — Observabilidad (pendiente)
- [ ] `/health` real que chequee DBs + Notion + OpenAI.
- [ ] Métricas de salud / alerta a un canal ante fallos.
- [ ] Caché de Notion más agresivo (subir TTL/tamaño; eviction LRU).

## 🟢 P3 — Resiliencia avanzada (pendiente)
- [ ] Circuit breaker para Notion/OpenAI.
- [ ] Dead-letter / reintento para respuestas del trigger 23h.
- [ ] "No sé / escalar a humano" cuando la confianza es baja.

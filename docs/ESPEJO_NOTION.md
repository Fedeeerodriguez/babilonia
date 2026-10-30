# Espejo de Notion

Las bases `NOTION_DB_*` de Notion se copian a una base propia: el proyecto Supabase que estaba en desuso, `vpeeeeanqumeyemhdxta`, en el esquema `notion_espejo`. La copia se actualiza sola en 1 o 2 minutos.

Tommy y el gestor de tickets van a leer de la copia en vez de Notion, que es lento: hay bases que tardan minutos en bajar por sus fórmulas y rollups. Además, la copia deja preparada la plataforma de asesores, que en el futuro va a sincronizar en los dos sentidos.

Plan completo y fases: ver el plan aprobado (F0 inventario → F7 bidireccional).

## Piezas

| Pieza | Dónde |
|---|---|
| Esquema (tablas, índices, búsqueda vectorial, RLS) | `backend/sql/notion_espejo.sql` |
| Pedidos a Notion: límite global de 2,5/s, reintentos, conteo | `backend/app/services/espejo/notion_api.py` |
| Carga completa, incremental y cola del webhook | `backend/app/services/espejo/sync.py` |
| Lectura y escritura del esquema | `backend/app/services/espejo/repo.py` |
| Worker (proceso aparte) | `backend/app/services/espejo/worker.py` |
| Webhook de Notion y estado | `backend/app/routers/espejo.py` |

## Cómo se mantiene al día

1. **Webhook de Notion.** Notion avisa en segundos que una página cambió y el aviso entra a la cola `pendientes`. El worker vuelve a leer esa página de Notion: el aviso nunca se toma como dato.
2. **Incremental cada 2 minutos.** Por cada base, trae las páginas con `last_edited_time` igual o posterior al último visto, menos 2 minutos de solape. Así se recupera cualquier aviso que se haya perdido.
3. **Carga completa cada noche**, por defecto a las 08 UTC (2 a.m. de México). Sirve para dos cosas:
   - detectar borrados;
   - refrescar fórmulas y rollups que Notion recalcula sin marcar la página como editada, como "Días de Atraso Actuales".

El formato de `paginas.props` es el mismo que devuelve hoy `notion_client._flatten_props`. Por eso cambiar la fuente no toca la lógica de Tommy.

## Variables

| Variable | Para qué |
|---|---|
| `ESPEJO_DATABASE_URL` | Conexión al proyecto del espejo. El worker usa el puerto 5432; las lecturas del backend pueden usar el 6543. **Solo va en `.env` y en EasyPanel.** |
| `NOTION_TOKEN`, `NOTION_DB_*` | Los mismos de siempre. |
| `ESPEJO_INTERVALO_SEG` | Cada cuánto corre la ronda. Default 120. |
| `ESPEJO_HORA_COMPLETA` | Hora UTC de la carga completa diaria. Default 8. |
| `ESPEJO_NOTION_RPS` | Pedidos por segundo a Notion. Default 2,5; Notion permite 3. |
| `ESPEJO_VIEJA_SEG` | Pasado este atraso, una base cuenta como vieja en el estado. Default 600. |
| `NOTION_WEBHOOK_TOKEN` | Opcional. Si no está, se usa el que Notion manda al crear la suscripción. |

## Puesta en marcha

1. Crear el esquema: `python -m app.services.espejo.worker --esquema`
2. Hacer la carga inicial: `python -m app.services.espejo.worker --completa`. Se puede pasar una sola base, por ejemplo `--completa emisiones`.
3. Desplegar el worker:
   - En EasyPanel → **+ Service → App** → `babilonia-espejo`, mismo repo, build path `backend/`.
   - **Command:** `python -m app.services.espejo.worker`.
   - Mismas variables que el backend, más `ESPEJO_DATABASE_URL`.
   - No necesita dominio ni puerto.
4. Crear el webhook en Notion:
   1. Ir a https://www.notion.so/profile/integrations → la integración de Tomi → **Webhooks** → **Create subscription**.
   2. URL: `https://<backend>/api/notion/webhook`.
   3. Eventos: los de página (created, properties updated, content updated, deleted, undeleted, moved).
   4. Notion manda un token de verificación, que se guarda solo. Leerlo con `GET /api/tomi/espejo/token-webhook` (header `X-Tomi-Key`) y pegarlo en Notion en **Verify**.
5. Revisar el estado con `GET /api/tomi/espejo/estado`. Muestra, por base:
   - último sync, atraso y si está vieja;
   - páginas copiadas;
   - pedidos a Notion en la última hora.

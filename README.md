# Tomi · Babilonia

Plataforma interna de métricas y conocimiento para el agente Tomi (soporte WhatsApp/WATI a asesores Allianz).

Stack: **FastAPI + JWT + SQLAlchemy** (backend) · **React + Vite + Tailwind** (frontend) · **Supabase Postgres + pgvector** (datos) · **OpenAI** (embeddings + agente interno).

Diseño: minimalista estilo Apple, paleta Cobalt/Deep Cobalt de la marca Babilonia.

---

## Arranque (Windows)

1. Crear el schema en Supabase ejecutando [`db/schema.sql`](db/schema.sql) en el SQL editor.
2. Importar [`n8n/actualizacion_contexto_wati.json`](n8n/actualizacion_contexto_wati.json) en n8n (reemplaza el workflow viejo).
3. Doble-click en `setup.bat`.
4. Editar `backend/.env`:
   - `DATABASE_URL` — connection string del Postgres de Supabase.
   - `OPENAI_API_KEY` — para embeddings y agente.
   - `SECRET_KEY` — random largo.
5. Doble-click en `start-backend.bat` (puerto 8020) y `start-frontend.bat` (puerto 5173).
6. Ir a http://localhost:5173/register — el primer usuario será admin.

## Estructura

```
tomi-babilonia/
├── backend/        FastAPI + auth JWT + SQLAlchemy contra Supabase Postgres
│   └── app/
│       ├── routers/   auth · users · dashboard · metrics · conversations · documents · agent
│       └── ...
├── frontend/       React + Vite + Tailwind (estilo "RCA minimalist")
│   └── src/
│       ├── pages/     Login · Register · Dashboard · Conversations · Advisors · Knowledge · AgentChat · Team
│       └── ...
├── db/schema.sql                       SQL para Supabase (messages, documents_meta, users, agent_chats)
└── n8n/actualizacion_contexto_wati.json Workflow n8n modificado
```

## Métricas que expone

- `GET /api/metrics/summary` — sent, received, advisor_replies, bot_replies, **avg_response_seconds**.
- `GET /api/metrics/timeseries?bucket=hour|day|week` — series temporales.
- `GET /api/metrics/by-advisor` — ranking de respuestas por asesor.
- `GET /api/dashboard/hud` — datos compactos (24h) para la barra superior.

## Carga de conocimiento

PDF/texto → chunks (1000/150) → OpenAI embeddings (`text-embedding-3-small`) → `documents` con `metadata.source`.
El agente Tomi en n8n usa el mismo `source` (`plu3`, `patrimonial`, `educacion`, `plu`, `plu4`), así que lo cargado es inmediatamente consultable por el bot de WATI.

## Agente interno

`POST /api/agent/chat` con OpenAI function calling. Tools:
- `query_metrics` · `search_conversations` · `list_documents` · `upload_knowledge`

## Cambios al workflow n8n (vs el original)

1. `Edit Fields1` ahora también captura `wati_message_id` (`body.id`) y `operator_email`.
2. Después del `Switch`, cada rama dispara **dos** INSERTs en paralelo:
   - El existente a `n8n_chat_histories` (memoria de Tomi, intacto).
   - Uno nuevo a `messages` con `direction` correspondiente (`cliente`/`asesor`/`template`).
3. Se eliminaron los nodos duplicados desconectados (`Webhook1`, `Edit Fields` viejo).
4. **Importante:** los 3 nodos nuevos usan la credencial Postgres existente (`YkAn096wtNJS3fPB`). Si esa credencial NO apunta al Postgres de Supabase donde están las tablas nuevas, creá una nueva credencial y cambiala solo en `messages: cliente/asesor/template`.

## Logos

Los assets de marca están en `C:\Users\Usuario\OneDrive\Bureau\JOSE MIER\🎨 LOGO BABILONIA`. Para usar el isotipo real, copiar `Isotipo_Babilonia.png` a `frontend/public/logo-iso.png` y modificar `Logo.jsx` para renderizarlo.

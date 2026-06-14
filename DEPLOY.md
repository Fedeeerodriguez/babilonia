# 🚀 Deploy de producción — Tomi · Babilonia (EasyPanel + n8n)

Guía para dejar el sistema completo corriendo: **backend** (FastAPI), **frontend** (React),
**Postgres/Supabase** y los **workflows de n8n** (incluido el nuevo loop de feedback del sandbox).

> Para el deploy de **demo** con cartera ficticia, ver [`DEPLOY_DEMO.md`](DEPLOY_DEMO.md).
> Esta guía es para la instancia **real**, conectada a Notion, WATI y OpenAI.

---

## 🗺️ Arquitectura

```
        Cloudflare (DNS + HTTPS)
   ┌──────────────┬───────────────┬─────────────┐
   ▼              ▼               ▼
┌─────────┐  ┌──────────┐   ┌──────────┐
│ Frontend│  │ Backend  │   │   n8n    │
│ (nginx) │─►│ FastAPI  │◄──│ workflows│◄── WATI webhook
└─────────┘  └────┬─────┘   └────┬─────┘
                  │              │
                  ▼              ▼
          ┌────────────────┐  ┌────────┐
          │ Supabase/PG    │  │ Notion │
          │ messages,docs, │  └────────┘
          │ sandbox_feedback│
          └────────────────┘
```

Todo vive en **EasyPanel** como servicios. Prefijo sugerido: `babilonia-`.

---

## 0️⃣ Base de datos (Supabase Postgres)

1. En el SQL editor de Supabase ejecutá [`db/schema.sql`](db/schema.sql).
   Crea: `messages`, `documents_meta`, `users`, `agent_chats`, `tomi_locks`, **`sandbox_feedback`**.
2. La tabla `documents` (vector store con `pgvector`) ya debería existir (la crea n8n/LangChain).
   Si no, habilitá la extensión: `create extension if not exists vector;`
3. Guardá el connection string: *Project Settings → Database → Connection string (URI)*.
   Usá el **pooler (6543)** para apps serverless/contenedores.

---

## 1️⃣ Backend (FastAPI) — `babilonia-backend`

1. EasyPanel → **+ Service → App** → nombre `babilonia-backend`.
2. **Source:** este repo, branch `main`, **build path** `backend/` (el `Dockerfile` ya está).
3. **Port:** `8020`.
4. **Environment variables:** tomá [`backend/.env.example`](backend/.env.example) como checklist. Mínimo:

   | Variable | Valor |
   |---|---|
   | `SECRET_KEY` | `openssl rand -hex 32` |
   | `DATABASE_URL` | connection string de Supabase (paso 0) |
   | `CORS_ORIGINS` | dominio del frontend (paso 2), ej. `https://app.babilonia.tudominio.com` |
   | `OPENAI_API_KEY` | tu key (embeddings + agente) |
   | `TOMI_INTERNAL_KEY` | `openssl rand -hex 32` — **mismo valor que en n8n** |
   | `NOTION_TOKEN` | token de la integración Notion |
   | `NOTION_DB_*` | IDs de las databases que uses (ver `.env.example`) |
   | `DOCUMENTS_DATABASE_URL` | solo si `documents` vive en otro Postgres |
   | `RELOAD` | `0` (apaga el auto-reloader de uvicorn en el contenedor) |

   > ⚠️ **NUNCA** pongas `DEMO_SEED=1` / `DEMO_RESET=1` acá: esto es producción.
   > ℹ️ La tabla `documents` (vector store) se asume en el **mismo** Postgres que `DATABASE_URL`
   > (el upload de conocimiento y el promote del sandbox escriben con esa conexión). Si está en
   > otra DB, además de `DOCUMENTS_DATABASE_URL` hay que migrar esos writes — avisá si es el caso.

5. Deploy y verificá: `https://api.babilonia.tudominio.com/health` → `{"status":"ok"}`.
   Probá la auth interna:
   ```bash
   curl -X POST https://api.../api/feedback/log \
     -H "X-Tomi-Key: <TOMI_INTERNAL_KEY>" -H "Content-Type: application/json" \
     -d '{"pregunta":"ping","respuesta_tomi":"pong","canal":"sandbox"}'
   ```
   Debe devolver el feedback creado con `"status":"pending"`.
6. Exponé el dominio: *Domains → `api.babilonia.tudominio.com`*.

---

## 2️⃣ Frontend (React/nginx) — `babilonia-frontend`

1. EasyPanel → **+ Service → App** → nombre `babilonia-frontend`.
2. **Source:** este repo, **build path** `frontend/` (Dockerfile multi-stage incluido).
3. **Build arg / env:** `VITE_API_URL=https://api.babilonia.tudominio.com`
   (el frontend la consume en build-time; configurala como **Build Argument** en EasyPanel).
4. **Port:** `80`. Deploy.
5. Exponé el dominio `app.babilonia.tudominio.com`.
6. Primer usuario: andá a `/register` → el primero queda **admin**.
   La página **Sandbox** queda en el sidebar (entre Analítica y Administración).

---

## 3️⃣ n8n — workflows

> Si ya tenés n8n corriendo (en EasyPanel u otro lado), saltá al import.
> Si no, EasyPanel → **+ Service → App** con la imagen oficial `n8nio/n8n`, puerto `5678`,
> volumen persistente en `/home/node/.n8n`, y dominio `n8n.babilonia.tudominio.com`.

### Env vars en n8n (Settings → Variables / o env del contenedor)

| Variable | Valor |
|---|---|
| `TOMI_API_URL` | `https://api.babilonia.tudominio.com` |
| `WATI_SERVER` | `https://live-mt-server.wati.io/<TENANT_ID>` (sin barra final) — solo si usás multimedia |
| `WATI_TOKEN` | tu token de WATI — solo si usás multimedia |
| `TOMI_INTERNAL_KEY` | **el mismo** que en el backend (paso 1) |

### Importar workflows (en orden)

Ver el detalle completo en [`n8n/README.md`](n8n/README.md). Resumen:

1. **Credencial Postgres → Supabase** (apuntando a la DB del paso 0).
2. `n8n/actualizacion_contexto_wati.json` — ingesta de mensajes WATI → `messages`.
3. `n8n/tomi_webhook_entry.json` — bridge (snippet) a pegar en tu workflow `tomi unificado`.
4. `n8n/tomi_trigger_23h.json` — handoff de 23h (ajustar credencial y URL).
5. **`n8n/feedback_log_sandbox.json`** — loop de feedback del sandbox: copiá el nodo
   **`Registrar feedback (Tomi)`** dentro de `tomi unificado`, después de la respuesta del
   agente, en rama paralela (fire-and-forget). Mapeá `pregunta` / `respuesta_tomi` / `canal`.

Tras esto, cada respuesta de Tomi queda registrada y aparece en la página **Sandbox** para
revisar, corregir y promover al conocimiento.

---

## 4️⃣ Cloudflare (DNS + HTTPS)

Para cada subdominio (`app.`, `api.`, `n8n.`):
1. Cloudflare → tu zona → **DNS → Add record**.
2. `CNAME` (o `A` a la IP de EasyPanel), **proxy naranja ON** para HTTPS automático.
3. Esperá la propagación (1–5 min) y probá las URLs.

---

## ✅ Checklist final

- [ ] `/health` del backend responde OK.
- [ ] `db/schema.sql` corrido (incluye `sandbox_feedback`).
- [ ] `TOMI_INTERNAL_KEY` **idéntica** en backend y n8n.
- [ ] `VITE_API_URL` del frontend apunta al dominio real del backend.
- [ ] `CORS_ORIGINS` del backend incluye el dominio del frontend.
- [ ] Primer usuario registrado (admin) y login OK.
- [ ] Workflows de n8n importados y `tomi unificado` con el nodo de feedback.
- [ ] Curl de prueba a `/api/feedback/log` crea una fila → se ve en **Sandbox**.
- [ ] Notion: la integración compartida con cada DB y los `NOTION_DB_*` cargados.

---

## 🔄 Actualizaciones

EasyPanel rebuildeaa al pushear a `main` (si activaste auto-deploy) o con **Deploy** manual.
La tabla `sandbox_feedback` y futuras tablas de la API se crean solas vía `create_all`
al arrancar — no requieren migración manual.

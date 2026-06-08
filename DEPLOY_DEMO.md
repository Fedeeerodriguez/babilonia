# 🎬 Deploy DEMO — Babilonia (cartera ficticia para mostrar)

Instancia **independiente** del sistema, con datos 100% inventados, para presentaciones.
No toca producción ni datos reales de clientes.

> **Resultado final:** un frontend público (ej. `https://demo.babilonia.tudominio.com`)
> con login, dashboard, conversaciones de WhatsApp, métricas y equipo — todo poblado.

---

## 🔑 Accesos del demo (ya quedan creados por el seed)

| Rol | Email | Password |
|-----|-------|----------|
| **Admin** | `demo@babilonia.com` | `DemoBabilonia2026` |
| Asesor | `sofia.martinez@babilonia.demo` | `Asesor2026` |
| Asesor | `diego.fernandez@babilonia.demo` | `Asesor2026` |
| Asesor | `valentina.gomez@babilonia.demo` | `Asesor2026` |
| Asesor | `matias.rios@babilonia.demo` | `Asesor2026` |

Entrá con el **admin** para ver todo (dashboard, métricas, equipo, conversaciones).

---

## 🧱 Arquitectura del demo

```
┌──────────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│ Frontend demo (Vite) │ ──► │ Backend demo (FastAPI│ ──► │ Postgres DEMO   │
│ demo.babilonia...    │     │ api-demo.babilonia.. │     │ (separado)      │
└──────────────────────┘     └──────────────────────┘     └─────────────────┘
        Cloudflare                  EasyPanel                  EasyPanel/Supabase
```

3 servicios nuevos en EasyPanel, **todo con prefijo `babilonia-demo-`** para no confundir con prod.

---

## 1️⃣ Base de datos demo (Postgres separado)

**Opción A — Postgres dentro de EasyPanel (recomendada, gratis):**
1. EasyPanel → tu proyecto → **+ Service → Postgres**.
2. Nombre: `babilonia-demo-db`. Anotá usuario/password/host que te da.
3. El connection string interno queda: `postgresql://postgres:PASS@babilonia-demo-db:5432/postgres`

**Opción B — Proyecto Supabase nuevo:**
1. supabase.com → **New Project** (free) → nombre `babilonia-demo`.
2. Project Settings → Database → Connection string (URI). Guardalo.

> ⚠️ NO uses la DB de producción. El punto del demo es que esté aislado.

---

## 2️⃣ Backend demo

1. EasyPanel → **+ Service → App** → nombre `babilonia-demo-backend`.
2. **Source:** este repo, branch `main`, carpeta `backend/` (Dockerfile ya incluido).
3. **Environment variables:** copiá las de [`backend/.env.demo.example`](backend/.env.demo.example) y completá:
   - `DATABASE_URL` → el del paso 1.
   - `SECRET_KEY` → uno nuevo (`openssl rand -hex 32`).
   - `CORS_ORIGINS` → el dominio del frontend demo (paso 3).
   - `DEMO_SEED=1` ← **esto carga la cartera ficticia sola al arrancar.**
4. **Port:** `8020`. Deploy.
5. Verificá: abrí `https://api-demo.../health` → debe responder `{"status":"ok"}`.
   En los logs vas a ver el cartel `SEED DEMO OK`.
6. Exponé el dominio: EasyPanel → Domains → `api-demo.babilonia.tudominio.com`.

---

## 3️⃣ Frontend demo

1. EasyPanel → **+ Service → App** → nombre `babilonia-demo-frontend`.
2. **Source:** este repo, carpeta `frontend/`.
3. **Build:** Vite estático. Variable de entorno de build:
   - `VITE_API_URL=https://api-demo.babilonia.tudominio.com` (ver [`frontend/.env.demo.example`](frontend/.env.demo.example))
   - Build command: `npm install && npm run build` · Output: `dist/`
4. Deploy y exponé dominio `demo.babilonia.tudominio.com`.

---

## 4️⃣ Cloudflare (DNS + HTTPS)

Para cada dominio (`demo.` y `api-demo.`):
1. Cloudflare → tu zona → **DNS → Add record**.
2. Tipo `CNAME` (o `A` a la IP de EasyPanel), proxy **naranja (ON)** para HTTPS automático.
3. Esperá la propagación (1-5 min) y probá ambas URLs.

---

## 5️⃣ Probar el demo

1. Entrá a `https://demo.babilonia.tudominio.com/login`.
2. Login con `demo@babilonia.com` / `DemoBabilonia2026`.
3. Recorré: **Dashboard** (HUD con totales) · **Conversations** (12 clientes con chats de Tommy) ·
   **Metrics** (series de 30 días, ranking por asesor) · **Team** (4 asesores) · **Knowledge** (8 docs).

---

## 🔄 Recargar / limpiar datos demo

- **Recargar de cero:** poné `DEMO_RESET=1` en el backend, redeploy una vez, y volvé a sacarlo.
- El seed es **determinístico** (`random.seed(42)`): siempre genera la misma cartera.

---

## ⚠️ Qué se ve y qué no

| Pantalla | En el demo |
|---|---|
| Login / Dashboard / Métricas / Conversaciones / Equipo / Knowledge | ✅ Llenas con datos ficticios |
| Pólizas / Renovaciones / Siniestros / Comisiones (Notion en vivo) | ⬜ Vacías (Notion va vacío a propósito para aislar el demo) |
| AgentChat (Tommy interno) | ⚠️ Responde solo si cargás `OPENAI_API_KEY` |

> Si querés que las pantallas de **pólizas/renovaciones** también tengan datos en el demo,
> hay que crear un workspace Notion de prueba y cargar su token — decímelo y lo agregamos.

---

## 🧹 Seguridad

- Los emails demo terminan en `@babilonia.demo` / `demo@babilonia.com` → fáciles de identificar y borrar.
- **Nunca** pongas `DEMO_SEED=1` ni `DEMO_RESET=1` en el backend de producción real.
- Las contraseñas demo son públicas (están en este doc) → es a propósito, son para mostrar.

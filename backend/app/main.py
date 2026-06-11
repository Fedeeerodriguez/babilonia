import logging
import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import Base, engine
from app.routers import auth, users, dashboard, metrics, conversations, documents, agent, tomi, analytics, feedback

load_dotenv(override=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("tomi.main")

# Solo crea las tablas que maneja la API (users, agent_chats, documents_meta).
# `messages` y `documents` viven en Supabase ya creadas por SQL.
Base.metadata.create_all(bind=engine)

# Auto-seed de datos demo: setear DEMO_SEED=1 en el entorno demo (NUNCA en producción real).
if os.getenv("DEMO_SEED", "0") == "1":
    try:
        from app.seed_demo import run as _seed_demo
        _seed_demo()
        log.info("DEMO_SEED=1 → datos demo verificados/cargados.")
    except Exception as e:  # nunca tirar la app por el seed
        log.warning("Fallo el seed demo (se ignora): %s", e)

app = FastAPI(title="Tomi · Babilonia — Métricas WATI / Allianz", version="0.3.0")

origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in [auth, users, dashboard, metrics, conversations, documents, agent, tomi, analytics, feedback]:
    app.include_router(r.router)


@app.get("/health")
def health():
    return {"status": "ok", "brand": "Tomi · Babilonia", "version": "0.3.0"}

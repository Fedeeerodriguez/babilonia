import logging
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from app.database import Base, engine
from app.routers import auth, users, dashboard, metrics, conversations, documents, agent
from app.services.tomi_dispatcher import run_once, DISPATCH_INTERVAL_MINUTES

load_dotenv(override=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("tomi.main")

scheduler: BackgroundScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(run_once, "interval", minutes=DISPATCH_INTERVAL_MINUTES,
                      id="tomi_dispatcher", max_instances=1, coalesce=True)
    scheduler.start()
    log.info("Dispatcher 23h iniciado: cada %d min", DISPATCH_INTERVAL_MINUTES)
    yield
    if scheduler:
        scheduler.shutdown(wait=False)

# Solo crea las tablas que maneja la API (users, agent_chats, documents_meta).
# `messages` y `documents` viven en Supabase ya creadas por SQL.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Tomi · Babilonia — Métricas WATI / Allianz", version="0.2.0", lifespan=lifespan)

origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in [auth, users, dashboard, metrics, conversations, documents, agent]:
    app.include_router(r.router)


@app.get("/health")
def health():
    return {"status": "ok", "brand": "Tomi · Babilonia", "version": "0.2.0"}


@app.post("/api/tomi/dispatch")
def manual_dispatch():
    """Ejecuta un tick del dispatcher 23h manualmente (útil para testing)."""
    return run_once()

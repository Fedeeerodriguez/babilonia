import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import Base, engine
from app.routers import auth, users, dashboard, metrics, conversations, documents, agent

load_dotenv(override=True)

# Solo crea las tablas que maneja la API (users, agent_chats, documents_meta).
# `messages` y `documents` viven en Supabase ya creadas por SQL.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Tomi · Babilonia — Métricas WATI / Allianz", version="0.1.0")

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
    return {"status": "ok", "brand": "Tomi · Babilonia", "version": "0.1.0"}

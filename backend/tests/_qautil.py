"""Utilidades compartidas del paquete QA de Tomi.

- `Skipped`: excepción para saltear tests que necesitan credenciales/servicios.
- `load_env`: parser simple del backend/.env (sin dependencia de python-dotenv).
- `rag_session`: crea una Session de SQLAlchemy contra el Postgres del RAG
  (DOCUMENTS_DATABASE_URL) y exporta OPENAI_API_KEY al entorno.
"""
from __future__ import annotations

import os
from typing import Dict, Optional


class Skipped(Exception):
    """Se lanza cuando un test no puede correr (faltan credenciales/servicio)."""


def _backend_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env() -> Dict[str, str]:
    """Lee backend/.env a un dict. No pisa variables ya presentes en os.environ."""
    env: Dict[str, str] = {}
    path = os.path.join(_backend_dir(), ".env")
    if not os.path.exists(path):
        return env
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


_SESSION_FACTORY = None


def rag_session():
    """Devuelve una Session hacia el RAG o lanza Skipped si faltan credenciales.

    También exporta OPENAI_API_KEY / OPENAI_EMBED_MODEL a os.environ para que
    `memorias._embed` funcione.
    """
    global _SESSION_FACTORY
    env = load_env()
    dsn = os.getenv("DOCUMENTS_DATABASE_URL") or env.get("DOCUMENTS_DATABASE_URL")
    if not dsn:
        raise Skipped("DOCUMENTS_DATABASE_URL no configurada (falta backend/.env)")
    # exportar claves OpenAI para el embedding
    for k in ("OPENAI_API_KEY", "OPENAI_EMBED_MODEL", "DOCUMENTS_TABLE"):
        if env.get(k) and not os.getenv(k):
            os.environ[k] = env[k]
    if not os.getenv("OPENAI_API_KEY"):
        raise Skipped("OPENAI_API_KEY no configurada (necesaria para embeddings)")

    try:
        import psycopg2  # noqa: F401
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
    except Exception as e:  # pragma: no cover
        raise Skipped(f"dependencias no disponibles: {e}")

    if _SESSION_FACTORY is None:
        # El usuario del pooler de Supabase tiene un punto (postgres.<ref>) y SQLAlchemy
        # lo parsea mal al construir el engine desde la URL (termina conectando como
        # "postgres" y falla auth). Forzamos psycopg2 con el DSN EXACTO via `creator`.
        import psycopg2 as _pg
        engine = create_engine(
            "postgresql+psycopg2://",
            creator=lambda: _pg.connect(dsn, connect_timeout=20),
            pool_pre_ping=True,
        )
        _SESSION_FACTORY = sessionmaker(bind=engine)
    return _SESSION_FACTORY()

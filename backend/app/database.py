import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tomi_babilonia.db")
_is_sqlite = DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False} if _is_sqlite else {}

# Pool configurable por env. En Postgres evita agotar conexiones en picos y
# recicla conexiones viejas que el firewall/pooler de Supabase pudo cerrar.
# pool_timeout: cuánto espera una request por una conexión libre antes de fallar
# rápido (mejor que colgarse indefinidamente).
_pool_kwargs = {} if _is_sqlite else dict(
    pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
    pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "10")),
)

engine = create_engine(
    DATABASE_URL, connect_args=connect_args, pool_pre_ping=True, **_pool_kwargs
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Conexión secundaria a la DB donde n8n almacena el vector store `documents`.
# Si no se configura, cae a la principal.
DOCUMENTS_DATABASE_URL = os.getenv("DOCUMENTS_DATABASE_URL") or DATABASE_URL
_docs_connect_args = {"check_same_thread": False} if DOCUMENTS_DATABASE_URL.startswith("sqlite") else {}

_docs_is_sqlite = DOCUMENTS_DATABASE_URL.startswith("sqlite")
_docs_pool_kwargs = {} if _docs_is_sqlite else dict(
    pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
    pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "10")),
)

docs_engine = create_engine(
    DOCUMENTS_DATABASE_URL,
    connect_args=_docs_connect_args,
    pool_pre_ping=True,
    **_docs_pool_kwargs,
)
DocsSessionLocal = sessionmaker(bind=docs_engine, autoflush=False, autocommit=False)


def get_docs_db():
    """Sesión hacia la DB que contiene la tabla `documents` (vector store)."""
    db = DocsSessionLocal()
    try:
        yield db
    finally:
        db.close()

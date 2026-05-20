import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tomi_babilonia.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
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

docs_engine = create_engine(
    DOCUMENTS_DATABASE_URL,
    connect_args=_docs_connect_args,
    pool_pre_ping=True,
    pool_recycle=1800,
)
DocsSessionLocal = sessionmaker(bind=docs_engine, autoflush=False, autocommit=False)


def get_docs_db():
    """Sesión hacia la DB que contiene la tabla `documents` (vector store)."""
    db = DocsSessionLocal()
    try:
        yield db
    finally:
        db.close()

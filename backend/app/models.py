"""Modelos SQLAlchemy. Tipos dialect-agnósticos: corren en SQLite (dev) y Postgres (prod/Supabase)."""
from datetime import datetime
from enum import Enum
import uuid
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text, BigInteger,
    Enum as SQLEnum, ForeignKey, JSON, Uuid,
)
from app.database import Base

# BigInteger autoincrement no funciona en SQLite — degradamos a Integer en ese dialecto.
PK = BigInteger().with_variant(Integer(), "sqlite")


class UserRole(str, Enum):
    admin = "admin"
    asesor = "asesor"


class User(Base):
    __tablename__ = "users"
    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    full_name = Column(String)
    role = Column(SQLEnum(UserRole, name="user_role"), nullable=False, default=UserRole.asesor)
    operator_name = Column(String, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class MessageDirection(str, Enum):
    cliente = "cliente"
    asesor = "asesor"
    bot = "bot"
    template = "template"


class Message(Base):
    """Espejo de la tabla `messages` que escribe n8n. La API solo lee."""
    __tablename__ = "messages"
    id = Column(PK, primary_key=True, autoincrement=True)
    wa_id = Column(String, nullable=False, index=True)
    sender_name = Column(String)
    operator_name = Column(String, index=True)
    operator_email = Column(String)
    direction = Column(SQLEnum(MessageDirection, name="message_direction"), nullable=False, index=True)
    message_type = Column(String)
    template_name = Column(String)
    content = Column(Text, nullable=False)
    event_type = Column(String)
    wati_message_id = Column(String)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    raw = Column(JSON)


class DocumentMeta(Base):
    __tablename__ = "documents_meta"
    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    file_name = Column(String, nullable=False)
    source = Column(String, nullable=False, index=True)
    uploaded_by = Column(String)
    uploaded_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    size_bytes = Column(BigInteger)
    chunks = Column(Integer)
    status = Column(String, default="ready")
    storage_path = Column(String)


class AgentChatMessage(Base):
    __tablename__ = "agent_chats"
    id = Column(PK, primary_key=True, autoincrement=True)
    user_id = Column(Uuid, ForeignKey("users.id"))
    role = Column(String, nullable=False)
    content = Column(Text)
    tool_calls = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)

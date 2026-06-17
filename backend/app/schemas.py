from datetime import datetime
from typing import Optional, List, Any
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field
from app.models import UserRole, MessageDirection


# ─── Auth / Users ───────────────────────────────────────────────
class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    operator_name: Optional[str] = None


class UserCreate(UserBase):
    password: str = Field(min_length=6)
    role: UserRole = UserRole.asesor


class UserOut(UserBase):
    id: UUID
    role: UserRole
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ─── Métricas ───────────────────────────────────────────────────
class MetricsSummary(BaseModel):
    sent: int
    received: int
    advisor_replies: int
    bot_replies: int
    avg_response_seconds: Optional[float]
    period_from: datetime
    period_to: datetime


class TimeBucket(BaseModel):
    bucket: datetime
    sent: int
    received: int
    advisor_replies: int


class AdvisorMetric(BaseModel):
    operator_name: Optional[str]
    replies: int
    avg_response_seconds: Optional[float]


# ─── Conversaciones ─────────────────────────────────────────────
class MessageOut(BaseModel):
    id: int
    wa_id: str
    sender_name: Optional[str]
    operator_name: Optional[str]
    direction: MessageDirection
    message_type: Optional[str]
    template_name: Optional[str]
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationSummary(BaseModel):
    wa_id: str
    sender_name: Optional[str]
    last_message_at: datetime
    message_count: int
    last_direction: MessageDirection
    last_content: str


# ─── Documentos ─────────────────────────────────────────────────
class DocumentOut(BaseModel):
    id: UUID
    file_name: str
    source: str
    uploaded_by: Optional[str]
    uploaded_at: datetime
    size_bytes: Optional[int]
    chunks: Optional[int]
    status: str

    class Config:
        from_attributes = True


class TextUploadIn(BaseModel):
    title: str
    source: str
    text: str


# ─── Agente interno ─────────────────────────────────────────────
class AgentChatIn(BaseModel):
    message: str
    history: List[dict] = []


# ─── Sandbox feedback ───────────────────────────────────────────
class FeedbackLogIn(BaseModel):
    """Registra una interacción de Tomi (la llama el sandbox / n8n)."""
    pregunta: str
    respuesta_tomi: Optional[str] = None
    canal: str = "sandbox"
    source: Optional[str] = None
    publico: Optional[str] = None    # cliente | asesor | prospecto | estudiante | otro
    user_email: Optional[str] = None


class FeedbackReviewIn(BaseModel):
    """El admin califica y/o corrige una interacción."""
    rating: Optional[str] = Field(None, description="good | mejorable | bad")
    respuesta_corregida: Optional[str] = None
    tags: Optional[List[str]] = None
    publico: Optional[str] = None    # permite corregir el público desde la revisión


class FeedbackOut(BaseModel):
    id: int
    pregunta: str
    respuesta_tomi: Optional[str]
    respuesta_corregida: Optional[str]
    rating: Optional[str]
    status: str
    canal: Optional[str]
    source: Optional[str]
    publico: Optional[str]
    tags: Optional[List[str]]
    user_email: Optional[str]
    reviewed_by: Optional[str]
    promoted_doc_source: Optional[str]
    created_at: datetime
    reviewed_at: Optional[datetime]

    class Config:
        from_attributes = True


class FeedbackStats(BaseModel):
    total: int
    pendientes: int
    revisadas: int
    promovidas: int
    good: int
    mejorable: int
    bad: int
    tasa_aprobacion: float                 # good / calificadas (correctas a la primera)
    top_tags_malos: List[dict]
    por_publico: List[dict]                # [{publico, total, good, mejorable, bad, tasa}]

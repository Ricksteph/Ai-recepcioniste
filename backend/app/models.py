"""SQLAlchemy models — multi-tenant data model (cahier des charges §22)."""
import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .config import settings
from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Vector column: pgvector on Postgres, JSON text on SQLite (dev/tests).
EmbeddingColumn = Vector(settings.embedding_dim).with_variant(Text(), "sqlite")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    sector: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    website: Mapped[str] = mapped_column(String(300), default="")
    timezone: Mapped[str] = mapped_column(String(60), default="Europe/Paris")
    languages: Mapped[list] = mapped_column(JSON, default=lambda: ["fr"])
    currency: Mapped[str] = mapped_column(String(10), default="EUR")
    logo_url: Mapped[str] = mapped_column(String(500), default="")
    # {"monday": {"open": "09:00", "close": "18:00"}, ..., "sunday": null}
    business_hours: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=True
    )
    email: Mapped[str] = mapped_column(String(200), index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    full_name: Mapped[str] = mapped_column(String(200), default="")
    # super_admin | admin | agent
    role: Mapped[str] = mapped_column(String(30), default="admin")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ReceptionistConfig(Base, TimestampMixin):
    __tablename__ = "receptionist_configs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), default="Léa")
    avatar_url: Mapped[str] = mapped_column(String(500), default="")
    voice: Mapped[str] = mapped_column(String(80), default="")
    language: Mapped[str] = mapped_column(String(10), default="fr")
    tone: Mapped[str] = mapped_column(String(80), default="professionnel et chaleureux")
    style: Mapped[str] = mapped_column(String(200), default="concis et direct")
    conciseness: Mapped[int] = mapped_column(Integer, default=2)  # 1 court .. 3 détaillé
    greeting: Mapped[str] = mapped_column(
        Text, default="Bonjour ! Je suis Léa, l'assistante virtuelle. Comment puis-je vous aider ?"
    )
    # {"do": [...], "avoid": [...], "ask": [...], "confirm": [...], "transfer": [...]}
    instructions: Mapped[dict] = mapped_column(JSON, default=dict)
    services: Mapped[list] = mapped_column(JSON, default=list)  # [{"name","duration_min","description"}]
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeSource(Base, TimestampMixin):
    __tablename__ = "knowledge_sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    # pdf | docx | xlsx | csv | txt | markdown | web | faq | manual
    type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(800), default="")
    content: Mapped[str] = mapped_column(Text, default="")  # manual/faq/txt content
    # pending | processing | ready | error
    status: Mapped[str] = mapped_column(String(20), default="pending")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str] = mapped_column(Text, default="")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)


class KnowledgeChunk(Base, TimestampMixin):
    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(EmbeddingColumn, nullable=True)


class BusinessRule(Base, TimestampMixin):
    __tablename__ = "business_rules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    # hours | appointment | transfer | unknown | action_limit | validation | custom
    kind: Mapped[str] = mapped_column(String(30), default="custom")
    # structured condition, see engine/rules.py for the grammar
    condition: Mapped[dict] = mapped_column(JSON, default=dict)
    action: Mapped[str] = mapped_column(String(60), default="allow")  # allow | block | require_human | set
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Contact(Base, TimestampMixin):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    notes: Mapped[str] = mapped_column(Text, default="")


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(30), default="web_chat")  # web_chat | sandbox | whatsapp | voice
    contact_id: Mapped[str | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    visitor_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | handoff | resolved | closed
    summary: Mapped[str] = mapped_column(Text, default="")
    intent: Mapped[str] = mapped_column(String(40), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    # working memory: extracted entities + rolling summary
    memory: Mapped[dict] = mapped_column(JSON, default=dict)
    resolution: Mapped[str] = mapped_column(String(20), default="")  # resolved_by_agent | handed_off


class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # user | assistant | human_agent | system
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(40), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    sources: Mapped[list] = mapped_column(JSON, default=list)  # [{"source_id","name","snippet"}]
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Lead(Base, TimestampMixin):
    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    contact_id: Mapped[str | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    need: Mapped[str] = mapped_column(Text, default="")
    service: Mapped[str] = mapped_column(String(200), default="")
    budget: Mapped[str] = mapped_column(String(100), default="")
    urgency: Mapped[str] = mapped_column(String(30), default="normal")  # low | normal | high | urgent
    source: Mapped[str] = mapped_column(String(60), default="web_chat")
    comment: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[int] = mapped_column(Integer, default=0)  # 0..100, explainable
    score_reasons: Mapped[list] = mapped_column(JSON, default=list)
    # new | contacted | qualified | converted | lost
    status: Mapped[str] = mapped_column(String(20), default="new")


class Appointment(Base, TimestampMixin):
    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    contact_id: Mapped[str | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    service: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(String(300), default="")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(60), default="Europe/Paris")
    notes: Mapped[str] = mapped_column(Text, default="")
    # confirmed | cancelled | completed | no_show
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    external_id: Mapped[str] = mapped_column(String(120), default="")
    provider: Mapped[str] = mapped_column(String(40), default="internal_calendar")


class Integration(Base, TimestampMixin):
    __tablename__ = "integrations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40))  # calendar | email | whatsapp
    provider: Mapped[str] = mapped_column(String(60), default="internal_calendar")
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # secrets stay server-side
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ActionExecution(Base, TimestampMixin):
    __tablename__ = "action_executions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    tool: Mapped[str] = mapped_column(String(60))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    # success | failed | pending
    status: Mapped[str] = mapped_column(String(20))


class Handoff(Base, TimestampMixin):
    __tablename__ = "handoffs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str] = mapped_column(String(200), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    # pending | claimed | resolved
    status: Mapped[str] = mapped_column(String(20), default="pending")
    assigned_to: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class EmailOutbox(Base, TimestampMixin):
    __tablename__ = "email_outbox"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    to: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | sent | failed


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=True
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor: Mapped[str] = mapped_column(String(200), default="system")
    action: Mapped[str] = mapped_column(String(120), index=True)
    object_type: Mapped[str] = mapped_column(String(60), default="")
    object_id: Mapped[str] = mapped_column(String(64), default="")
    result: Mapped[str] = mapped_column(String(20), default="success")  # success | failed
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

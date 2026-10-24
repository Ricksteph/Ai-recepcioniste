"""Pydantic request/response schemas for the public API."""
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# ---- Auth ------------------------------------------------------------------ #
class RegisterIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(default="", max_length=200)
    sector: str = Field(default="", max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    tenant_id: str | None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---- Tenant / Receptionist -------------------------------------------------- #
class BusinessHours(BaseModel):
    open: str | None = None
    close: str | None = None


class TenantIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str | None = Field(default=None, max_length=80)
    sector: str = ""
    description: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    timezone: str = "Europe/Paris"
    languages: list[str] = Field(default_factory=lambda: ["fr"])
    currency: str = "EUR"
    business_hours: dict[str, BusinessHours | None] = Field(default_factory=dict)


class ServiceIn(BaseModel):
    name: str
    duration_min: int = 30
    description: str = ""
    price: str = ""


class ReceptionistIn(BaseModel):
    name: str = "Léa"
    avatar_url: str = ""
    voice: str = ""
    language: str = "fr"
    tone: str = "professionnel et chaleureux"
    style: str = "concis et direct"
    conciseness: int = 2
    greeting: str = ""
    instructions: dict = Field(default_factory=dict)
    services: list[ServiceIn] = Field(default_factory=list)


class OnboardingIn(BaseModel):
    """Étapes 2-6 du parcours : entreprise + réceptionniste + premières règles."""
    tenant: TenantIn
    receptionist: ReceptionistIn = Field(default_factory=ReceptionistIn)
    create_default_rules: bool = True


# ---- Knowledge -------------------------------------------------------------- #
class SourceIn(BaseModel):
    type: str = Field(pattern=r"^(pdf|docx|xlsx|csv|txt|markdown|web|faq|manual)$")
    name: str = Field(min_length=1, max_length=300)
    url: str = ""
    content: str = ""


class SourcePatch(BaseModel):
    name: str | None = None
    url: str | None = None
    content: str | None = None
    enabled: bool | None = None


class SourceOut(BaseModel):
    id: str
    type: str
    name: str
    url: str
    status: str
    enabled: bool
    error: str
    chunk_count: int
    created_at: datetime
    updated_at: datetime


# ---- Rules ------------------------------------------------------------------ #
class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = "custom"
    condition: dict = Field(default_factory=dict)
    action: str = "allow"
    params: dict = Field(default_factory=dict)
    description: str = ""
    priority: int = 100
    enabled: bool = True


class RuleOut(RuleIn):
    id: str
    tenant_id: str


# ---- Conversations / Chat ---------------------------------------------------- #
class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    visitor_id: str = ""


class SourceRef(BaseModel):
    source_id: str | None = None
    name: str = ""
    snippet: str = ""


class ActionOut(BaseModel):
    tool: str
    status: str
    result: dict = Field(default_factory=dict)
    message: str = ""


class ChatOut(BaseModel):
    conversation_id: str
    reply: str
    intent: str
    confidence: float
    sources: list[SourceRef] = Field(default_factory=list)
    actions: list[ActionOut] = Field(default_factory=list)
    handoff: bool = False


class ConversationOut(BaseModel):
    id: str
    channel: str
    status: str
    intent: str
    confidence: float
    summary: str
    resolution: str
    created_at: datetime
    updated_at: datetime
    contact_name: str = ""


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    intent: str
    confidence: float
    sources: list = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)
    created_at: datetime


# ---- Leads ------------------------------------------------------------------- #
class LeadIn(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    need: str = ""
    service: str = ""
    budget: str = ""
    urgency: str = "normal"
    source: str = "web_chat"
    comment: str = ""


class LeadPatch(BaseModel):
    status: str | None = None
    comment: str | None = None
    urgency: str | None = None


class LeadOut(LeadIn):
    id: str
    conversation_id: str | None = None
    score: int
    score_reasons: list = Field(default_factory=list)
    created_at: datetime


# ---- Appointments --------------------------------------------------------------- #
class AppointmentIn(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    service: str = ""
    date: str  # YYYY-MM-DD
    time: str  # HH:MM or HH:MM:SS
    notes: str = ""


class AppointmentPatch(BaseModel):
    status: str | None = None
    date: str | None = None
    time: str | None = None
    notes: str | None = None


class AppointmentOut(BaseModel):
    id: str
    service: str
    title: str
    starts_at: datetime
    ends_at: datetime
    status: str
    notes: str
    contact_name: str = ""
    contact_email: str = ""
    conversation_id: str | None = None
    created_at: datetime


class AvailabilityOut(BaseModel):
    date: str
    duration_min: int
    slots: list[dict]


# ---- Handoff / Analytics / Audit -------------------------------------------------- #
class HandoffOut(BaseModel):
    id: str
    conversation_id: str
    reason: str
    summary: str
    status: str
    created_at: datetime


class AuditOut(BaseModel):
    id: str
    actor: str
    action: str
    object_type: str
    object_id: str
    result: str
    details: dict
    created_at: datetime


class SandboxTestIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None


class WidgetConfigOut(BaseModel):
    company: str
    agent_name: str
    greeting: str
    language: str
    color: str = "#2563eb"
    published: bool

"""Public widget API (§15) — visitor-facing, tenant-published only.

Strict isolation: a visitor can only talk to a published tenant, and can only
read back messages of conversations matching their own visitor_id.
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..config import settings
from ..db import get_session
from ..engine.conversation import handle_message
from ..models import Conversation, Message, ReceptionistConfig, Tenant
from ..schemas import ChatIn, ChatOut, MessageOut, WidgetConfigOut

router = APIRouter(prefix="/public", tags=["public"])

RATE_LIMIT_PER_MINUTE = 30
_visitor_hits: dict[str, list[float]] = {}


async def _rate_limit(request: Request) -> None:
    import time

    key = request.client.host if request.client else "unknown"
    now = time.time()
    hits = [t for t in _visitor_hits.get(key, []) if now - t < 60]
    if len(hits) >= RATE_LIMIT_PER_MINUTE:
        raise HTTPException(429, "Trop de messages, réessayez dans une minute.")
    hits.append(now)
    _visitor_hits[key] = hits


async def _published_tenant(db: AsyncSession, slug: str) -> tuple[Tenant, ReceptionistConfig]:
    tenant = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if not tenant or not tenant.is_active:
        raise HTTPException(404, "Assistant introuvable")
    config = (
        await db.execute(select(ReceptionistConfig).where(ReceptionistConfig.tenant_id == tenant.id))
    ).scalar_one_or_none()
    if not config or not config.is_published:
        raise HTTPException(404, "Cet assistant n'est pas encore publié")
    return tenant, config


@router.get("/{slug}/widget", response_model=WidgetConfigOut)
async def widget_config(slug: str, db: AsyncSession = Depends(get_session)):
    tenant, config = await _published_tenant(db, slug)
    return WidgetConfigOut(
        company=tenant.name, agent_name=config.name, greeting=config.greeting,
        language=config.language, published=config.is_published,
    )


@router.post("/{slug}/chat", response_model=ChatOut)
async def chat(slug: str, payload: ChatIn, request: Request, db: AsyncSession = Depends(get_session)):
    await _rate_limit(request)
    tenant, config = await _published_tenant(db, slug)
    visitor_id = payload.visitor_id or secrets.token_hex(12)

    conv = None
    if payload.conversation_id:
        conv = (
            await db.execute(
                select(Conversation).where(
                    Conversation.id == payload.conversation_id,
                    Conversation.tenant_id == tenant.id,
                    Conversation.visitor_id == visitor_id,
                )
            )
        ).scalar_one_or_none()
        if not conv:
            raise HTTPException(404, "Conversation introuvable")
    if conv is None:
        conv = Conversation(
            tenant_id=tenant.id, channel="web_chat", visitor_id=visitor_id, status="open",
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)

    result = await handle_message(db, tenant, config, conv, payload.message)
    return ChatOut(**{k: result[k] for k in (
        "conversation_id", "reply", "intent", "confidence", "sources", "actions", "handoff",
    )})


@router.get("/{slug}/history", response_model=list[MessageOut])
async def history(
    slug: str,
    visitor_id: str,
    conversation_id: str = "",
    db: AsyncSession = Depends(get_session),
):
    """Session history for the visitor (§15), scoped to their own visitor_id."""
    tenant, _ = await _published_tenant(db, slug)
    query = (
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Conversation.tenant_id == tenant.id, Conversation.visitor_id == visitor_id)
    )
    if conversation_id:
        query = query.where(Conversation.id == conversation_id)
    rows = (await db.execute(query.order_by(Message.created_at).limit(200))).scalars().all()
    return [
        MessageOut(
            id=m.id, role=m.role, content=m.content, intent=m.intent,
            confidence=m.confidence, sources=m.sources or [], meta=m.meta or {},
            created_at=m.created_at,
        )
        for m in rows
    ]

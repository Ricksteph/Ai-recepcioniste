"""Conversation supervision + sandbox testing + human replies + handoffs."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..db import get_session
from ..deps import CurrentUser, require_agent, require_admin, tenant_scope
from ..engine.conversation import handle_message
from ..models import (
    ActionExecution,
    Contact,
    Conversation,
    Handoff,
    Message,
    ReceptionistConfig,
    Tenant,
)
from ..schemas import ChatIn, ChatOut, ConversationOut, HandoffOut, MessageOut, SandboxTestIn

router = APIRouter(tags=["conversations"])


async def _load_config(db: AsyncSession, tenant_id: str) -> ReceptionistConfig | None:
    return (
        await db.execute(
            select(ReceptionistConfig).where(ReceptionistConfig.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()


async def _conversation_out(db: AsyncSession, conv: Conversation) -> ConversationOut:
    contact_name = ""
    if conv.contact_id:
        contact = await db.get(Contact, conv.contact_id)
        contact_name = contact.name if contact else ""
    return ConversationOut(
        id=conv.id, channel=conv.channel, status=conv.status, intent=conv.intent,
        confidence=conv.confidence, summary=conv.summary, resolution=conv.resolution,
        created_at=conv.created_at, updated_at=conv.updated_at, contact_name=contact_name,
    )


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    status: str = "",
    channel: str = "",
    q: str = "",
    limit: int = 50,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    query = select(Conversation).where(Conversation.tenant_id == tenant_id)
    if status:
        query = query.where(Conversation.status == status)
    if channel:
        query = query.where(Conversation.channel == channel)
    if q:
        query = query.where(Conversation.summary.contains(q))
    rows = (
        await db.execute(query.order_by(Conversation.updated_at.desc()).limit(min(limit, 200)))
    ).scalars().all()
    return [await _conversation_out(db, c) for c in rows]


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.tenant_id != tenant_id:
        raise HTTPException(404, "Conversation introuvable")
    return await _conversation_out(db, conv)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: str,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.tenant_id != tenant_id:
        raise HTTPException(404, "Conversation introuvable")
    rows = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
    ).scalars().all()
    return [
        MessageOut(
            id=m.id, role=m.role, content=m.content, intent=m.intent,
            confidence=m.confidence, sources=m.sources or [], meta=m.meta or {},
            created_at=m.created_at,
        )
        for m in rows
    ]


@router.post("/conversations/{conversation_id}/reply", response_model=ChatOut)
async def agent_reply(
    conversation_id: str,
    payload: ChatIn,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    """An human agent answers on the conversation; visitor will see it in the widget."""
    tenant_id = tenant_scope(user)
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.tenant_id != tenant_id:
        raise HTTPException(404, "Conversation introuvable")
    db.add(Message(
        tenant_id=tenant_id, conversation_id=conv.id, role="human_agent",
        content=payload.message, meta={"user": user.email},
    ))
    if conv.status == "handoff":
        conv.status = "open"
    await db.commit()
    await audit(
        db, action="conversation.agent_reply", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="conversation", object_id=conv.id,
    )
    return ChatOut(
        conversation_id=conv.id, reply=payload.message, intent=conv.intent,
        confidence=conv.confidence, sources=[], actions=[], handoff=False,
    )


@router.post("/conversations/{conversation_id}/resolve")
async def resolve_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.tenant_id != tenant_id:
        raise HTTPException(404, "Conversation introuvable")
    conv.status = "resolved"
    conv.resolution = "resolved_by_human"
    handoff = (
        await db.execute(
            select(Handoff).where(Handoff.conversation_id == conv.id, Handoff.status != "resolved")
        )
    ).scalars().first()
    if handoff:
        handoff.status = "resolved"
        handoff.assigned_to = user.id
    await db.commit()
    await audit(
        db, action="conversation.resolved", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="conversation", object_id=conv.id,
    )
    return {"status": "resolved"}


# --------------------------------------------------------------------------- #
# Sandbox — test before publishing (§19)
# --------------------------------------------------------------------------- #
@router.post("/sandbox/test", response_model=ChatOut)
async def sandbox_test(
    payload: SandboxTestIn,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    tenant = await db.get(Tenant, tenant_id)
    config = await _load_config(db, tenant_id)
    if payload.conversation_id:
        conv = await db.get(Conversation, payload.conversation_id)
        if not conv or conv.tenant_id != tenant_id or conv.channel != "sandbox":
            raise HTTPException(404, "Conversation de test introuvable")
    else:
        conv = Conversation(
            tenant_id=tenant_id, channel="sandbox",
            visitor_id=f"sandbox:{user.id}", status="open",
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
    result = await handle_message(db, tenant, config, conv, payload.message)
    await audit(
        db, action="sandbox.test", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="conversation", object_id=conv.id,
        details={"intent": result["intent"], "actions": [a["tool"] for a in result["actions"]]},
    )
    return ChatOut(**{k: result[k] for k in (
        "conversation_id", "reply", "intent", "confidence", "sources", "actions", "handoff",
    )})


@router.get("/sandbox/conversations", response_model=list[ConversationOut])
async def sandbox_conversations(
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    rows = (
        await db.execute(
            select(Conversation)
            .where(Conversation.tenant_id == tenant_id, Conversation.channel == "sandbox")
            .order_by(Conversation.updated_at.desc())
            .limit(50)
        )
    ).scalars().all()
    return [await _conversation_out(db, c) for c in rows]


# --------------------------------------------------------------------------- #
# Handoffs
# --------------------------------------------------------------------------- #
@router.get("/handoffs", response_model=list[HandoffOut])
async def list_handoffs(
    status: str = "",
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    query = select(Handoff).where(Handoff.tenant_id == tenant_id)
    if status:
        query = query.where(Handoff.status == status)
    rows = (
        await db.execute(query.order_by(Handoff.created_at.desc()).limit(100))
    ).scalars().all()
    return [
        HandoffOut(
            id=h.id, conversation_id=h.conversation_id, reason=h.reason,
            summary=h.summary, status=h.status, created_at=h.created_at,
        )
        for h in rows
    ]


@router.post("/handoffs/{handoff_id}/claim")
async def claim_handoff(
    handoff_id: str,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    handoff = await db.get(Handoff, handoff_id)
    if not handoff or handoff.tenant_id != tenant_id:
        raise HTTPException(404, "Transfert introuvable")
    handoff.status = "claimed"
    handoff.assigned_to = user.id
    await db.commit()
    await audit(
        db, action="handoff.claimed", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="handoff", object_id=handoff.id,
    )
    return {"status": "claimed", "assigned_to": user.id}


@router.get("/conversations/{conversation_id}/actions")
async def conversation_actions(
    conversation_id: str,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.tenant_id != tenant_id:
        raise HTTPException(404, "Conversation introuvable")
    rows = (
        await db.execute(
            select(ActionExecution)
            .where(ActionExecution.conversation_id == conversation_id)
            .order_by(ActionExecution.created_at)
        )
    ).scalars().all()
    return [
        {
            "id": a.id, "tool": a.tool, "params": a.params, "result": a.result,
            "status": a.status, "created_at": a.created_at.isoformat(),
        }
        for a in rows
    ]


@router.get("/conversations/stats/counts")
async def conversation_counts(
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    rows = (
        await db.execute(
            select(Conversation.status, func.count()).where(Conversation.tenant_id == tenant_id).group_by(Conversation.status)
        )
    ).all()
    return {status: count for status, count in rows}

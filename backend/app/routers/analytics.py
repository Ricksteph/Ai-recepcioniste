"""Analytics + audit endpoints (§18)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import CurrentUser, require_agent, tenant_scope
from ..models import (
    ActionExecution,
    AuditLog,
    Conversation,
    Handoff,
    Lead,
    Message,
    Appointment,
)

router = APIRouter(tags=["analytics"])


@router.get("/analytics/overview")
async def overview(
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    since = datetime.now(timezone.utc) - timedelta(days=30)

    async def count(model, *where):
        return (await db.execute(
            select(func.count()).select_from(model).where(model.tenant_id == tenant_id, *where)
        )).scalar() or 0

    total_conversations = await count(Conversation)
    handoffs = await count(Conversation, Conversation.status == "handoff")
    resolved_by_agent = await count(Conversation, Conversation.resolution == "resolved_by_agent")
    resolved_total = await count(Conversation, Conversation.status.in_(["resolved", "closed"]))
    open_conversations = await count(Conversation, Conversation.status == "open")
    leads = await count(Lead)
    qualified_leads = await count(Lead, Lead.status.in_(["qualified", "converted"]))
    appointments = await count(Appointment, Appointment.status == "confirmed")
    messages = await count(Message, Message.created_at >= since)
    actions_ok = await count(ActionExecution, ActionExecution.status == "success")
    actions_failed = await count(ActionExecution, ActionExecution.status == "failed")
    pending_handoffs = await count(Handoff, Handoff.status == "pending")

    resolution_rate = 0.0
    finished = resolved_total + handoffs
    if finished:
        resolution_rate = round(resolved_total / finished, 3)

    # daily volume, last 14 days
    daily_rows = (
        await db.execute(
            select(func.date(Message.created_at), func.count())
            .where(Message.tenant_id == tenant_id, Message.created_at >= since)
            .group_by(func.date(Message.created_at))
            .order_by(func.date(Message.created_at))
        )
    ).all()
    return {
        "conversations": {"total": total_conversations, "open": open_conversations, "handoff": handoffs},
        "messages_30d": messages,
        "resolution_rate": resolution_rate,
        "resolved_by_agent": resolved_by_agent + resolved_total,
        "leads": {"total": leads, "qualified": qualified_leads},
        "appointments_confirmed": appointments,
        "actions": {"success": actions_ok, "failed": actions_failed},
        "pending_handoffs": pending_handoffs,
        "daily_messages": [{"date": str(d), "count": c} for d, c in daily_rows],
    }


@router.get("/analytics/intents")
async def intents(
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    rows = (
        await db.execute(
            select(Message.intent, func.count())
            .where(Message.tenant_id == tenant_id, Message.role == "user", Message.intent != "")
            .group_by(Message.intent)
            .order_by(func.count().desc())
        )
    ).all()
    top_questions = (
        await db.execute(
            select(Message.content, func.count())
            .where(Message.tenant_id == tenant_id, Message.role == "user")
            .group_by(Message.content)
            .order_by(func.count().desc())
            .limit(10)
        )
    ).all()
    escalations = (
        await db.execute(
            select(Handoff.reason, func.count())
            .where(Handoff.tenant_id == tenant_id)
            .group_by(Handoff.reason)
            .order_by(func.count().desc())
        )
    ).all()
    tool_rows = (
        await db.execute(
            select(ActionExecution.tool, ActionExecution.status, func.count())
            .where(ActionExecution.tenant_id == tenant_id)
            .group_by(ActionExecution.tool, ActionExecution.status)
        )
    ).all()
    return {
        "intents": [{"intent": i, "count": c} for i, c in rows],
        "top_questions": [{"question": q, "count": c} for q, c in top_questions],
        "escalations": [{"reason": r, "count": c} for r, c in escalations],
        "tools": [{"tool": t, "status": s, "count": c} for t, s, c in tool_rows],
    }


@router.get("/audit")
async def audit_logs(
    action: str = "",
    limit: int = 100,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    query = select(AuditLog).where(AuditLog.tenant_id == tenant_id)
    if action:
        query = query.where(AuditLog.action == action)
    rows = (
        await db.execute(query.order_by(AuditLog.created_at.desc()).limit(min(limit, 500)))
    ).scalars().all()
    return [
        {
            "id": a.id, "actor": a.actor, "action": a.action, "object_type": a.object_type,
            "object_id": a.object_id, "result": a.result, "details": a.details or {},
            "created_at": a.created_at.isoformat(),
        }
        for a in rows
    ]

"""Leads endpoints (§17) — explainable scoring computed by the Tool Engine."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..db import get_session
from ..deps import CurrentUser, require_agent, tenant_scope
from ..engine.tools import _lead_score
from ..models import Lead
from ..schemas import LeadIn, LeadOut, LeadPatch

router = APIRouter(prefix="/leads", tags=["leads"])


def _out(lead: Lead) -> LeadOut:
    return LeadOut(
        id=lead.id, conversation_id=lead.conversation_id, name=lead.name,
        email=lead.email, phone=lead.phone, need=lead.need, service=lead.service,
        budget=lead.budget, urgency=lead.urgency, source=lead.source,
        comment=lead.comment, score=lead.score, score_reasons=lead.score_reasons or [],
        created_at=lead.created_at,
    )


@router.get("", response_model=list[LeadOut])
async def list_leads(
    status: str = "",
    limit: int = 100,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    query = select(Lead).where(Lead.tenant_id == tenant_id)
    if status:
        query = query.where(Lead.status == status)
    rows = (
        await db.execute(query.order_by(Lead.created_at.desc()).limit(min(limit, 300)))
    ).scalars().all()
    return [_out(l) for l in rows]


@router.post("", response_model=LeadOut, status_code=201)
async def create_lead(
    payload: LeadIn,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    data = payload.model_dump()
    score, reasons = _lead_score(data)
    lead = Lead(tenant_id=tenant_id, score=score, score_reasons=reasons, **data)
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    await audit(
        db, action="lead.created", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="lead", object_id=lead.id, details={"score": score},
    )
    return _out(lead)


@router.patch("/{lead_id}", response_model=LeadOut)
async def patch_lead(
    lead_id: str,
    payload: LeadPatch,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    lead = await db.get(Lead, lead_id)
    if not lead or lead.tenant_id != tenant_id:
        raise HTTPException(404, "Prospect introuvable")
    if payload.status is not None:
        if payload.status not in ("new", "contacted", "qualified", "converted", "lost"):
            raise HTTPException(400, "Statut invalide")
        lead.status = payload.status
    if payload.comment is not None:
        lead.comment = payload.comment
    if payload.urgency is not None:
        lead.urgency = payload.urgency
        lead.score, lead.score_reasons = _lead_score({
            "email": lead.email, "phone": lead.phone, "service": lead.service,
            "need": lead.need, "budget": lead.budget, "urgency": lead.urgency,
        })
    await db.commit()
    await audit(
        db, action="lead.updated", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="lead", object_id=lead.id, details={"status": lead.status},
    )
    return _out(lead)


@router.delete("/{lead_id}", status_code=204)
async def delete_lead(
    lead_id: str,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    lead = await db.get(Lead, lead_id)
    if not lead or lead.tenant_id != tenant_id:
        raise HTTPException(404, "Prospect introuvable")
    await db.delete(lead)
    await db.commit()
    await audit(
        db, action="lead.deleted", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="lead", object_id=lead_id,
    )

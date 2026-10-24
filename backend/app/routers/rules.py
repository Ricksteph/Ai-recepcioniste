"""Business rules CRUD (engine/rules.py defines the condition grammar)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..db import get_session
from ..deps import CurrentUser, require_admin, tenant_scope
from ..engine.rules import default_rules_payload, evaluate_condition
from ..models import BusinessRule
from ..schemas import RuleIn, RuleOut

router = APIRouter(prefix="/rules", tags=["rules"])


def _rule_out(rule: BusinessRule) -> RuleOut:
    data = {k: v for k, v in rule.__dict__.items() if not k.startswith("_")}
    return RuleOut(id=rule.id, tenant_id=rule.tenant_id, **{
        k: v for k, v in data.items() if k not in ("id", "tenant_id")
    })


@router.get("", response_model=list[RuleOut])
async def list_rules(
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
):
    tenant_id = tenant_scope(user)
    rows = (
        await db.execute(
            select(BusinessRule)
            .where(BusinessRule.tenant_id == tenant_id)
            .order_by(BusinessRule.priority)
        )
    ).scalars().all()
    return [_rule_out(r) for r in rows]


@router.post("", response_model=RuleOut, status_code=201)
async def create_rule(
    payload: RuleIn,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
):
    tenant_id = tenant_scope(user)
    rule = BusinessRule(tenant_id=tenant_id, **payload.model_dump())
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    await audit(
        db, action="rule.created", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="rule", object_id=rule.id, details={"name": rule.name},
    )
    return _rule_out(rule)


@router.put("/{rule_id}", response_model=RuleOut)
async def update_rule(
    rule_id: str,
    payload: RuleIn,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
):
    tenant_id = tenant_scope(user)
    rule = await db.get(BusinessRule, rule_id)
    if not rule or rule.tenant_id != tenant_id:
        raise HTTPException(404, "Règle introuvable")
    for field in ("name", "kind", "condition", "action", "params", "description", "priority", "enabled"):
        setattr(rule, field, getattr(payload, field))
    await db.commit()
    await audit(
        db, action="rule.updated", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="rule", object_id=rule.id, details={"name": rule.name},
    )
    return _rule_out(rule)


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: str,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
):
    tenant_id = tenant_scope(user)
    rule = await db.get(BusinessRule, rule_id)
    if not rule or rule.tenant_id != tenant_id:
        raise HTTPException(404, "Règle introuvable")
    await db.delete(rule)
    await db.commit()
    await audit(
        db, action="rule.deleted", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="rule", object_id=rule_id,
    )


@router.post("/defaults", status_code=201)
async def create_default_rules(
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
):
    tenant_id = tenant_scope(user)
    existing = (
        await db.execute(select(BusinessRule).where(BusinessRule.tenant_id == tenant_id))
    ).scalars().all()
    names = {r.name for r in existing}
    created = 0
    for rule in default_rules_payload():
        if rule["name"] not in names:
            db.add(BusinessRule(tenant_id=tenant_id, **rule))
            created += 1
    await db.commit()
    await audit(
        db, action="rule.defaults_created", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="rule", details={"created": created},
    )
    return {"created": created}


@router.post("/simulate")
async def simulate(
    payload: dict,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
):
    """Simulate rule evaluation against a context (sandbox tool)."""
    tenant_id = tenant_scope(user)
    rows = (
        await db.execute(select(BusinessRule).where(BusinessRule.tenant_id == tenant_id))
    ).scalars().all()
    context = payload.get("context") or {}
    matched = [
        {"rule": r.name, "action": r.action, "params": r.params, "description": r.description}
        for r in rows
        if r.enabled and evaluate_condition(r.condition or {}, context)
    ]
    return {"context": context, "matched": matched}

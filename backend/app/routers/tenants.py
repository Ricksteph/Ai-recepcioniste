"""Tenant configuration endpoints: company profile, receptionist identity, publish, users."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..db import get_session
from ..deps import CurrentUser, get_current_user, require_admin, tenant_scope
from ..engine.rules import default_rules_payload
from ..models import BusinessRule, ReceptionistConfig, Tenant, User
from ..schemas import OnboardingIn, ReceptionistIn, RuleIn, TenantIn, UserOut
from ..security import hash_password

router = APIRouter(prefix="/tenants", tags=["tenants"])


async def _get_tenant(db: AsyncSession, tenant_id: str) -> Tenant:
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Entreprise introuvable")
    return tenant


async def _get_config(db: AsyncSession, tenant_id: str) -> ReceptionistConfig:
    config = (
        await db.execute(
            select(ReceptionistConfig).where(ReceptionistConfig.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not config:
        config = ReceptionistConfig(tenant_id=tenant_id)
        db.add(config)
        await db.commit()
        await db.refresh(config)
    return config


def _tenant_out(tenant: Tenant) -> dict:
    return {
        "id": tenant.id,
        "slug": tenant.slug,
        "name": tenant.name,
        "sector": tenant.sector,
        "description": tenant.description,
        "address": tenant.address,
        "phone": tenant.phone,
        "email": tenant.email,
        "website": tenant.website,
        "timezone": tenant.timezone,
        "languages": tenant.languages,
        "currency": tenant.currency,
        "business_hours": tenant.business_hours,
        "is_active": tenant.is_active,
        "created_at": tenant.created_at,
    }


def _config_out(config: ReceptionistConfig, tenant: Tenant) -> dict:
    return {
        "name": config.name,
        "avatar_url": config.avatar_url,
        "voice": config.voice,
        "language": config.language,
        "tone": config.tone,
        "style": config.style,
        "conciseness": config.conciseness,
        "greeting": config.greeting,
        "instructions": config.instructions,
        "services": config.services,
        "is_published": config.is_published,
        "published_at": config.published_at,
        "widget_url": f"/chat/{tenant.slug}",
    }


@router.get("/me")
async def get_my_tenant(
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
):
    tenant_id = tenant_scope(user)
    tenant = await _get_tenant(db, tenant_id)
    config = await _get_config(db, tenant_id)
    return {"tenant": _tenant_out(tenant), "receptionist": _config_out(config, tenant)}


@router.put("/me")
async def update_my_tenant(
    payload: TenantIn,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
):
    tenant_id = tenant_scope(user)
    tenant = await _get_tenant(db, tenant_id)
    hours = {}
    for day, val in (payload.business_hours or {}).items():
        hours[day] = val.model_dump() if val else None
    for field in (
        "name", "sector", "description", "address", "phone", "email",
        "website", "timezone", "currency",
    ):
        setattr(tenant, field, getattr(payload, field))
    tenant.languages = payload.languages or tenant.languages
    if hours:
        tenant.business_hours = hours
    await db.commit()
    await audit(
        db, action="tenant.updated", tenant_id=tenant.id, user_id=user.id,
        actor=user.email, object_type="tenant", object_id=tenant.id,
    )
    config = await _get_config(db, tenant_id)
    return {"tenant": _tenant_out(tenant), "receptionist": _config_out(config, tenant)}


@router.put("/me/receptionist")
async def update_receptionist(
    payload: ReceptionistIn,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
):
    tenant_id = tenant_scope(user)
    config = await _get_config(db, tenant_id)
    for field in ("name", "avatar_url", "voice", "language", "tone", "style", "greeting"):
        setattr(config, field, getattr(payload, field))
    config.conciseness = max(1, min(3, payload.conciseness))
    config.instructions = payload.instructions or {}
    config.services = [s.model_dump() for s in payload.services]
    await db.commit()
    await audit(
        db, action="receptionist.updated", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="receptionist_config", object_id=config.id,
        details={"name": config.name, "services": len(config.services)},
    )
    tenant = await _get_tenant(db, tenant_id)
    return _config_out(config, tenant)


@router.post("/me/publish")
async def publish(
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
):
    tenant_id = tenant_scope(user)
    config = await _get_config(db, tenant_id)
    config.is_published = True
    config.published_at = datetime.now(timezone.utc)
    await db.commit()
    await audit(
        db, action="receptionist.published", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="receptionist_config", object_id=config.id,
    )
    tenant = await _get_tenant(db, tenant_id)
    return {"published": True, **_config_out(config, tenant)}


@router.post("/me/unpublish")
async def unpublish(
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
):
    tenant_id = tenant_scope(user)
    config = await _get_config(db, tenant_id)
    config.is_published = False
    await db.commit()
    await audit(
        db, action="receptionist.unpublished", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="receptionist_config", object_id=config.id,
    )
    tenant = await _get_tenant(db, tenant_id)
    return {"published": False, **_config_out(config, tenant)}


@router.post("/onboarding")
async def onboarding(
    payload: OnboardingIn,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
):
    """Étapes 2-6 du parcours : profil entreprise, réceptionniste, règles initiales."""
    tenant_id = tenant_scope(user)
    tenant = await _get_tenant(db, tenant_id)
    t = payload.tenant
    hours = {day: (val.model_dump() if val else None) for day, val in (t.business_hours or {}).items()}
    for field in ("name", "sector", "description", "address", "phone", "email", "website", "timezone", "currency"):
        setattr(tenant, field, getattr(t, field))
    tenant.languages = t.languages or tenant.languages
    if hours:
        tenant.business_hours = hours

    config = await _get_config(db, tenant_id)
    r = payload.receptionist
    for field in ("name", "avatar_url", "voice", "language", "tone", "style", "greeting"):
        setattr(config, field, getattr(r, field))
    config.conciseness = max(1, min(3, r.conciseness))
    config.instructions = r.instructions or {}
    config.services = [s.model_dump() for s in r.services]

    created_rules = 0
    if payload.create_default_rules:
        existing = (
            await db.execute(select(BusinessRule).where(BusinessRule.tenant_id == tenant_id))
        ).scalars().all()
        if not existing:
            for rule in default_rules_payload():
                db.add(BusinessRule(tenant_id=tenant_id, **rule))
                created_rules += 1
    await db.commit()
    await audit(
        db, action="onboarding.completed", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="tenant", object_id=tenant_id,
        details={"rules_created": created_rules},
    )
    return {"tenant": _tenant_out(tenant), "receptionist": _config_out(config, tenant), "rules_created": created_rules}


@router.get("/me/users", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
):
    tenant_id = tenant_scope(user)
    rows = (await db.execute(select(User).where(User.tenant_id == tenant_id))).scalars().all()
    return [
        UserOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role, tenant_id=u.tenant_id)
        for u in rows
    ]


@router.post("/me/users", response_model=UserOut, status_code=201)
async def create_user(
    payload: dict,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_admin),
):
    tenant_id = tenant_scope(user)
    email = str(payload.get("email", "")).strip()
    password = str(payload.get("password", ""))
    role = str(payload.get("role", "agent"))
    if not email or len(password) < 8 or role not in ("admin", "agent"):
        raise HTTPException(400, "Champs invalides (email, mot de passe ≥ 8 car., rôle admin|agent)")
    if (await db.execute(select(User).where(User.email == email))).scalar_one_or_none():
        raise HTTPException(409, "Cet email est déjà utilisé")
    new_user = User(
        tenant_id=tenant_id, email=email, password_hash=hash_password(password),
        full_name=str(payload.get("full_name", "")), role=role,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    await audit(
        db, action="user.created", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="user", object_id=new_user.id, details={"email": email, "role": role},
    )
    return UserOut(
        id=new_user.id, email=new_user.email, full_name=new_user.full_name,
        role=new_user.role, tenant_id=new_user.tenant_id,
    )


@router.get("/super-admin")
async def list_all_tenants(
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    if user.role != "super_admin":
        raise HTTPException(403, "Réservé au super admin")
    rows = (await db.execute(select(Tenant))).scalars().all()
    return [_tenant_out(t) for t in rows]

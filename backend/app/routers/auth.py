"""Auth endpoints: register (creates tenant + admin), login, me."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..db import get_session
from ..deps import CurrentUser, get_current_user
from ..engine.rules import default_rules_payload
from ..models import BusinessRule, ReceptionistConfig, Tenant, User
from ..schemas import LoginIn, RegisterIn, TokenOut, UserOut
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(payload: RegisterIn, db: AsyncSession = Depends(get_session)):
    existing = (
        await db.execute(select(Tenant).where(Tenant.slug == payload.slug))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "Ce slug d'entreprise est déjà utilisé")
    existing_email = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if existing_email:
        raise HTTPException(409, "Un compte existe déjà avec cet email")

    tenant = Tenant(
        slug=payload.slug,
        name=payload.company_name,
        sector=payload.sector,
        email=payload.email,
        business_hours={
            "monday": {"open": "09:00", "close": "18:00"},
            "tuesday": {"open": "09:00", "close": "18:00"},
            "wednesday": {"open": "09:00", "close": "18:00"},
            "thursday": {"open": "09:00", "close": "18:00"},
            "friday": {"open": "09:00", "close": "18:00"},
            "saturday": {"open": "09:00", "close": "12:30"},
            "sunday": None,
        },
    )
    db.add(tenant)
    await db.flush()

    user = User(
        tenant_id=tenant.id,
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name or payload.email.split("@")[0],
        role="admin",
    )
    db.add(user)
    db.add(ReceptionistConfig(tenant_id=tenant.id))
    for rule in default_rules_payload():
        db.add(BusinessRule(tenant_id=tenant.id, **rule))
    await db.commit()
    await db.refresh(user)

    await audit(
        db, action="tenant.created", tenant_id=tenant.id, user_id=user.id,
        actor=user.email, object_type="tenant", object_id=tenant.id,
        details={"slug": tenant.slug, "name": tenant.name},
    )
    token = create_access_token(user_id=user.id, tenant_id=tenant.id, role=user.role)
    return TokenOut(
        access_token=token,
        user=UserOut(
            id=user.id, email=user.email, full_name=user.full_name,
            role=user.role, tenant_id=tenant.id,
        ),
    )


@router.post("/login", response_model=TokenOut)
async def login(payload: LoginIn, db: AsyncSession = Depends(get_session)):
    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        await audit(
            db, action="auth.login", actor=payload.email, result="failed",
            details={"reason": "invalid_credentials"},
        )
        raise HTTPException(401, "Email ou mot de passe incorrect")
    if not user.is_active:
        raise HTTPException(403, "Compte désactivé")
    await audit(
        db, action="auth.login", tenant_id=user.tenant_id, user_id=user.id,
        actor=user.email, object_type="user", object_id=user.id,
    )
    token = create_access_token(user_id=user.id, tenant_id=user.tenant_id, role=user.role)
    return TokenOut(
        access_token=token,
        user=UserOut(
            id=user.id, email=user.email, full_name=user.full_name,
            role=user.role, tenant_id=user.tenant_id,
        ),
    )


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser = Depends(get_current_user)):
    return UserOut(
        id=user.id, email=user.email, full_name=user.full_name,
        role=user.role, tenant_id=user.tenant_id,
    )

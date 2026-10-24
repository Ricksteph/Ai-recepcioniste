"""FastAPI dependencies: authentication, RBAC, tenant scoping."""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import User
from .security import decode_access_token


@dataclass
class CurrentUser:
    id: str
    tenant_id: str | None
    role: str
    email: str
    full_name: str


def _unauthorized(detail: str = "Non authentifié") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_session)
) -> CurrentUser:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise _unauthorized()
    payload = decode_access_token(auth.removeprefix("Bearer ").strip())
    if not payload:
        raise _unauthorized("Token invalide ou expiré")
    user = await db.get(User, payload.get("sub", ""))
    if not user or not user.is_active:
        raise _unauthorized("Utilisateur inactif ou introuvable")
    return CurrentUser(
        id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        email=user.email,
        full_name=user.full_name,
    )


def require_roles(*roles: str):
    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Accès refusé : rôle requis {'/'.join(roles)}",
            )
        return user

    return checker


require_admin = require_roles("admin", "super_admin")
require_agent = require_roles("admin", "super_admin", "agent")
require_super_admin = require_roles("super_admin")


def tenant_scope(user: CurrentUser) -> str:
    """Return the tenant the user operates on, or 403 if missing."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ce compte n'est rattaché à aucune entreprise",
        )
    return user.tenant_id

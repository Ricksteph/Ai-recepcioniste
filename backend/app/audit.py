"""Audit log helper — every critical event is recorded (cahier des charges §18/§24)."""
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditLog


async def audit(
    db: AsyncSession,
    *,
    action: str,
    tenant_id: str | None = None,
    user_id: str | None = None,
    actor: str = "system",
    object_type: str = "",
    object_id: str = "",
    result: str = "success",
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            actor=actor,
            action=action,
            object_type=object_type,
            object_id=object_id,
            result=result,
            details=details or {},
        )
    )
    await db.commit()

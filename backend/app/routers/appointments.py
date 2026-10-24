"""Appointments endpoints (§16): availability + creation verified against real slots."""
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import audit
from ..db import get_session
from ..deps import CurrentUser, require_agent, tenant_scope
from ..engine.availability import find_free_slots
from ..engine.rules import evaluate_rules
from ..engine.tools import _resolve_contact, _service_duration
from ..models import Appointment, BusinessRule, Contact, ReceptionistConfig, Tenant
from ..schemas import AppointmentIn, AppointmentOut, AppointmentPatch, AvailabilityOut

router = APIRouter(prefix="/appointments", tags=["appointments"])


def _parse(value: str, fmt: str) -> datetime:
    try:
        return datetime.strptime(value, fmt)
    except ValueError as exc:
        raise HTTPException(400, f"Format invalide : {value}") from exc


async def _rules_for(db: AsyncSession, tenant_id: str, intent: str = "APPOINTMENT"):
    rows = (
        await db.execute(
            select(BusinessRule).where(BusinessRule.tenant_id == tenant_id, BusinessRule.enabled.is_(True))
        )
    ).scalars().all()
    return evaluate_rules(rows, {"intent": intent, "entities": {}})


@router.get("/availability", response_model=AvailabilityOut)
async def availability(
    date: str,
    service: str = "",
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    tenant = await db.get(Tenant, tenant_id)
    config = (
        await db.execute(select(ReceptionistConfig).where(ReceptionistConfig.tenant_id == tenant_id))
    ).scalar_one_or_none()
    rules = await _rules_for(db, tenant_id)
    duration = _service_duration(config, service)
    try:
        day = date_cls.fromisoformat(date)
    except ValueError as exc:
        raise HTTPException(400, "Date invalide (YYYY-MM-DD attendu)") from exc
    slots = await find_free_slots(
        db, tenant, day=day, duration_minutes=duration,
        min_lead_hours=rules.min_lead_hours, max_days_ahead=rules.max_days_ahead,
        closed_days=rules.closed_days, limit=30,
    )
    return AvailabilityOut(date=date, duration_min=duration, slots=slots)


@router.get("", response_model=list[AppointmentOut])
async def list_appointments(
    status: str = "",
    limit: int = 100,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    query = select(Appointment).where(Appointment.tenant_id == tenant_id)
    if status:
        query = query.where(Appointment.status == status)
    rows = (
        await db.execute(query.order_by(Appointment.starts_at.desc()).limit(min(limit, 300)))
    ).scalars().all()
    out = []
    for a in rows:
        contact = await db.get(Contact, a.contact_id) if a.contact_id else None
        out.append(AppointmentOut(
            id=a.id, service=a.service, title=a.title, starts_at=a.starts_at,
            ends_at=a.ends_at, status=a.status, notes=a.notes,
            contact_name=contact.name if contact else "",
            contact_email=contact.email if contact else "",
            conversation_id=a.conversation_id, created_at=a.created_at,
        ))
    return out


@router.post("", response_model=AppointmentOut, status_code=201)
async def create_appointment(
    payload: AppointmentIn,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    """Same verification path as the chat tool: never book a slot that is not real."""
    tenant_id = tenant_scope(user)
    tenant = await db.get(Tenant, tenant_id)
    config = (
        await db.execute(select(ReceptionistConfig).where(ReceptionistConfig.tenant_id == tenant_id))
    ).scalar_one_or_none()
    rules = await _rules_for(db, tenant_id)

    starts = _parse(payload.time if len(payload.time) > 5 else payload.time + ":00", "%H:%M:%S")
    try:
        day = date_cls.fromisoformat(payload.date)
    except ValueError as exc:
        raise HTTPException(400, "Date invalide") from exc
    starts_at = datetime.combine(day, starts.time(), tzinfo=timezone.utc)

    fake_conv = type("C", (), {"id": None, "contact_id": None, "channel": "dashboard"})()
    contact = await _resolve_contact(db, tenant, fake_conv, payload.model_dump())
    if not contact or not contact.name:
        raise HTTPException(400, "Le nom du client est obligatoire")

    duration = _service_duration(config, payload.service)
    slots = await find_free_slots(
        db, tenant, day=day, duration_minutes=duration,
        min_lead_hours=rules.min_lead_hours, max_days_ahead=rules.max_days_ahead,
        closed_days=rules.closed_days, limit=400,
    )
    if not any(s["starts_at"][:19] == starts_at.isoformat()[:19] for s in slots):
        raise HTTPException(
            409, "Ce créneau n'est pas disponible (hors horaires, passé, déjà réservé ou délai minimum)"
        )

    appt = Appointment(
        tenant_id=tenant_id, contact_id=contact.id, service=payload.service,
        title=f"{payload.service or 'Rendez-vous'} — {contact.name}",
        starts_at=starts_at, ends_at=starts_at + timedelta(minutes=duration),
        timezone=tenant.timezone, notes=payload.notes, status="confirmed",
        provider="internal_calendar",
    )
    db.add(appt)
    await db.commit()
    await db.refresh(appt)
    await audit(
        db, action="appointment.created", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="appointment", object_id=appt.id,
        details={"starts_at": starts_at.isoformat(), "service": payload.service},
    )
    return AppointmentOut(
        id=appt.id, service=appt.service, title=appt.title, starts_at=appt.starts_at,
        ends_at=appt.ends_at, status=appt.status, notes=appt.notes,
        contact_name=contact.name, contact_email=contact.email,
        conversation_id=None, created_at=appt.created_at,
    )


@router.patch("/{appointment_id}", response_model=AppointmentOut)
async def patch_appointment(
    appointment_id: str,
    payload: AppointmentPatch,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    appt = await db.get(Appointment, appointment_id)
    if not appt or appt.tenant_id != tenant_id:
        raise HTTPException(404, "Rendez-vous introuvable")
    if payload.status is not None:
        if payload.status not in ("confirmed", "cancelled", "completed", "no_show"):
            raise HTTPException(400, "Statut invalide")
        appt.status = payload.status
    if payload.date and payload.time:
        tenant = await db.get(Tenant, tenant_id)
        rules = await _rules_for(db, tenant_id)
        new_time = _parse(payload.time if len(payload.time) > 5 else payload.time + ":00", "%H:%M:%S")
        new_day = date_cls.fromisoformat(payload.date)
        new_starts = datetime.combine(new_day, new_time.time(), tzinfo=timezone.utc)
        duration = int((appt.ends_at - appt.starts_at).total_seconds() // 60)
        slots = await find_free_slots(
            db, tenant, day=new_day, duration_minutes=duration,
            min_lead_hours=rules.min_lead_hours, max_days_ahead=rules.max_days_ahead,
            closed_days=rules.closed_days, limit=400,
        )
        if not any(s["starts_at"][:19] == new_starts.isoformat()[:19] for s in slots):
            raise HTTPException(409, "Le nouveau créneau n'est pas disponible")
        appt.starts_at = new_starts
        appt.ends_at = new_starts + timedelta(minutes=duration)
    if payload.notes is not None:
        appt.notes = payload.notes
    await db.commit()
    await db.refresh(appt)
    contact = await db.get(Contact, appt.contact_id) if appt.contact_id else None
    await audit(
        db, action="appointment.updated", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="appointment", object_id=appt.id,
        details={"status": appt.status},
    )
    return AppointmentOut(
        id=appt.id, service=appt.service, title=appt.title, starts_at=appt.starts_at,
        ends_at=appt.ends_at, status=appt.status, notes=appt.notes,
        contact_name=contact.name if contact else "",
        contact_email=contact.email if contact else "",
        conversation_id=appt.conversation_id, created_at=appt.created_at,
    )


@router.delete("/{appointment_id}", status_code=204)
async def cancel_appointment(
    appointment_id: str,
    db: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_agent),
):
    tenant_id = tenant_scope(user)
    appt = await db.get(Appointment, appointment_id)
    if not appt or appt.tenant_id != tenant_id:
        raise HTTPException(404, "Rendez-vous introuvable")
    appt.status = "cancelled"
    await db.commit()
    await audit(
        db, action="appointment.cancelled", tenant_id=tenant_id, user_id=user.id,
        actor=user.email, object_type="appointment", object_id=appt.id,
    )

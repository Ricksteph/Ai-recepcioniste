"""Real availability computation from tenant business hours + existing appointments.

No invented slots: every proposed slot comes from configured opening hours,
minus confirmed appointments, minus rule constraints (lead time, horizon,
closed days).
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Appointment, Tenant

_SLOT_MINUTES = 30
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _parse_hhmm(value: str) -> time | None:
    try:
        h, m = value.split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return None


async def find_free_slots(
    db: AsyncSession,
    tenant: Tenant,
    *,
    day: date,
    duration_minutes: int = 30,
    min_lead_hours: float = 0.0,
    max_days_ahead: int = 90,
    closed_days: list[str] | None = None,
    limit: int = 6,
) -> list[dict]:
    """Return up to `limit` free ISO datetime slots for the given day."""
    closed_days = [d.lower() for d in (closed_days or [])]
    tz = ZoneInfo(tenant.timezone or "Europe/Paris")
    now = datetime.now(timezone.utc).astimezone(tz)

    if day < now.date():
        return []
    if (day - now.date()).days > max_days_ahead:
        return []
    weekday = _WEEKDAYS[day.weekday()]
    if weekday in closed_days:
        return []

    hours = (tenant.business_hours or {}).get(weekday)
    if not hours or not hours.get("open") or not hours.get("close"):
        return []
    open_t = _parse_hhmm(str(hours["open"]))
    close_t = _parse_hhmm(str(hours["close"]))
    if not open_t or not close_t or close_t <= open_t:
        return []

    day_start = datetime.combine(day, open_t, tzinfo=tz)
    day_end = datetime.combine(day, close_t, tzinfo=tz)

    result: list[dict] = []
    cursor = day_start.replace(minute=(open_t.minute // _SLOT_MINUTES) * _SLOT_MINUTES, second=0, microsecond=0)
    slot = timedelta(minutes=duration_minutes or _SLOT_MINUTES)
    earliest = now + timedelta(hours=min_lead_hours)

    rows = await db.execute(
        select(Appointment.starts_at, Appointment.ends_at).where(
            Appointment.tenant_id == tenant.id,
            Appointment.status.in_(["confirmed"]),
        )
    )
    busy = [
        (
            s.astimezone(tz) if s.tzinfo else s.replace(tzinfo=tz),
            e.astimezone(tz) if e.tzinfo else e.replace(tzinfo=tz),
        )
        for s, e in rows.all()
    ]

    while cursor + slot <= day_end:
        slot_end = cursor + slot
        if cursor >= earliest and not any(cursor < b_end and slot_end > b_start for b_start, b_end in busy):
            result.append(
                {
                    "starts_at": cursor.isoformat(),
                    "ends_at": slot_end.isoformat(),
                    "weekday": weekday,
                }
            )
            if len(result) >= limit:
                break
        cursor += timedelta(minutes=_SLOT_MINUTES)
    return result


async def next_available(
    db: AsyncSession,
    tenant: Tenant,
    *,
    duration_minutes: int = 30,
    min_lead_hours: float = 0.0,
    max_days_ahead: int = 60,
    closed_days: list[str] | None = None,
    horizon_days: int = 14,
) -> list[dict]:
    """Search upcoming days for the first free slots (used when no date given)."""
    for offset in range(horizon_days):
        day = (datetime.now(timezone.utc) + timedelta(days=offset)).date()
        slots = await find_free_slots(
            db,
            tenant,
            day=day,
            duration_minutes=duration_minutes,
            min_lead_hours=min_lead_hours,
            max_days_ahead=max_days_ahead,
            closed_days=closed_days,
            limit=3,
        )
        if slots:
            return slots
    return []

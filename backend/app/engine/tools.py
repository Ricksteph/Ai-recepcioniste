"""Tool / Action Engine (cahier des charges §12).

Critical rule: an action is NEVER reported as successful on the basis of the
LLM's intention. Each tool validates its parameters, executes for real against
the tenant's own data, and returns an explicit status: success | failed | pending.
The Conversation Engine only phrases outcomes from these verified statuses.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Coroutine

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    ActionExecution,
    Appointment,
    Contact,
    Conversation,
    EmailOutbox,
    Handoff,
    Lead,
    ReceptionistConfig,
    Tenant,
)
from ..config import settings
from .availability import find_free_slots, next_available
from .rules import RuleOutcome

logger = logging.getLogger("ai_receptionist.tools")

TOOL_NAMES = [
    "check_availability",
    "create_appointment",
    "cancel_appointment",
    "reschedule_appointment",
    "create_lead",
    "update_customer",
    "send_email",
    "transfer_to_human",
]


@dataclass
class ToolResult:
    status: str  # success | failed | pending
    result: dict[str, Any] = field(default_factory=dict)
    message: str = ""

    def as_dict(self) -> dict:
        return {"status": self.status, "result": self.result, "message": self.message}


def _parse_dt(date_str: str, time_str: str) -> datetime | None:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    t_str = (time_str or "").strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            t = datetime.strptime(t_str, fmt).time()
            return datetime.combine(d, t)
        except ValueError:
            continue
    return None


def _service_duration(config: ReceptionistConfig | None, service: str) -> int:
    if config and service:
        for s in config.services or []:
            if str(s.get("name", "")).lower() == service.lower():
                return int(s.get("duration_min") or 30)
    return 30


async def _resolve_contact(
    db: AsyncSession, tenant: Tenant, conv: Conversation, params: dict
) -> Contact | None:
    contact_id = conv.contact_id
    if not contact_id:
        # try match by email/phone within the tenant
        email, phone = params.get("email"), params.get("phone")
        q = select(Contact).where(Contact.tenant_id == tenant.id)
        if email:
            contact = (await db.execute(q.where(Contact.email == email))).scalar_one_or_none()
        elif phone:
            contact = (await db.execute(q.where(Contact.phone == phone))).scalar_one_or_none()
        else:
            contact = None
        if contact is None:
            contact = Contact(
                tenant_id=tenant.id,
                name=params.get("name") or "",
                email=email or "",
                phone=phone or "",
            )
            db.add(contact)
            await db.flush()
        conv.contact_id = contact.id
        contact_id = contact.id
    contact = await db.get(Contact, contact_id)
    if contact:
        # complete the card when the LLM collected new info
        changed = False
        for f in ("name", "email", "phone"):
            if params.get(f) and not getattr(contact, f):
                setattr(contact, f, params[f])
                changed = True
        if changed:
            await db.commit()
    return contact


def _lead_score(params: dict) -> tuple[int, list[str]]:
    """Explainable lead score (cahier des charges §17)."""
    score, reasons = 0, []
    if params.get("email"):
        score += 30
        reasons.append("+30 : email collecté")
    if params.get("phone"):
        score += 20
        reasons.append("+20 : téléphone collecté")
    if params.get("service"):
        score += 20
        reasons.append("+20 : service identifié")
    urgency = str(params.get("urgency") or "").lower()
    if urgency in ("high", "urgent"):
        score += 15
        reasons.append(f"+15 : urgence {urgency}")
    if params.get("need"):
        score += 10
        reasons.append("+10 : besoin décrit")
    if params.get("budget"):
        score += 5
        reasons.append("+5 : budget indiqué")
    return min(score, 100), reasons


# --------------------------------------------------------------------------- #
# Tool implementations
# --------------------------------------------------------------------------- #
async def t_check_availability(
    db: AsyncSession, tenant: Tenant, conv: Conversation, params: dict, outcome: RuleOutcome
) -> ToolResult:
    config = (
        await db.execute(
            select(ReceptionistConfig).where(ReceptionistConfig.tenant_id == tenant.id)
        )
    ).scalar_one_or_none()
    service = params.get("service") or ""
    duration = _service_duration(config, service)
    date_str = params.get("date")
    common = dict(
        duration_minutes=duration,
        min_lead_hours=outcome.min_lead_hours,
        max_days_ahead=outcome.max_days_ahead,
        closed_days=outcome.closed_days,
    )
    if date_str:
        try:
            day = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return ToolResult("failed", {"reason": "date invalide"}, "Date de disponibilité invalide.")
        slots = await find_free_slots(db, tenant, day=day, **common)
    else:
        slots = await next_available(db, tenant, **common)
    if not slots:
        return ToolResult(
            "failed",
            {"reason": "aucun créneau", "date": date_str},
            "Aucun créneau libre sur cette période selon les horaires d'ouverture.",
        )
    return ToolResult(
        "success",
        {"slots": slots[:6], "service": service, "duration_min": duration},
        f"{len(slots[:6])} créneau(x) disponible(s).",
    )


async def t_create_appointment(
    db: AsyncSession, tenant: Tenant, conv: Conversation, params: dict, outcome: RuleOutcome
) -> ToolResult:
    config = (
        await db.execute(
            select(ReceptionistConfig).where(ReceptionistConfig.tenant_id == tenant.id)
        )
    ).scalar_one_or_none()
    service = params.get("service") or ""
    if outcome.allowed_services and service and service not in outcome.allowed_services:
        return ToolResult("failed", {"reason": "service non autorisé"}, f"Le service « {service} » n'est pas proposé.")
    starts = _parse_dt(str(params.get("date") or ""), str(params.get("time") or ""))
    if not starts:
        return ToolResult(
            "failed", {"reason": "date/heure manquante ou invalide"},
            "Je ne peux pas créer le rendez-vous : date ou heure manquante.",
        )
    missing = [f for f in outcome.require_fields if not params.get(f)]
    if missing:
        return ToolResult(
            "failed", {"reason": "champs obligatoires manquants", "missing": missing},
            f" informations manquantes : {', '.join(missing)}.",
        )
    contact = await _resolve_contact(db, tenant, conv, params)
    if not contact or not contact.name:
        return ToolResult(
            "failed", {"reason": "coordonnées manquantes"},
            "Le nom du client est nécessaire pour confirmer le rendez-vous.",
        )
    duration = _service_duration(config, service)
    slots = await find_free_slots(
        db, tenant, day=starts.date(), duration_minutes=duration,
        min_lead_hours=outcome.min_lead_hours, max_days_ahead=outcome.max_days_ahead,
        closed_days=outcome.closed_days, limit=200,
    )
    if not any(s["starts_at"][:19] == starts.isoformat()[:19] for s in slots):
        return ToolResult(
            "failed", {"reason": "créneau indisponible", "requested": starts.isoformat()},
            "Ce créneau n'est plus disponible (hors horaires, passé, déjà réservé ou délai minimum non respecté).",
        )
    appt = Appointment(
        tenant_id=tenant.id,
        contact_id=contact.id,
        conversation_id=conv.id,
        service=service,
        title=f"{service or 'Rendez-vous'} — {contact.name}",
        starts_at=starts,
        ends_at=starts + timedelta(minutes=duration),
        timezone=tenant.timezone,
        notes=params.get("notes") or "",
        status="confirmed",
        provider="internal_calendar",
        external_id="",
    )
    db.add(appt)
    await db.commit()
    await db.refresh(appt)
    return ToolResult(
        "success",
        {
            "appointment_id": appt.id,
            "starts_at": starts.isoformat(),
            "ends_at": appt.ends_at.isoformat(),
            "service": service,
            "contact": contact.name,
        },
        "Rendez-vous réellement créé et confirmé.",
    )


async def t_cancel_appointment(
    db: AsyncSession, tenant: Tenant, conv: Conversation, params: dict, outcome: RuleOutcome
) -> ToolResult:
    appt = None
    if params.get("appointment_id"):
        appt = await db.get(Appointment, str(params["appointment_id"]))
        if appt and appt.tenant_id != tenant.id:
            appt = None
    if appt is None:
        q = select(Appointment).where(
            Appointment.tenant_id == tenant.id, Appointment.status == "confirmed"
        )
        if conv.contact_id:
            q = q.where(Appointment.contact_id == conv.contact_id)
        elif params.get("email"):
            contact = (
                await db.execute(
                    select(Contact).where(
                        Contact.tenant_id == tenant.id, Contact.email == params["email"]
                    )
                )
            ).scalar_one_or_none()
            if contact:
                q = q.where(Appointment.contact_id == contact.id)
        else:
            return ToolResult(
                "failed", {"reason": "référence manquante"},
                "Je ne trouve pas le rendez-vous à annuler : précisez la date ou le référence.",
            )
        rows = (await db.execute(q.order_by(Appointment.starts_at))).scalars().all()
        target_date = params.get("date")
        candidates = rows
        if target_date:
            candidates = [a for a in rows if a.starts_at.strftime("%Y-%m-%d") == target_date]
        if not candidates:
            return ToolResult(
                "failed", {"reason": "aucun rendez-vous trouvé"},
                "Aucun rendez-vous confirmé ne correspond à votre demande.",
            )
        appt = candidates[0]
    appt.status = "cancelled"
    await db.commit()
    return ToolResult(
        "success",
        {"appointment_id": appt.id, "starts_at": appt.starts_at.isoformat(), "status": "cancelled"},
        "Rendez-vous réellement annulé.",
    )


async def t_reschedule_appointment(
    db: AsyncSession, tenant: Tenant, conv: Conversation, params: dict, outcome: RuleOutcome
) -> ToolResult:
    new_starts = _parse_dt(str(params.get("date") or ""), str(params.get("time") or ""))
    if not new_starts:
        return ToolResult("failed", {"reason": "nouvelle date/heure invalide"}, "Nouvelle date ou heure invalide.")
    appt = None
    if params.get("appointment_id"):
        appt = await db.get(Appointment, str(params["appointment_id"]))
        if appt and appt.tenant_id != tenant.id:
            appt = None
    if appt is None:
        q = select(Appointment).where(
            Appointment.tenant_id == tenant.id, Appointment.status == "confirmed"
        )
        if conv.contact_id:
            q = q.where(Appointment.contact_id == conv.contact_id)
        rows = (await db.execute(q.order_by(Appointment.starts_at))).scalars().all()
        if not rows:
            return ToolResult("failed", {"reason": "aucun rendez-vous"}, "Aucun rendez-vous à déplacer.")
        target = params.get("original_date")
        appt = next((a for a in rows if a.starts_at.strftime("%Y-%m-%d") == target), rows[0])
    config = (
        await db.execute(
            select(ReceptionistConfig).where(ReceptionistConfig.tenant_id == tenant.id)
        )
    ).scalar_one_or_none()
    duration = int((appt.ends_at - appt.starts_at).total_seconds() // 60) or _service_duration(config, appt.service)
    slots = await find_free_slots(
        db, tenant, day=new_starts.date(), duration_minutes=duration,
        min_lead_hours=outcome.min_lead_hours, max_days_ahead=outcome.max_days_ahead,
        closed_days=outcome.closed_days, limit=200,
    )
    if not any(s["starts_at"][:19] == new_starts.isoformat()[:19] for s in slots):
        return ToolResult("failed", {"reason": "nouveau créneau indisponible"}, "Ce nouveau créneau n'est pas disponible.")
    old = appt.starts_at.isoformat()
    appt.starts_at = new_starts
    appt.ends_at = new_starts + timedelta(minutes=duration)
    await db.commit()
    return ToolResult(
        "success",
        {"appointment_id": appt.id, "old_starts_at": old, "starts_at": new_starts.isoformat()},
        "Rendez-vous réellement déplacé.",
    )


async def t_create_lead(
    db: AsyncSession, tenant: Tenant, conv: Conversation, params: dict, outcome: RuleOutcome
) -> ToolResult:
    score, reasons = _lead_score(params)
    contact = await _resolve_contact(db, tenant, conv, params)
    existing = None
    if conv.id:
        existing = (
            await db.execute(select(Lead).where(Lead.conversation_id == conv.id))
        ).scalar_one_or_none()
    if existing:
        for f in ("name", "email", "phone", "need", "service", "budget", "comment"):
            if params.get(f):
                setattr(existing, f, params[f])
        existing.score, existing.score_reasons = _lead_score(
            {**{k: getattr(existing, k) for k in ("name", "email", "phone", "need", "service", "budget", "urgency")}, **params}
        )
        await db.commit()
        return ToolResult("success", {"lead_id": existing.id, "score": existing.score}, "Fiche prospect mise à jour.")
    lead = Lead(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        contact_id=contact.id if contact else None,
        name=params.get("name") or (contact.name if contact else ""),
        email=params.get("email") or (contact.email if contact else ""),
        phone=params.get("phone") or (contact.phone if contact else ""),
        need=params.get("need") or "",
        service=params.get("service") or "",
        budget=params.get("budget") or "",
        urgency=str(params.get("urgency") or "normal"),
        source=conv.channel,
        comment=params.get("comment") or "",
        score=score,
        score_reasons=reasons,
        status="new",
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    return ToolResult(
        "success",
        {"lead_id": lead.id, "score": lead.score, "reasons": reasons},
        "Fiche prospect réellement créée.",
    )


async def t_update_customer(
    db: AsyncSession, tenant: Tenant, conv: Conversation, params: dict, outcome: RuleOutcome
) -> ToolResult:
    allowed = {"name", "email", "phone", "notes"}
    updates = {k: v for k, v in params.items() if k in allowed and v}
    if not updates:
        return ToolResult("failed", {"reason": "aucun champ autorisé fourni"}, "Aucune information autorisée à mettre à jour.")
    contact = await _resolve_contact(db, tenant, conv, {**updates, "email": updates.get("email", params.get("email"))})
    if not contact:
        return ToolResult("failed", {"reason": "contact introuvable"}, "Fiche client introuvable.")
    for k, v in updates.items():
        setattr(contact, k, v)
    await db.commit()
    return ToolResult("success", {"contact_id": contact.id, "updated": sorted(updates)}, "Fiche client mise à jour.")


async def t_send_email(
    db: AsyncSession, tenant: Tenant, conv: Conversation, params: dict, outcome: RuleOutcome
) -> ToolResult:
    to = params.get("to") or ""
    if "@" not in to:
        contact = await db.get(Contact, conv.contact_id) if conv.contact_id else None
        to = contact.email if contact else ""
    if "@" not in to:
        return ToolResult("failed", {"reason": "destinataire invalide"}, "Je n'ai pas d'adresse email valide pour envoyer la confirmation.")
    subject = params.get("subject") or "Confirmation"
    body = params.get("body") or ""
    if not settings.smtp_url:
        # Honest status: nothing was sent. The agent must not claim otherwise.
        return ToolResult(
            "failed",
            {"reason": "service d'email non configuré", "to": to},
            "L'envoi d'email n'est pas configuré pour le moment.",
        )
    db.add(EmailOutbox(tenant_id=tenant.id, to=to, subject=subject, body=body, status="queued"))
    await db.commit()
    return ToolResult("pending", {"to": to, "subject": subject}, "Email mis en file d'attente d'envoi.")


async def t_transfer_to_human(
    db: AsyncSession, tenant: Tenant, conv: Conversation, params: dict, outcome: RuleOutcome
) -> ToolResult:
    handoff = (
        await db.execute(
            select(Handoff).where(
                Handoff.conversation_id == conv.id, Handoff.status == "pending"
            )
        )
    ).scalar_one_or_none()
    if handoff:
        return ToolResult("success", {"handoff_id": handoff.id, "status": handoff.status}, "Transfert déjà en cours.")
    summary = build_handoff_summary(
        db=db, conv=conv, reason=str(params.get("reason") or "Demande client"),
        last_message=str(params.get("last_message") or ""),
        intent=str(params.get("intent") or ""),
    )
    handoff = Handoff(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        reason=str(params.get("reason") or "Demande client"),
        summary=summary,
        status="pending",
    )
    conv.status = "handoff"
    db.add(handoff)
    await db.commit()
    await db.refresh(handoff)
    return ToolResult("success", {"handoff_id": handoff.id, "status": "pending"}, "Demande transmise à un conseiller.")


def build_handoff_summary(
    *, db: AsyncSession | None, conv: Conversation, reason: str,
    history: list[dict] | None = None, last_message: str = "", intent: str = "",
) -> str:
    """Résumé généré avant transfert (cahier des charges §14)."""
    mem = conv.memory or {}
    parts = [
        f"Motif : {reason}",
        f"Intention principale : {intent or conv.intent or 'non déterminée'}",
    ]
    if last_message:
        parts.append(f"Dernier message client : {last_message[:300]}")
    known = {k: v for k, v in (mem.get("entities") or {}).items() if v}
    if known:
        parts.append("Identité/contexte connu : " + ", ".join(f"{k}={v}" for k, v in known.items()))
    if mem.get("actions"):
        parts.append("Actions déjà tentées : " + "; ".join(
            f"{a.get('tool')}→{a.get('status')}" for a in mem.get("actions", [])[-5:]
        ))
    if mem.get("summary"):
        parts.append(f"Résumé session : {mem['summary']}")
    return "\n".join(parts)


TOOL_REGISTRY: dict[str, Callable[[AsyncSession, Tenant, Conversation, dict, RuleOutcome], Coroutine]] = {
    "check_availability": t_check_availability,
    "create_appointment": t_create_appointment,
    "cancel_appointment": t_cancel_appointment,
    "reschedule_appointment": t_reschedule_appointment,
    "create_lead": t_create_lead,
    "update_customer": t_update_customer,
    "send_email": t_send_email,
    "transfer_to_human": t_transfer_to_human,
}


async def execute_tool(
    db: AsyncSession,
    tenant: Tenant,
    conv: Conversation,
    tool: str,
    params: dict,
    outcome: RuleOutcome,
) -> ToolResult:
    """Execute a tool for real and record the ActionExecution trace."""
    handler = TOOL_REGISTRY.get(tool)
    if handler is None:
        result = ToolResult("failed", {"reason": "outil inconnu", "tool": tool}, f"Outil « {tool} » inconnu.")
    elif outcome.require_human and tool not in ("transfer_to_human", "check_availability"):
        result = ToolResult(
            "failed", {"reason": "bloqué par règle métier", "rule": outcome.human_reason},
            "Action bloquée par une règle métier (escalade humaine requise).",
        )
    else:
        try:
            result = await handler(db, tenant, conv, params or {}, outcome)
        except Exception as exc:  # noqa: BLE001 — tools must never crash the conversation
            logger.exception("Erreur outil %s", tool)
            result = ToolResult("failed", {"reason": "exception", "error": str(exc)}, "L'action a échoué.")
    db.add(
        ActionExecution(
            tenant_id=tenant.id,
            conversation_id=conv.id,
            tool=tool,
            params=params or {},
            result=result.as_dict(),
            status=result.status,
        )
    )
    await db.commit()
    return result

"""Conversation Engine (cahier des charges §10).

Pipeline: Message → Intent → Context → Retrieval → Rules → Decision → Tool → Result → Response

The engine separates understanding from generation: the LLM (or the
deterministic policy) proposes, the Tool Engine verifies, and only verified
statuses are phrased back to the visitor.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..llm import orchestrator
from ..models import (
    Conversation,
    Message,
    ReceptionistConfig,
    Tenant,
)
from ..rag.retrieval import search_knowledge
from .policy import policy_decide, policy_reply
from .rules import evaluate_rules
from .tools import execute_tool

logger = logging.getLogger("ai_receptionist.engine")

MAX_TOOL_ROUNDS = 2
HISTORY_TAIL = 12


def _config_dict(config: ReceptionistConfig | None) -> dict:
    if not config:
        return {}
    return {
        "name": config.name,
        "tone": config.tone,
        "style": config.style,
        "language": config.language,
        "conciseness": config.conciseness,
        "greeting": config.greeting,
        "instructions": config.instructions or {},
        "services": config.services or [],
    }


def _tenant_dict(tenant: Tenant) -> dict:
    return {
        "name": tenant.name,
        "sector": tenant.sector,
        "phone": tenant.phone,
        "email": tenant.email,
        "address": tenant.address,
        "website": tenant.website,
        "timezone": tenant.timezone,
        "languages": tenant.languages,
    }


def _build_context(
    *,
    tenant: Tenant,
    config: ReceptionistConfig | None,
    conv: Conversation,
    raw_text: str,
    intent: str,
    confidence: float,
    entities: dict,
    rules_ctx: dict,
    kb_snippets: list[dict],
    tool_results: list[dict],
) -> dict:
    memory = dict(conv.memory or {})
    return {
        "company": _tenant_dict(tenant),
        "receptionist": _config_dict(config),
        "intent": intent,
        "confidence": confidence,
        "entities": entities,
        "raw_text": raw_text,
        "memory": memory,
        "conversation": {"id": conv.id, "status": conv.status, "channel": conv.channel},
        "kb_snippets": kb_snippets,
        "rules": rules_ctx,
        "tool_results": tool_results,
        "history": memory.get("history_tail") or [],
    }


async def handle_message(
    db: AsyncSession,
    tenant: Tenant,
    config: ReceptionistConfig | None,
    conversation: Conversation,
    text: str,
) -> dict:
    """Run the full pipeline for one inbound visitor message."""
    text = (text or "").strip()[:4000]
    memory = dict(conversation.memory or {})
    entities = dict(memory.get("entities") or {})
    tool_results: list[dict] = list(memory.get("last_tool_results") or [])

    # --- 1. Intent + entities ------------------------------------------------
    classified = await orchestrator.classify_intent(text)
    intent = classified["intent"]
    confidence = float(classified["confidence"])
    new_entities = {k: v for k, v in (classified.get("entities") or {}).items() if v}

    # slot choice / confirmation while awaiting a slot ("à 14h30", "le matin", "oui")
    if memory.get("stage") == "awaiting_slot_confirmation":
        from ..llm.intents import extract_time

        from .policy import _is_yes

        t = extract_time(text)
        if t:
            new_entities["time"] = t
            memory["chosen_slot"] = t
        if t or _is_yes({"raw_text": text}):
            intent = "APPOINTMENT"  # a slot answer belongs to the booking flow

    entities.update(new_entities)

    # service entity: match the tenant's configured services in the text
    if not entities.get("service") and config is not None:
        import unicodedata

        def _norm(s: str) -> str:
            s = unicodedata.normalize("NFD", s.lower())
            return "".join(c for c in s if unicodedata.category(c) != "Mn")

        low = _norm(text)
        for svc in config.services or []:
            name = str(svc.get("name") or "").strip()
            if name and _norm(name) in low:
                entities["service"] = name
                break

    unknown_streak = int(memory.get("unknown_streak") or 0)
    mid_booking = memory.get("stage") == "awaiting_slot_confirmation"
    if intent == "UNKNOWN" and not mid_booking:
        unknown_streak += 1
    elif intent != "GREETING":
        unknown_streak = 0
    memory["unknown_streak"] = unknown_streak  # visible to the policy in this turn's context

    # --- 2. Rules (always evaluated with the base intent; the conversation's
    #         main intent is stored once determined) --------------------------
    rules = await _evaluate_rules(db, tenant.id, intent, entities, conversation, unknown_streak, tool_results)
    rules_ctx = _rules_context(rules)

    # --- 3. Knowledge retrieval (tenant-isolated) ----------------------------
    kb_snippets: list[dict] = []
    if intent != "GREETING":
        kb_snippets = await search_knowledge(db, tenant.id, text, limit=5)

    ctx = _build_context(
        tenant=tenant, config=config, conv=conversation, raw_text=text,
        intent=intent, confidence=confidence, entities=entities,
        rules_ctx=rules_ctx, kb_snippets=kb_snippets, tool_results=tool_results,
    )

    # --- 4. Decision ---------------------------------------------------------
    decision = await orchestrator.decide(ctx) or policy_decide(ctx)

    # persist the conversation's main intent (skips GREETING intros)
    if intent not in ("GREETING", "UNKNOWN") or not conversation.intent:
        conversation.intent = intent

    # --- 5. Tool execution (verified) ----------------------------------------
    actions_done: list[dict] = list(memory.get("actions") or [])
    executed_this_turn: list[dict] = []
    budget = rules.max_actions_per_conversation - len(actions_done)
    for action in (decision.get("actions") or [])[:MAX_TOOL_ROUNDS * 2]:
        if budget <= 0:
            executed_this_turn.append({
                "tool": action.get("tool"), "status": "failed",
                "result": {"reason": "limite d'actions atteinte"},
                "message": "Limite d'actions automatiques atteinte.",
            })
            break
        budget -= 1
        result = await execute_tool(
            db, tenant, conversation, str(action.get("tool")), action.get("params") or {}, rules
        )
        entry = {"tool": action.get("tool"), **result.as_dict()}
        executed_this_turn.append(entry)
        actions_done.append({**entry, "at": datetime.now(timezone.utc).isoformat()})
        tool_results.append(entry)

    # --- 6. Final response (phrased from verified results) -------------------
    ctx = _build_context(
        tenant=tenant, config=config, conv=conversation, raw_text=text,
        intent=intent, confidence=confidence, entities=entities,
        rules_ctx=rules_ctx, kb_snippets=kb_snippets, tool_results=executed_this_turn or tool_results[-3:],
    )
    ctx["memory"] = {**memory, "entities": entities, "stage": (memory.get("stage") if not executed_this_turn else ctx["memory"].get("stage"))}

    final = None
    if orchestrator.get_provider() is not None:
        final = await orchestrator.decide(ctx)
    if final is None or not final.get("reply"):
        # policy_reply may return an action-only decision (e.g. slot confirmation)
        fallback = policy_reply(ctx)
        if fallback.get("actions") and not fallback.get("reply"):
            for action in fallback["actions"][:2]:
                result = await execute_tool(
                    db, tenant, conversation, str(action.get("tool")), action.get("params") or {}, rules
                )
                entry = {"tool": action.get("tool"), **result.as_dict()}
                executed_this_turn.append(entry)
                actions_done.append({**entry, "at": datetime.now(timezone.utc).isoformat()})
                tool_results.append(entry)
            ctx["tool_results"] = executed_this_turn
            again = policy_reply(ctx)
            final = again if again.get("reply") else {
                "reply": "Veuillez patienter, je finalise votre demande.",
                "escalate": False,
            }
        else:
            final = fallback

    reply = str(final.get("reply") or "").strip()
    escalate = bool(final.get("escalate"))
    escalate = escalate or rules.require_human  # a rule always wins
    if escalate and not any(a.get("tool") == "transfer_to_human" for a in executed_this_turn):
        reason = (
            rules.human_reason or (intent if intent != "UNKNOWN" else "Question incomprise")
        )
        result = await execute_tool(
            db, tenant, conversation, "transfer_to_human",
            {"reason": reason, "intent": intent, "last_message": text},
            rules,
        )
        executed_this_turn.append({"tool": "transfer_to_human", **result.as_dict()})
        if not reply:
            reply = "Je transmets votre demande à un conseiller humain qui saura vous répondre."

    if not reply:
        reply = "Merci de votre message. Un conseiller reviendra vers vous rapidement."

    # --- 7. Persist memory, messages, conversation ---------------------------
    tail = list(memory.get("history_tail") or [])
    tail.append({"role": "user", "content": text, "at": datetime.now(timezone.utc).isoformat()})
    tail.append({"role": "assistant", "content": reply})
    memory.update({
        "entities": entities,
        "history_tail": tail[-HISTORY_TAIL:],
        "actions": actions_done[-20:],
        "last_tool_results": executed_this_turn,
        "unknown_streak": unknown_streak,
        "stage": ctx["memory"].get("stage") or memory.get("stage") or "",
        "summary": _rolling_summary(tail),
    })
    if memory.get("stage") == "appointment_confirmed":
        memory["chosen_slot"] = None  # booking complete: reset the slot-choice flow
    conversation.memory = memory
    if intent not in ("GREETING", "UNKNOWN") or not conversation.intent:
        conversation.intent = intent
    conversation.confidence = confidence
    db.add(Message(
        tenant_id=tenant.id, conversation_id=conversation.id, role="user",
        content=text, intent=intent, confidence=confidence,
    ))
    db.add(Message(
        tenant_id=tenant.id, conversation_id=conversation.id, role="assistant",
        content=reply, intent=intent, confidence=confidence,
        sources=kb_snippets, meta={"actions": executed_this_turn},
    ))
    if conversation.status == "open" and any(
        a.get("tool") == "transfer_to_human" and a.get("status") == "success"
        for a in executed_this_turn
    ):
        conversation.status = "handoff"
    await db.commit()

    return {
        "conversation_id": conversation.id,
        "reply": reply,
        "intent": intent,
        "confidence": confidence,
        "sources": [
            {"source_id": s.get("source_id"), "name": s.get("name"), "snippet": (s.get("content") or "")[:220]}
            for s in kb_snippets[:3]
        ],
        "actions": executed_this_turn,
        "handoff": conversation.status == "handoff",
        "handoff_reason": rules.human_reason if rules.require_human else "",
    }


async def _load_rules(db: AsyncSession, tenant_id: str):
    from ..models import BusinessRule

    return (await db.execute(
        select(BusinessRule).where(BusinessRule.tenant_id == tenant_id, BusinessRule.enabled.is_(True))
    )).scalars().all()


async def _evaluate_rules(db, tenant_id, intent, entities, conversation, unknown_streak, tool_results):
    from .rules import evaluate_rules

    context = {
        "intent": intent,
        "entities": entities,
        "conversation": {"status": conversation.status},
        "channel": conversation.channel,
        "unknown_streak": unknown_streak,
        "tools_failed": sum(1 for t in tool_results if t.get("status") == "failed"),
    }
    return evaluate_rules(await _load_rules(db, tenant_id), context)


def _rules_context(rules) -> dict:
    return {
        "require_human": rules.require_human,
        "reason": rules.human_reason,
        "blocked": rules.block,
        "block_reason": rules.block_reason,
        "matched": rules.matched_rules,
        "constraints": {
            "min_lead_hours": rules.min_lead_hours,
            "max_days_ahead": rules.max_days_ahead,
            "require_fields": rules.require_fields,
            "allowed_services": rules.allowed_services,
            "closed_days": rules.closed_days,
        },
        "max_actions_per_conversation": rules.max_actions_per_conversation,
        "unknown_streak_handoff": rules.unknown_streak_handoff,
    }


def _rolling_summary(history: list[dict]) -> str:
    user_msgs = [h["content"] for h in history if h.get("role") == "user"]
    if not user_msgs:
        return ""
    return " | ".join(user_msgs[-3:])[:400]

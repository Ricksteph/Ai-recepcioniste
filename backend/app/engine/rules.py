"""Business rules engine (cahier des charges §9).

Rules are stored per tenant and evaluated deterministically BEFORE and AFTER
any LLM involvement. The LLM cannot override a rule outcome.

Condition grammar (JSON):
  {"all": [<cond>...], "any": [<cond>...], "not": <cond>}
  leaf: {"field": "intent", "op": "in", "value": ["APPOINTMENT"]}
  ops: eq | ne | in | not_in | gte | lte | gt | lt | contains | exists
  Fields: intent, entities.<key>, conversation.status, channel, always,
          unknown_streak, tools_failed
"""
from dataclasses import dataclass, field

from ..models import BusinessRule

_OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "in": lambda a, b: a in (b or []),
    "not_in": lambda a, b: a not in (b or []),
    "gte": lambda a, b: a is not None and a >= b,
    "lte": lambda a, b: a is not None and a <= b,
    "gt": lambda a, b: a is not None and a > b,
    "lt": lambda a, b: a is not None and a < b,
    "contains": lambda a, b: bool(b) and b in str(a or ""),
    "exists": lambda a, b: bool(a) is not bool(b),
}


def _resolve(ctx: dict, dotted: str):
    node = ctx
    for part in dotted.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node


def evaluate_condition(cond: dict, ctx: dict) -> bool:
    if not cond:
        return True
    if "all" in cond:
        return all(evaluate_condition(c, ctx) for c in cond["all"])
    if "any" in cond:
        return any(evaluate_condition(c, ctx) for c in cond["any"])
    if "not" in cond:
        return not evaluate_condition(cond["not"], ctx)
    field_ = cond.get("field", "")
    op = cond.get("op", "eq")
    fn = _OPS.get(op)
    if fn is None or not field_:
        return True  # malformed leaf: fail-open, rules are logged separately
    try:
        return bool(fn(_resolve(ctx, field_), cond.get("value")))
    except TypeError:
        return False


@dataclass
class RuleOutcome:
    require_human: bool = False
    human_reason: str = ""
    block: bool = False
    block_reason: str = ""
    # constraints consumed by the Tool Engine / availability computation
    min_lead_hours: float = 0.0
    max_days_ahead: int = 90
    require_fields: list[str] = field(default_factory=list)
    allowed_services: list[str] = field(default_factory=list)
    closed_days: list[str] = field(default_factory=list)
    max_actions_per_conversation: int = 8
    unknown_streak_handoff: int = 2
    matched_rules: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def evaluate_rules(rules: list[BusinessRule], context: dict) -> RuleOutcome:
    """Evaluate enabled rules by ascending priority. Later matches win on conflicts."""
    outcome = RuleOutcome()
    for rule in sorted(rules, key=lambda r: r.priority):
        if not rule.enabled:
            continue
        ctx = {**context, "rule_kind": rule.kind}
        if not evaluate_condition(rule.condition or {}, ctx):
            continue
        outcome.matched_rules.append(rule.name)
        params = rule.params or {}
        if rule.action == "require_human":
            outcome.require_human = True
            outcome.human_reason = rule.description or rule.name
        elif rule.action == "block":
            outcome.block = True
            outcome.block_reason = rule.description or rule.name
        elif rule.action == "set":
            if "min_lead_hours" in params:
                outcome.min_lead_hours = float(params["min_lead_hours"])
            if "max_days_ahead" in params:
                outcome.max_days_ahead = int(params["max_days_ahead"])
            if "require_fields" in params:
                outcome.require_fields = [str(f) for f in params["require_fields"]]
            if "allowed_services" in params:
                outcome.allowed_services = [str(s) for s in params["allowed_services"]]
            if "closed_days" in params:
                outcome.closed_days = [str(d).lower() for d in params["closed_days"]]
            if "max_actions_per_conversation" in params:
                outcome.max_actions_per_conversation = int(params["max_actions_per_conversation"])
            if "unknown_streak_handoff" in params:
                outcome.unknown_streak_handoff = int(params["unknown_streak_handoff"])
    return outcome


def default_rules_payload() -> list[dict]:
    """Règles par défaut créées à l'onboarding d'un tenant (modifiables ensuite)."""
    return [
        {
            "name": "Transfert sur demande explicite",
            "kind": "transfer",
            "condition": {"field": "intent", "op": "in", "value": ["HUMAN_TRANSFER"]},
            "action": "require_human",
            "params": {},
            "description": "Le client demande à parler à un humain",
            "priority": 10,
        },
        {
            "name": "Transfert sur plainte",
            "kind": "transfer",
            "condition": {"field": "intent", "op": "in", "value": ["COMPLAINT"]},
            "action": "require_human",
            "params": {},
            "description": "Plainte ou réclamation détectée",
            "priority": 20,
        },
        {
            "name": "Délai minimum de réservation",
            "kind": "appointment",
            "condition": {"field": "intent", "op": "in", "value": ["APPOINTMENT", "RESCHEDULING"]},
            "action": "set",
            "params": {"min_lead_hours": 2, "max_days_ahead": 60, "require_fields": ["date"]},
            "description": "Interdire un rendez-vous moins de 2h à l'avance",
            "priority": 30,
        },
        {
            "name": "Information inconnue → humain",
            "kind": "unknown",
            "condition": {"field": "intent", "op": "in", "value": ["UNKNOWN"]},
            "action": "set",
            "params": {"unknown_streak_handoff": 2},
            "description": "Après 2 questions incompréhensives, proposer un humain",
            "priority": 40,
        },
        {
            "name": "Limite d'actions automatiques",
            "kind": "action_limit",
            "condition": {"always": True},
            "action": "set",
            "params": {"max_actions_per_conversation": 8},
            "description": "Sécurité : nombre maximal d'actions automatiques par conversation",
            "priority": 50,
        },
        {
            "name": "Pas de réservation le dimanche",
            "kind": "hours",
            "condition": {"always": True},
            "action": "set",
            "params": {"closed_days": ["sunday"]},
            "description": "Jour de fermeture hebdomadaire",
            "priority": 60,
        },
    ]

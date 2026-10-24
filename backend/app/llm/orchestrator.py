"""AI Orchestrator — thin facade over providers (cahier des charges §20).

Responsibilities:
- classify_intent: LLM-first JSON classification with deterministic fallback.
- decide: produce a structured conversation decision (reply / actions / escalate)
  using the LLM when available. The Conversation Engine never trusts it blindly:
  tool parameters are validated and tool results verified by the Tool Engine.
"""
import json
import logging
import re

from .intents import classify_keywords, extract_entities
from .providers import (
    ChatProvider,
    ProviderError,
    embed_texts,
    local_embed,
    resolve_chat_provider,
)

logger = logging.getLogger("ai_receptionist.orchestrator")

_provider: ChatProvider | None | bool = False  # False = not resolved yet


def get_provider() -> ChatProvider | None:
    global _provider
    if _provider is False:
        _provider = resolve_chat_provider()
        logger.info("LLM provider résolu : %s", _provider.name if _provider else "policy locale")
    return _provider


def reset_provider_cache() -> None:
    """Used by tests after changing settings."""
    global _provider
    _provider = False


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z]*\n?|```$", "", candidate).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


async def classify_intent(text: str) -> dict:
    """Return {intent, confidence, entities}. LLM-first with keyword fallback."""
    entities = extract_entities(text)
    provider = get_provider()
    if provider is not None:
        system = (
            "Tu es le module de classification d'intentions d'un réceptionniste IA. "
            "Classe le message utilisateur parmi : "
            + ", ".join(
                [
                    "GREETING", "INFORMATION", "SERVICE_REQUEST", "PRICE_REQUEST",
                    "QUOTE_REQUEST", "APPOINTMENT", "CANCELLATION", "RESCHEDULING",
                    "COMPLAINT", "SUPPORT", "PURCHASE", "HUMAN_TRANSFER", "UNKNOWN",
                ]
            )
            + ". Réponds UNIQUEMENT par un JSON: "
            '{"intent": "...", "confidence": 0.0, "entities": {"name": null, '
            '"email": null, "phone": null, "date": "YYYY-MM-DD", "time": "HH:MM:SS", '
            '"service": null, "budget": null, "urgency": null}}'
        )
        try:
            raw = await provider.chat(
                [{"role": "system", "content": system}, {"role": "user", "content": text}],
                temperature=0.0,
                max_tokens=250,
                json_mode=True,
            )
            data = _extract_json(raw)
            if data and data.get("intent"):
                intent = str(data["intent"]).upper().strip()
                known = {
                    "GREETING", "INFORMATION", "SERVICE_REQUEST", "PRICE_REQUEST",
                    "QUOTE_REQUEST", "APPOINTMENT", "CANCELLATION", "RESCHEDULING",
                    "COMPLAINT", "SUPPORT", "PURCHASE", "HUMAN_TRANSFER", "UNKNOWN",
                }
                if intent in known:
                    merged = {**entities, **{k: v for k, v in (data.get("entities") or {}).items() if v}}
                    try:
                        confidence = float(data.get("confidence") or 0.7)
                    except (TypeError, ValueError):
                        confidence = 0.7
                    return {
                        "intent": intent,
                        "confidence": max(0.0, min(confidence, 1.0)),
                        "entities": merged,
                    }
        except ProviderError as exc:
            logger.warning("Classification LLM échouée (%s) — fallback mots-clés", exc)

    intent, confidence = classify_keywords(text)
    return {"intent": intent, "confidence": confidence, "entities": entities}


async def decide(prompt_context: dict) -> dict | None:
    """Ask the LLM for a structured decision.

    Returns {"reply": str, "actions": [{"tool": str, "params": dict}], "escalate": bool}
    or None when no LLM is configured (caller uses the deterministic policy).
    """
    provider = get_provider()
    if provider is None:
        return None
    system = (
        "Tu es le moteur de décision du réceptionniste IA d'une entreprise. "
        "Tu reçois : le profil du réceptionniste, les règles métier évaluées, "
        "les extraits de la base de connaissances, la mémoire de conversation, "
        "l'intention détectée et les résultats réels des actions déjà exécutées. "
        "Réponds UNIQUEMENT par un JSON : "
        '{"reply": "message pour le client (français, ton du réceptionniste)", '
        '"actions": [{"tool": "nom_outil", "params": {...}}], '
        '"escalate": false, "need_info": ["champ_manquant"]}. '
        "Règles absolues : ne déclare JAMAIS une action réussie sans résultat réel dans le contexte ; "
        "si une action a échoué, explique et propose un humain si nécessaire ; "
        "n'invente jamais de prix, horaire ou disponibilité hors contexte ; "
        "si l'information est absente de la base de connaissances, dis-le honnêtement."
    )
    try:
        raw = await provider.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(prompt_context, ensure_ascii=False, default=str)},
            ],
            temperature=0.3,
            max_tokens=800,
            json_mode=True,
        )
        data = _extract_json(raw)
        if not data or "reply" not in data:
            logger.warning("Décision LLM malformée — fallback policy locale")
            return None
        actions = data.get("actions") or []
        clean_actions = []
        for a in actions:
            if isinstance(a, dict) and a.get("tool"):
                clean_actions.append(
                    {"tool": str(a["tool"]), "params": a.get("params") or {}}
                )
        return {
            "reply": str(data.get("reply") or ""),
            "actions": clean_actions[:3],
            "escalate": bool(data.get("escalate")),
            "need_info": [str(x) for x in (data.get("need_info") or [])][:6],
        }
    except ProviderError as exc:
        logger.warning("Décision LLM échouée (%s) — fallback policy locale", exc)
        return None


async def embed(texts: list[str]) -> list[list[float]]:
    return await embed_texts(texts)


def embed_local(text: str) -> list[float]:
    return local_embed(text)

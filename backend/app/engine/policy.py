"""Deterministic conversation policy (offline fallback for the AI Orchestrator).

When no LLM provider is configured, this module produces the decision and the
final reply. It is fully functional: intent + collected entities + KB snippets +
rule outcomes drive real tool executions through the same Tool Engine. This
keeps the product testable end-to-end without any external API key.
"""
import re

SNIPPET_LEN = 420


def _best_snippets(ctx: dict, keywords: list[str], limit: int = 2) -> list[dict]:
    scored: list[tuple[int, dict]] = []
    for s in ctx.get("kb_snippets") or []:
        text = str(s.get("content") or "")
        score = sum(1 for k in keywords if k and k in text.lower())
        scored.append((score, s))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for score, s in scored if score >= 0][:limit]


def _snippet_text(s: dict) -> str:
    # `focus` is the window of the chunk closest to the query terms (retrieval)
    text = re.sub(r"\s+", " ", str(s.get("focus") or s.get("content") or "")).strip()
    # strip markdown heading markers for a cleaner spoken reply
    text = re.sub(r"^#+\s*", "", text)
    return text[:SNIPPET_LEN] + ("…" if len(text) > SNIPPET_LEN else "")


def _service_line(ctx: dict) -> str:
    services = (ctx.get("receptionist") or {}).get("services") or []
    if not services:
        return ""
    parts = []
    for s in services:
        name = s.get("name")
        if not name:
            continue
        desc = f" — {s['description']}" if s.get("description") else ""
        price = f" ({s['price']})" if s.get("price") else ""
        parts.append(f"• {name}{desc}{price}")
    return "\n".join(parts)


def _memory(ctx: dict) -> dict:
    return ctx.get("memory") or {}


def _entities(ctx: dict) -> dict:
    return {k: v for k, v in (ctx.get("entities") or {}).items() if v}


def _missing_appointment_info(ctx: dict) -> list[str]:
    ent = _entities(ctx)
    missing = []
    if not ent.get("date"):
        missing.append("date")
    if not ent.get("time"):
        missing.append("heure")
    if not ent.get("name"):
        missing.append("nom")
    return missing


def _tone_prefix(ctx: dict) -> str:
    name = (ctx.get("receptionist") or {}).get("name") or ""
    return ""


def policy_decide(ctx: dict) -> dict:
    """Phase 1 — choose actions to execute. Returns a decision dict."""
    intent = ctx.get("intent") or "UNKNOWN"
    rules = ctx.get("rules") or {}
    mem = _memory(ctx)
    ent = _entities(ctx)
    tools_done = {t.get("tool"): t for t in (ctx.get("tool_results") or [])}

    # Escalation requested by rules takes priority
    if rules.get("require_human") and intent != "GREETING":
        return {
            "reply": "",
            "actions": [{"tool": "transfer_to_human", "params": {
                "reason": rules.get("reason") or "Règle métier",
                "intent": intent, "last_message": ctx.get("raw_text", ""),
            }}],
            "escalate": True,
            "need_info": [],
        }

    if intent == "HUMAN_TRANSFER" or intent == "COMPLAINT":
        return {
            "reply": "",
            "actions": [{"tool": "transfer_to_human", "params": {
                "reason": f"Intention {intent}",
                "intent": intent, "last_message": ctx.get("raw_text", ""),
            }}],
            "escalate": True,
            "need_info": [],
        }

    if intent == "APPOINTMENT":
        # Mid-flow: slot + time already known → book directly
        if mem.get("stage") == "awaiting_slot_confirmation" and ent.get("date") and ent.get("time"):
            params = {
                "date": ent.get("date"), "time": ent.get("time"),
                "service": ent.get("service") or mem.get("service") or "",
                **{k: ent.get(k) for k in ("name", "email", "phone") if ent.get(k)},
            }
            return {
                "reply": "", "escalate": False, "need_info": [],
                "actions": [{"tool": "create_appointment", "params": {k: v for k, v in params.items() if v}}],
            }
        # Ensure contact card exists when we have data
        actions = []
        if ent.get("email") or ent.get("phone") or ent.get("name"):
            actions.append({"tool": "update_customer", "params": dict(ent)})
        if ent.get("date"):
            actions.append({
                "tool": "check_availability",
                "params": {"date": ent.get("date"), "service": ent.get("service") or ""},
            })
        return {"reply": "", "actions": actions[:2], "escalate": False, "need_info": _missing_appointment_info(ctx)}

    if intent == "CANCELLATION":
        return {
            "reply": "",
            "actions": [{"tool": "cancel_appointment", "params": {"date": ent.get("date")}}],
            "escalate": False,
            "need_info": [] if ent.get("date") else ["date du rendez-vous"],
        }

    if intent == "RESCHEDULING":
        if not ent.get("date"):
            return {"reply": "", "actions": [], "escalate": False, "need_info": ["nouvelle date"]}
        return {
            "reply": "",
            "actions": [{"tool": "reschedule_appointment", "params": {"date": ent.get("date"), "time": ent.get("time"), "original_date": ent.get("original_date")}}],
            "escalate": False,
            "need_info": [],
        }

    if intent in ("QUOTE_REQUEST", "PURCHASE", "SUPPORT") and (ent.get("email") or ent.get("phone") or ent.get("name")):
        return {
            "reply": "",
            "actions": [{"tool": "create_lead", "params": {**ent, "need": ent.get("need") or ctx.get("raw_text", "")}}],
            "escalate": False,
            "need_info": [],
        }

    return {"reply": "", "actions": [], "escalate": False, "need_info": []}


def _phrase_tool_outcomes(ctx: dict) -> tuple[str, bool] | None:
    """Turn verified tool results into honest sentences. Returns (text, escalate)."""
    results = ctx.get("tool_results") or []
    if not results:
        return None
    ent = _entities(ctx)
    lines: list[str] = []
    escalate = False

    for r in results:
        tool, status, res, msg = r.get("tool"), r.get("status"), r.get("result") or {}, r.get("message") or ""

        if tool == "check_availability":
            if status == "success":
                slots = res.get("slots") or []
                when = ent.get("date")
                listing = "\n".join(
                    f"  – {s['starts_at'][:10]} à {s['starts_at'][11:16]}" for s in slots[:5]
                )
                lines.append(
                    f"Voici les créneaux disponibles{f' le {when}' if when else ' prochainement'} :\n{listing}"
                    "\nLequel vous convient ? Je le réserve dès votre confirmation."
                )
                lines.append("__STAGE:awaiting_slot_confirmation")
            else:
                lines.append(
                    "Je suis désolé, aucun créneau ne correspond à votre demande selon nos horaires d'ouverture. "
                    "Puis-je vous proposer de parler à un conseiller ?"
                )
                escalate = True

        elif tool == "create_appointment":
            if status == "success":
                starts = str(res.get("starts_at") or "")
                lines.append(
                    f"✅ C'est confirmé ! Votre rendez-vous est réservé le {starts[:10]} à {starts[11:16]} "
                    f"({res.get('service') or 'rendez-vous'})."
                )
                lines.append("__STAGE:appointment_confirmed")
            else:
                lines.append(f"Le rendez-vous n'a pas pu être enregistré : {msg or 'raison inconnue'}.")
                lines.append("Souhaitez-vous qu'un conseiller prenne le relais ?")
                escalate = True

        elif tool == "cancel_appointment":
            if status == "success":
                starts = str(res.get("starts_at") or "")
                lines.append(f"✅ Votre rendez-vous du {starts[:10]} à {starts[11:16]} a bien été annulé.")
            else:
                lines.append(f"Je n'ai pas pu annuler : {msg or 'rendez-vous introuvable'}.")
                escalate = True

        elif tool == "reschedule_appointment":
            if status == "success":
                starts = str(res.get("starts_at") or "")
                lines.append(f"✅ C'est noté : votre rendez-vous a été déplacé au {starts[:10]} à {starts[11:16]}.")
            else:
                lines.append(f"Je n'ai pas pu déplacer le rendez-vous : {msg}.")
                escalate = True

        elif tool == "create_lead":
            if status == "success":
                lines.append("J'ai bien noté votre demande, un conseiller vous recontactera très vite.")
            else:
                lines.append("Je n'ai pas pu enregistrer votre demande.")

        elif tool == "transfer_to_human":
            if status == "success":
                lines.append(
                    "Je transmets votre demande à un conseiller humain qui va prendre le relais. "
                    "Merci de votre patience."
                )
                escalate = True

        elif tool == "send_email":
            if status == "success":
                lines.append("La confirmation est en cours d'envoi par email.")
            elif status == "pending":
                lines.append("La confirmation est en file d'attente d'envoi.")
            else:
                lines.append("Je ne peux pas envoyer d'email pour le moment, mais le rendez-vous est bien noté.")

        elif tool == "update_customer":
            pass  # silent bookkeeping

    text = "\n".join(l for l in lines if not l.startswith("__STAGE"))
    for l in lines:
        if l.startswith("__STAGE:"):
            mem = ctx.get("memory") or {}
            mem["stage"] = l.split(":", 1)[1]
            ctx["memory"] = mem
    return text, escalate


def policy_reply(ctx: dict) -> dict:
    """Phase 2 — final reply, phrased ONLY from verified results and known data."""
    intent = ctx.get("intent") or "UNKNOWN"
    rules = ctx.get("rules") or {}
    ent = _entities(ctx)
    mem = _memory(ctx)
    stage = mem.get("stage") or ""

    # 1) Tool outcomes dominate the reply
    phrased = _phrase_tool_outcomes(ctx)
    if phrased:
        text, escalate = phrased
        if text:
            return {"reply": text, "actions": [], "escalate": escalate, "need_info": []}

    # 2) Mid-flow: user confirmed a slot or answered with a time
    if stage == "awaiting_slot_confirmation" and intent in (
        "APPOINTMENT", "INFORMATION", "GREETING", "SERVICE_REQUEST", "UNKNOWN",
    ):
        chosen = mem.get("chosen_slot") or ent.get("time")
        date = ent.get("date") or mem.get("chosen_date")
        confirmed = bool(ent.get("confirm_yes")) or _is_yes(ctx) or bool(mem.get("chosen_slot"))
        if date and chosen and confirmed:
            params = {
                "date": date,
                "time": chosen if ":" in str(chosen) else None,
                "service": ent.get("service") or mem.get("service") or "",
                **{k: ent.get(k) for k in ("name", "email", "phone") if ent.get(k)},
            }
            return {
                "reply": "",
                "actions": [{"tool": "create_appointment", "params": {k: v for k, v in params.items() if v}}],
                "escalate": False,
                "need_info": [],
            }
        if not date:
            return {
                "reply": "Pour quel jour souhaitez-vous venir ?",
                "actions": [], "escalate": False, "need_info": ["date"],
            }
        if not chosen:
            return {
                "reply": "À quelle heure souhaitez-vous venir ? Je réserve dès que vous me le dites.",
                "actions": [], "escalate": False, "need_info": ["heure"],
            }

    # 3) Intent-specific template answers
    receptionist = ctx.get("receptionist") or {}
    company = ctx.get("company") or {}
    name = receptionist.get("name") or "l'assistant"

    if intent == "GREETING":
        greeting = receptionist.get("greeting") or f"Bonjour ! Je suis {name}. Comment puis-je vous aider ?"
        return {"reply": greeting, "actions": [], "escalate": False, "need_info": []}

    if intent == "INFORMATION":
        snippets = _best_snippets(ctx, ["horaire", "ouvert", "adresse", "où", "ou", "accès", "parking", "comment", "fermé"])
        if snippets:
            body = " ".join(_snippet_text(s) for s in snippets[:1])
            return {
                "reply": f"D'après nos informations : {body}",
                "actions": [],
                "escalate": False,
                "need_info": [],
            }
        return {
            "reply": "Je ne trouve pas cette information dans nos documents. Je peux demander à un conseiller de vous répondre précisément.",
            "actions": [],
            "escalate": True,
            "need_info": [],
        }

    if intent == "SERVICE_REQUEST":
        line = _service_line(ctx)
        snippets = _best_snippets(ctx, ["service", "prestation", "propose", "séance", "seance"])
        extra = f"\n{_snippet_text(snippets[0])}" if snippets else ""
        if line or extra:
            return {
                "reply": f"Voici ce que nous proposons :\n{line}{extra}".strip(),
                "actions": [],
                "escalate": False,
                "need_info": [],
            }
        return {
            "reply": "Je n'ai pas la liste de nos prestations sous les yeux. Un conseiller pourra vous renseigner.",
            "actions": [],
            "escalate": True,
            "need_info": [],
        }

    if intent == "PRICE_REQUEST":
        snippets = _best_snippets(ctx, ["prix", "tarif", "€", "eur", "coût", "cout", "combien"])
        if snippets:
            return {
                "reply": f"Concernant les tarifs : {_snippet_text(snippets[0])}",
                "actions": [],
                "escalate": False,
                "need_info": [],
            }
        return {
            "reply": "Je n'ai pas la grille tarifaire disponible ici. Je peux transmettre votre demande à un conseiller qui vous enverra un devis précis.",
            "actions": [{"tool": "create_lead", "params": {**ent, "need": "Demande de prix / devis"}}] if (ent.get("email") or ent.get("phone") or ent.get("name")) else [],
            "escalate": False,
            "need_info": ["email"] if not ent.get("email") else [],
        }

    if intent == "QUOTE_REQUEST":
        if ent.get("email") or ent.get("phone"):
            return {
                "reply": "J'ai enregistré votre demande de devis, un conseiller vous recontactera avec une proposition chiffrée.",
                "actions": [{"tool": "create_lead", "params": {**ent, "need": ent.get("need") or "Demande de devis"}}],
                "escalate": False,
                "need_info": [],
            }
        return {
            "reply": "Avec plaisir. Pour vous préparer un devis, quelle est votre adresse email ou votre téléphone ?",
            "actions": [],
            "escalate": False,
            "need_info": ["email"],
        }

    if intent == "APPOINTMENT":
        missing = _missing_appointment_info(ctx)
        if "date" in missing:
            services = _service_line(ctx)
            hint = f"\nNos prestations :\n{services}" if services else ""
            return {
                "reply": f"Bien sûr, je peux vous proposer un rendez-vous. Pour quel jour souhaitez-vous venir ?{hint}",
                "actions": [],
                "escalate": False,
                "need_info": missing,
            }
        if "heure" in missing:
            return {
                "reply": "Quelle heure vous conviendra le mieux ? Je vérifie les disponibilités réelles.",
                "actions": [],
                "escalate": False,
                "need_info": missing,
            }
        if "nom" in missing:
            return {
                "reply": "Parfait. À quel nom puis-je vous indiquer le rendez-vous ?",
                "actions": [],
                "escalate": False,
                "need_info": missing,
            }
        return {
            "reply": "Je vérifie les disponibilités…",
            "actions": [{"tool": "check_availability", "params": {"date": ent.get("date"), "service": ent.get("service") or ""}}],
            "escalate": False,
            "need_info": [],
        }

    if intent == "SUPPORT":
        snippets = _best_snippets(ctx, ["aide", "support", "problème", "probleme", "erreur", "maintenance", "fonctionne"])
        if snippets:
            return {
                "reply": f"Voici ce qui pourrait vous aider : {_snippet_text(snippets[0])}",
                "actions": [],
                "escalate": False,
                "need_info": [],
            }
        return {
            "reply": "Votre problème nécessite l'intervention d'un technicien. Je vous mets en relation avec un conseiller.",
            "actions": [{"tool": "transfer_to_human", "params": {"reason": "Support technique"}}],
            "escalate": True,
            "need_info": [],
        }

    if intent == "PURCHASE":
        snippets = _best_snippets(ctx, ["acheter", "commande", "inscription", "abonnement", "commander"])
        reply = f"Voici les informations : {_snippet_text(snippets[0])}" if snippets else "Je transmets votre demande d'achat à un conseiller."
        actions = [{"tool": "create_lead", "params": {**ent, "need": "Demande d'achat"}}] if (ent.get("email") or ent.get("phone")) else []
        return {"reply": reply, "actions": actions, "escalate": not snippets, "need_info": []}

    # UNKNOWN / fallback
    streak = int(mem.get("unknown_streak") or 0)
    threshold = rules.get("unknown_streak_handoff") or 2
    if streak >= threshold:
        return {
            "reply": "Je crains de ne pas bien comprendre. Je vous mets en relation avec un conseiller qui saura vous aider.",
            "actions": [{"tool": "transfer_to_human", "params": {
                "reason": "Question incompréhensible à répétition",
                "intent": intent, "last_message": ctx.get("raw_text", ""),
            }}],
            "escalate": True,
            "need_info": [],
        }
    return {
        "reply": "Pourriez-vous reformuler votre question ? Je peux renseigner nos horaires, nos prestations, les tarifs, ou vous proposer un rendez-vous.",
        "actions": [],
        "escalate": False,
        "need_info": ["reformulation"],
    }


def _is_yes(ctx: dict) -> bool:
    text = str(ctx.get("raw_text") or "").lower().strip()
    return bool(re.match(r"^(oui|ok|okey|yes|go|parfait|d'accord|dacord|c'est bon|vas-y|yes please)[!.\s]*$", text))

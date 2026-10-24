"""Deterministic intent classification + entity extraction (FR/EN).

Used as the offline baseline and as a safety net when the LLM is unavailable
or returns malformed output. Intent set comes from cahier des charges §11.
"""
import re
from datetime import datetime, timedelta, timezone

INTENTS = [
    "GREETING",
    "INFORMATION",
    "SERVICE_REQUEST",
    "PRICE_REQUEST",
    "QUOTE_REQUEST",
    "APPOINTMENT",
    "CANCELLATION",
    "RESCHEDULING",
    "COMPLAINT",
    "SUPPORT",
    "PURCHASE",
    "HUMAN_TRANSFER",
    "UNKNOWN",
]

_KEYWORDS: dict[str, list[str]] = {
    "GREETING": [
        "bonjour", "bonsoir", "salut", "hello", "hi ", "hey", "bjr",
        "good morning", "good evening", "coucou",
    ],
    "APPOINTMENT": [
        "rendez-vous", "rendez vous", "rdv", "réserver", "reserver", "prendre rdv",
        "disponible", "disponibilité", "disponibilite", "creneau", "créneau",
        "slot", "appointment", "booking", "calendar", "calendrier", "sur quel horaire",
        "quel horaire", "quand pouvez", "pouvoir passer", "venir quand",
    ],
    "CANCELLATION": [
        "annuler", "annulation", "cancel", "ne viendrai pas", "ne pas venir",
        "reporter impossible", "supprimer mon rdv",
    ],
    "RESCHEDULING": [
        "reporter", "déplacer", "deplacer", "changer de créneau", "changer de creneau",
        "reschedule", "décaler", "decaler", "autre créneau", "autre creneau",
    ],
    "PRICE_REQUEST": [
        "prix", "tarif", "combien", "coût", "cout", "tarification", "price",
        "how much", "c'est cher", "cest cher", "montant",
    ],
    "QUOTE_REQUEST": [
        "devis", "estimate", "estimation", "chiffrer", "proposition de prix",
        " devis ", "faire un devis",
    ],
    "COMPLAINT": [
        "plainte", "mécontent", "mecontent", "scandale", "honte", "nul", "dégoût",
        "degout", "arnaque", "maltraité", "maltraite", "réclamation", "reclamation",
        "insatisfait", "terrible", "awful", "complaint",
    ],
    "SUPPORT": [
        "problème", "probleme", "bug", "erreur", "ne fonctionne pas", "panne",
        "aide", "help", "support", "réparer", "reparer", "maintenance",
        "question technique", "bloqué", "bloque",
    ],
    "PURCHASE": [
        "acheter", "achat", "commander", "commande", "s'inscrire", "inscrire",
        "prendre un abonnement", "purchase", "buy", "order", "subscribe",
    ],
    "SERVICE_REQUEST": [
        "prestation", "service", "proposez", "propose", "vous faites", "vous faites",
        "séance", "seance", "consultation", "intervention", "accompagnement",
        "what do you offer", "vos services",
    ],
    "HUMAN_TRANSFER": [
        "humain", "un conseiller", "un agent", "quelqu'un", "quelquun",
        "parler à personne", "speak to", "human", "real person", "téléphonez",
        "appeler un",
    ],
    "INFORMATION": [
        "où", "ou êtes", "adresse", "horaires", "ouverture", "fermé", "ferme",
        "parking", "comment venir", "accès", "acces", "itinéraire", "itinaire",
        "where", "opening hours", "address", "how to get",
    ],
}

_DATE_WORDS = {
    "aujourd'hui": 0, "aujourd hui": 0, "cejourd": 0, "today": 0,
    "demain": 1, "tomorrow": 1,
    "après-demain": 2, "apres-demain": 2,
    "lundi": None, "mardi": None, "mercredi": None, "jeudi": None,
    "vendredi": None, "samedi": None, "dimanche": None,
}
_WEEKDAYS = {
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3,
    "vendredi": 4, "samedi": 5, "dimanche": 6,
}
_MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}


def _next_weekday(target: int) -> datetime:
    today = datetime.now(timezone.utc)
    delta = (target - today.weekday()) % 7 or 7
    return today + timedelta(days=delta)


def extract_date(text: str) -> str | None:
    """Return an ISO date (YYYY-MM-DD) if the text mentions one, else None."""
    low = text.lower()
    today = datetime.now(timezone.utc)
    # ISO date first (2026-10-26) so it is not misread as day-month
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            pass
    for word, offset in _DATE_WORDS.items():
        if word in low:
            if offset is not None:
                return (today + timedelta(days=offset)).strftime("%Y-%m-%d")
            for name, wd in _WEEKDAYS.items():
                if name in word or word in name:
                    return _next_weekday(wd).strftime("%Y-%m-%d")
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
        year = int(year) if year else today.year
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\b", low)
    if m:
        day, month_name = int(m.group(1)), m.group(2)
        month = _MONTHS[month_name]
        year = today.year
        try:
            candidate = datetime(year, month, day)
        except ValueError:
            return None
        if candidate.date() < today.date():
            year += 1
        return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def extract_time(text: str) -> str | None:
    """Return HH:MM if the text mentions a time."""
    m = re.search(r"\b([01]?\d|2[0-3])\s*[h:]\s*([0-5]\d)?\b", text)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2) or '00'}:00"
    for word, hour in {"matin": 10, "midi": 12, "après-midi": 15, "apres-midi": 15, "soir": 18}.items():
        if word in text.lower():
            return f"{hour:02d}:00:00"
    return None


def extract_entities(text: str) -> dict:
    entities: dict = {}
    low = text.lower()

    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    if m:
        entities["email"] = m.group(0)

    m = re.search(r"(?:\+?\d[\d\s.\-()]{8,}\d)", text)
    if m and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", m.group(0)):
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) >= 8:
            entities["phone"] = digits

    m = re.search(
        r"(?:je\s+m'appelle|je\s+me\s+nomme|mon\s+nom\s+est|au\s+nom\s+de|nom\s*:|my\s+name\s+is)\s+([^,.;!?\n]{2,40})",
        text,
        re.IGNORECASE,
    )
    if m:
        entities["name"] = m.group(1).strip().strip(". ")

    date = extract_date(text)
    if date:
        entities["date"] = date
    time_ = extract_time(text)
    if time_:
        entities["time"] = time_

    m = re.search(r"(\d{2,6})\s*(€|eur|euros)", low)
    if m:
        entities["budget"] = f"{m.group(1)} €"

    urgency = None
    for word, level in {
        "urgent": "urgent", "urgemment": "urgent", "asap": "urgent",
        "dès que possible": "high", "des que possible": "high",
        "le plus vite": "high", "cette semaine": "normal",
    }.items():
        if word in low:
            urgency = level
    if urgency:
        entities["urgency"] = urgency

    m = re.search(r"(?:pour|concernant|about)\s+([^.,!?]{3,60})", text)
    if m and "need" not in entities:
        entities["need"] = m.group(1).strip()
    return entities


# Tie-break priority: urgent intents win over informational ones on equal scores.
_PRIORITY = [
    "HUMAN_TRANSFER", "COMPLAINT", "CANCELLATION", "RESCHEDULING", "APPOINTMENT",
    "QUOTE_REQUEST", "PURCHASE", "SUPPORT", "PRICE_REQUEST", "SERVICE_REQUEST",
    "INFORMATION", "GREETING",
]


def _keyword_hit(pattern: str, low: str) -> bool:
    """Word-boundary match for single words (avoids 'nul' ⊂ 'annuler'), substring for phrases."""
    pattern = pattern.strip()
    if not pattern:
        return False
    if " " in pattern:
        return pattern in low
    return re.search(r"(?<![\w])" + re.escape(pattern) + r"(?![\w])", low) is not None


def classify_keywords(text: str) -> tuple[str, float]:
    """Score intents by keyword hits; return (intent, confidence 0..1)."""
    low = f" {text.lower()} "
    scores: dict[str, float] = {}
    for intent, patterns in _KEYWORDS.items():
        hits = sum(1 for p in patterns if _keyword_hit(p, low))
        if hits:
            scores[intent] = hits
    if not scores:
        return "UNKNOWN", 0.3
    best = max(
        scores,
        key=lambda k: (scores[k], -_PRIORITY.index(k) if k in _PRIORITY else -99),
    )
    runner_up = sorted(scores.values(), reverse=True)
    confidence = 0.55 + 0.15 * min(runner_up[0], 3)
    if len(runner_up) > 1 and runner_up[1] == runner_up[0]:
        confidence = max(0.4, confidence - 0.2)  # ambiguous
    return best, round(min(confidence, 0.95), 2)


def is_greeting_only(text: str) -> bool:
    low = text.strip().lower().rstrip("!?. ")
    return low in {"bonjour", "bonsoir", "salut", "hello", "hi", "hey", "bjr", "coucou", "bonjour !"}

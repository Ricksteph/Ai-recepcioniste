"""MVP acceptance tests (cahier des charges §26).

Covers: tenant creation + isolation, KB ingestion + FAQ answers, intent
detection, lead creation, verified appointment booking (success AND failure),
human handoff, supervision, audit trail, sandbox-before-publish, widget gating.
"""
import asyncio

import pytest

from .conftest import API, add_faq, auth, register, wait_sources_ready

FAQ_CONTENT = """# FAQ Test

## Horaires
Le magasin est ouvert du lundi au vendredi de 9h à 18h, le samedi de 10h à 13h.

## Tarifs
Le prix de la séance standard est de 80 €. Le forfait annuel coûte 600 €.

## Adresse
Nous sommes au 5 avenue des Fleurs, 69000 Lyon, près de la place Bellecour.
"""


async def _setup_tenant(client, slug="alpha"):
    data = await register(client, slug, company=f"Entreprise {slug}")
    token = data["access_token"]
    await add_faq(client, token, FAQ_CONTENT)
    await wait_sources_ready(client, token)
    async with client as c:
        r = await c.put(f"{API}/tenants/me/receptionist", headers=auth(token), json={
            "name": "Léa", "tone": "amical",
            "greeting": "Bonjour, ici Léa !",
            "services": [{"name": "Séance standard", "duration_min": 30, "description": "", "price": "80 €"}],
        })
        assert r.status_code == 200, r.text
    return token


async def _chat(client, token, message, conversation_id=None, channel="sandbox"):
    endpoint = f"{API}/sandbox/test" if channel == "sandbox" else f"{API}/public/{channel}/chat"
    payload = {"message": message}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    headers = auth(token) if channel == "sandbox" else {}
    async with client as c:
        r = await c.post(endpoint, headers=headers, json=payload)
        assert r.status_code == 200, r.text
        return r.json()


# --------------------------------------------------------------------------- #
# AUTH + TENANT
# --------------------------------------------------------------------------- #
async def test_register_login_and_me(client):
    data = await register(client, "regco")
    token = data["access_token"]
    assert data["user"]["role"] == "admin"
    async with client as c:
        r = await c.post(f"{API}/auth/login", json={"email": data["user"]["email"], "password": "Password123!"})
        assert r.status_code == 200
        r = await c.get(f"{API}/auth/me", headers=auth(token))
        assert r.status_code == 200
        assert r.json()["email"] == data["user"]["email"]
        r = await c.post(f"{API}/auth/login", json={"email": data["user"]["email"], "password": "wrong-pass"})
        assert r.status_code == 401


# --------------------------------------------------------------------------- #
# KB + RAG
# --------------------------------------------------------------------------- #
async def test_kb_ingestion_and_faq_answer(client):
    token = await _setup_tenant(client, "kbco")
    resp = await _chat(client, token, "Bonjour, quel sont vos horaires d'ouverture ?")
    assert resp["intent"] in ("INFORMATION", "GREETING")
    # la réponse doit venir de la KB, pas d'une invention
    follow = await _chat(client, token, "Quels sont vos horaires exactement ?", resp["conversation_id"])
    assert "9h" in follow["reply"] or "9h00" in follow["reply"] or "lundi" in follow["reply"].lower()
    assert follow["sources"], "La réponse devrait être reliée à sa source"


async def test_kb_price_answer(client):
    token = await _setup_tenant(client, "priceco")
    resp = await _chat(client, token, "Combien coûte la séance standard ?")
    assert "80" in resp["reply"]


# --------------------------------------------------------------------------- #
# INTENTS
# --------------------------------------------------------------------------- #
async def test_intent_detection(client):
    token = await _setup_tenant(client, "intentco")
    cases = {
        "Je voudrais prendre rendez-vous": "APPOINTMENT",
        "Vous m'avez fait un prix beaucoup trop élevé, c'est une arnaque": "COMPLAINT",
        "Je veux annuler mon rendez-vous": "CANCELLATION",
        "Un humain s'il vous plaît": "HUMAN_TRANSFER",
        "Quel est le prix du forfait ?": "PRICE_REQUEST",
    }
    for text, expected in cases.items():
        resp = await _chat(client, token, text)
        assert resp["intent"] == expected, f"{text!r} → {resp['intent']} (attendu {expected})"


# --------------------------------------------------------------------------- #
# LEADS
# --------------------------------------------------------------------------- #
async def test_lead_creation(client):
    token = await _setup_tenant(client, "leadco")
    resp = await _chat(client, token, "Bonjour, je m'appelle Claire Martin, je souhaite un devis pour un forfait annuel, mon email est claire@example.com")
    assert resp["intent"] == "QUOTE_REQUEST"
    assert any(a["tool"] == "create_lead" and a["status"] == "success" for a in resp["actions"])
    async with client as c:
        r = await c.get(f"{API}/leads", headers=auth(token))
        leads = r.json()
    assert len(leads) == 1
    lead = leads[0]
    assert lead["email"] == "clairé@example.com" or lead["email"] == "claire@example.com"
    assert lead["score"] > 0 and lead["score_reasons"], "Le score doit être explicable"


# --------------------------------------------------------------------------- #
# APPOINTMENTS — real verification, success AND failure
# --------------------------------------------------------------------------- #
async def _configure_open_days(client, token, min_lead_hours=0):
    async with client as c:
        r = await c.get(f"{API}/rules", headers=auth(token))
        rules = r.json()
        for rule in rules:
            if rule["name"] == "Délai minimum de réservation":
                r2 = await c.put(f"{API}/rules/{rule['id']}", headers=auth(token), json={
                    **{k: rule[k] for k in ("name", "kind", "condition", "action", "description", "priority", "enabled")},
                    "params": {"min_lead_hours": min_lead_hours, "max_days_ahead": 90, "require_fields": ["date"]},
                })
                assert r2.status_code == 200, r2.text


async def test_appointment_flow_success(client):
    token = await _setup_tenant(client, "aptco")
    await _configure_open_days(client, token, min_lead_hours=0)
    from datetime import datetime, timedelta, timezone

    # pick the next open weekday (Mon-Fri) at least 2 days out
    day = datetime.now(timezone.utc) + timedelta(days=2)
    while day.weekday() > 4:
        day += timedelta(days=1)
    date_str = day.strftime("%Y-%m-%d")

    resp = await _chat(client, token, f"Je veux prendre rendez-vous le {date_str} pour une séance standard")
    slots = None
    for a in resp["actions"]:
        if a["tool"] == "check_availability" and a["status"] == "success":
            slots = a["result"]["slots"]
    assert slots, f"aucun créneau retourné : {resp}"
    chosen = slots[0]
    time_str = chosen["starts_at"][11:16]

    resp2 = await _chat(client, token, "À quel nom ?", resp["conversation_id"])
    resp3 = await _chat(client, token, "Au nom de Jean Durand", resp["conversation_id"])
    resp4 = await _chat(client, token, f"Parfait, je confirme à {time_str}", resp["conversation_id"])

    assert any(a["tool"] == "create_appointment" and a["status"] == "success" for a in resp4["actions"]), resp4
    assert "confirmé" in resp4["reply"] or "réservé" in resp4["reply"]
    async with client as c:
        r = await c.get(f"{API}/appointments", headers=auth(token))
        appts = [a for a in r.json() if a["status"] == "confirmed"]
    assert len(appts) == 1
    assert "Jean" in appts[0]["contact_name"] or "Durand" in appts[0]["title"]


async def test_appointment_outside_hours_is_not_booked(client):
    token = await _setup_tenant(client, "closedco")
    await _configure_open_days(client, token, min_lead_hours=0)
    from datetime import datetime, timedelta, timezone

    # next Sunday (closed day)
    day = datetime.now(timezone.utc) + timedelta(days=1)
    while day.weekday() != 6:
        day += timedelta(days=1)
    date_str = day.strftime("%Y-%m-%d")

    resp = await _chat(client, token, f"Je veux un rendez-vous dimanche {date_str} à 10h00, au nom de Paul")
    # no appointment may exist, and the agent must not claim success
    assert not any(a["tool"] == "create_appointment" and a["status"] == "success" for a in resp["actions"])
    async with client as c:
        r = await c.get(f"{API}/appointments", headers=auth(token))
        assert [a for a in r.json() if a["status"] == "confirmed"] == []


async def test_appointment_min_lead_time_enforced(client):
    token = await _setup_tenant(client, "leadtimeco")
    await _configure_open_days(client, token, min_lead_hours=48)
    from datetime import datetime, timedelta, timezone

    day = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    resp = await _chat(client, token, f"RDV le {day} à 10h00, au nom de Marc")
    creates = [a for a in resp["actions"] if a["tool"] == "create_appointment"]
    for a in creates:
        assert a["status"] != "success", "Un délai minimum de 48h doit bloquer la réservation du lendemain"


async def test_dashboard_availability_matches_chat(client):
    token = await _setup_tenant(client, "availco")
    await _configure_open_days(client, token, min_lead_hours=0)
    from datetime import datetime, timedelta, timezone

    day = datetime.now(timezone.utc) + timedelta(days=2)
    while day.weekday() > 4:
        day += timedelta(days=1)
    date_str = day.strftime("%Y-%m-%d")
    async with client as c:
        r = await c.get(f"{API}/appointments/availability?date={date_str}&service=Séance standard", headers=auth(token))
        assert r.status_code == 200
        slots = r.json()["slots"]
    assert slots and slots[0]["starts_at"].startswith(date_str)


# --------------------------------------------------------------------------- #
# HUMAN HANDOFF
# --------------------------------------------------------------------------- #
async def test_human_handoff_on_complaint(client):
    token = await _setup_tenant(client, "handco")
    resp = await _chat(client, token, "Je suis extrêmement mécontent, c'est une arnaque scandaleuse !")
    assert resp["handoff"] is True
    assert any(a["tool"] == "transfer_to_human" and a["status"] == "success" for a in resp["actions"])
    async with client as c:
        r = await c.get(f"{API}/handoffs?status=pending", headers=auth(token))
        handoffs = r.json()
    assert len(handoffs) == 1
    assert "arnaque" in handoffs[0]["summary"].lower() or "COMPLAINT" in handoffs[0]["summary"]
    r2 = None
    async with client as c:
        r2 = await c.post(f"{API}/handoffs/{handoffs[0]['id']}/claim", headers=auth(token))
    assert r2.status_code == 200


async def test_unknown_repeated_triggers_handoff(client):
    token = await _setup_tenant(client, "unkco")
    r1 = await _chat(client, token, "Zorglub magnifex trucmuche")
    r2 = await _chat(client, token, "Blimborgle wakfufu zinzin", r1["conversation_id"])
    assert r2["handoff"] is True or any(
        a["tool"] == "transfer_to_human" and a["status"] == "success" for a in r2["actions"]
    )


# --------------------------------------------------------------------------- #
# TENANT ISOLATION
# --------------------------------------------------------------------------- #
async def test_tenant_isolation(client):
    token_a = await _setup_tenant(client, "isoalpha")
    token_b = (await register(client, "isobeta", company="Bêta Corp"))["access_token"]

    # B's KB is empty and must not retrieve A's documents
    async with client as c:
        r = await c.post(f"{API}/knowledge/search", headers=auth(token_b), json={"query": "horaires tarifs 80 €"})
        results = r.json()["results"]
    assert results == [], f"Exfiltration possible : {results}"

    # B must not see A's conversations/leads
    conv_a = await _chat(client, token_a, "Bonjour, je m'appelle Alice, devis s'il vous plaît, alice@example.com")
    async with client as c:
        r = await c.get(f"{API}/conversations", headers=auth(token_b))
        assert r.json() == []
        r = await c.get(f"{API}/leads", headers=auth(token_b))
        assert r.json() == []
        r = await c.get(f"{API}/conversations/{conv_a['conversation_id']}/messages", headers=auth(token_b))
        assert r.status_code == 404

    # B asking the same question must not get A's FAQ answer
    resp_b = await _chat(client, token_b, "Quel est le prix de la séance standard ?")
    assert "80" not in resp_b["reply"]


# --------------------------------------------------------------------------- #
# SUPERVISION + AUDIT
# --------------------------------------------------------------------------- #
async def test_supervision_and_audit(client):
    token = await _setup_tenant(client, "supco")
    conv = await _chat(client, token, "Bonjour, quels sont vos tarifs ?")
    async with client as c:
        r = await c.get(f"{API}/conversations", headers=auth(token))
        assert len(r.json()) == 1
        r = await c.get(f"{API}/conversations/{conv['conversation_id']}/messages", headers=auth(token))
        messages = r.json()
        assert len(messages) >= 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        r = await c.get(f"{API}/conversations/{conv['conversation_id']}/actions", headers=auth(token))
        assert isinstance(r.json(), list)
        r = await c.get(f"{API}/audit", headers=auth(token))
        actions = [a["action"] for a in r.json()]
        assert "sandbox.test" in actions
        r = await c.get(f"{API}/analytics/overview", headers=auth(token))
        overview = r.json()
        assert overview["conversations"]["total"] >= 1
        assert "resolution_rate" in overview
        r = await c.get(f"{API}/analytics/intents", headers=auth(token))
        assert r.json()["intents"]


# --------------------------------------------------------------------------- #
# SANDBOX BEFORE PUBLISH + WIDGET GATING
# --------------------------------------------------------------------------- #
async def test_sandbox_before_publish_and_widget_gating(client):
    data = await register(client, "pubco")
    token = data["access_token"]
    slug = "pubco"

    # widget must 404 before publishing
    async with client as c:
        r = await c.get(f"{API}/public/{slug}/widget")
        assert r.status_code == 404

    # sandbox must work before publishing
    resp = await _chat(client, token, "Bonjour !")
    assert resp["reply"]

    # publish, then widget works
    async with client as c:
        r = await c.post(f"{API}/tenants/me/publish", headers=auth(token))
        assert r.status_code == 200
        r = await c.get(f"{API}/public/{slug}/widget")
        assert r.status_code == 200
        cfg = r.json()
        assert cfg["published"] is True and cfg["agent_name"]
        r = await c.post(f"{API}/public/{slug}/chat", json={"message": "Bonjour, j'ai une question", "visitor_id": "vis-1"})
        assert r.status_code == 200
        body = r.json()
        assert body["reply"]
        # history is scoped by visitor_id
        r = await c.get(f"{API}/public/{slug}/history?visitor_id=vis-1")
        assert len(r.json()) >= 2
        r = await c.get(f"{API}/public/{slug}/history?visitor_id=vis-other")
        assert r.json() == []
    # unpublish → widget closed again
    async with client as c:
        r = await c.post(f"{API}/tenants/me/unpublish", headers=auth(token))
        assert r.status_code == 200
        r = await c.get(f"{API}/public/{slug}/widget")
        assert r.status_code == 404


# --------------------------------------------------------------------------- #
# TOOL SAFETY — an action is never announced as done without a real result
# --------------------------------------------------------------------------- #
async def test_failed_action_is_not_announced_as_success(client):
    token = await _setup_tenant(client, "safeconv")
    resp = await _chat(client, token, "Je veux réserver le dimanche 10h00 à 10h00, au nom de Test")
    if any(a["tool"] == "create_appointment" for a in resp["actions"]):
        # si un create a été tenté, il a dû être refusé pour cause d'horaire
        creates = [a for a in resp["actions"] if a["tool"] == "create_appointment"]
        assert all(a["status"] != "success" for a in creates)
        assert "confirmé" not in resp["reply"].lower() or "pas" in resp["reply"].lower()


async def test_send_email_without_config_is_honest(client):
    token = await _setup_tenant(client, "emailco")
    resp = await _chat(client, token, "Je voudrais un devis, mon email est test@example.com, au nom de Rita")
    # aucune phrase ne doit annoncer un email envoyé avec succès (pas de SMTP configuré)
    assert "envoyé" not in resp["reply"].lower()


# --------------------------------------------------------------------------- #
# CANCELLATION
# --------------------------------------------------------------------------- #
async def test_cancellation_flow(client):
    token = await _setup_tenant(client, "cancelco")
    await _configure_open_days(client, token, min_lead_hours=0)
    from datetime import datetime, timedelta, timezone

    day = datetime.now(timezone.utc) + timedelta(days=2)
    while day.weekday() > 4:
        day += timedelta(days=1)
    date_str = day.strftime("%Y-%m-%d")
    resp = await _chat(client, token, f"Je veux prendre rendez-vous le {date_str}, au nom de Marc")
    slots = None
    for a in resp["actions"]:
        if a["tool"] == "check_availability" and a["status"] == "success":
            slots = a["result"]["slots"]
    assert slots
    time_str = slots[0]["starts_at"][11:16]
    resp2 = await _chat(client, token, f"Je confirme à {time_str}", resp["conversation_id"])
    assert any(a["tool"] == "create_appointment" and a["status"] == "success" for a in resp2["actions"])

    resp3 = await _chat(client, token, f"Je dois annuler mon rendez-vous du {date_str}", resp["conversation_id"])
    assert any(a["tool"] == "cancel_appointment" and a["status"] == "success" for a in resp3["actions"]), resp3
    assert "annulé" in resp3["reply"].lower()


# --------------------------------------------------------------------------- #
# ROLES
# --------------------------------------------------------------------------- #
async def test_rbac_agent_cannot_configure(client):
    data = await register(client, "rbacco")
    admin_token = data["access_token"]
    async with client as c:
        r = await c.post(f"{API}/tenants/me/users", headers=auth(admin_token), json={
            "email": "agent@rbacco.example.com", "password": "Password123!", "role": "agent", "full_name": "Agent",
        })
        assert r.status_code == 201
    async with client as c:
        r = await c.post(f"{API}/auth/login", json={"email": "agent@rbacco.example.com", "password": "Password123!"})
        agent_token = r.json()["access_token"]
        # agent can supervise
        r = await c.get(f"{API}/conversations", headers=auth(agent_token))
        assert r.status_code == 200
        # agent cannot change the receptionist identity
        r = await c.put(f"{API}/tenants/me/receptionist", headers=auth(agent_token), json={"name": "Hack"})
        assert r.status_code == 403
        # agent cannot add knowledge sources
        r = await c.post(f"{API}/knowledge/sources", headers=auth(agent_token), json={
            "type": "manual", "name": "x", "content": "y",
        })
        assert r.status_code == 403

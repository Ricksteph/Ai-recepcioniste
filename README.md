# AI Receptionist — SaaS de réceptionniste virtuel autonome

Plateforme SaaS multi-tenant conforme au cahier des charges V1.0 : un réceptionniste IA
configurable par entreprise, qui répond à partir de **ses** connaissances, applique **ses**
règles métier, exécute de **vraies** actions (rendez-vous, prospects, transferts humains)
et en laisse une trace vérifiable.

Principe produit : **Configurer → Alimenter → Tester → Publier → Superviser → Améliorer.**

---

## Démarrage rapide (Docker)

```bash
cp .env.example .env          # renseigner JWT_SECRET au minimum
docker compose up --build
docker compose exec backend python seed.py   # données de démo
```

- Dashboard : http://localhost:3000 — `admin@clinique-dupont.fr` / `Demo!2026`
- Chat public : http://localhost:3000/chat/clinique-dupont
- API : http://localhost:8000/docs (OpenAPI)

## Démarrage local (sans Docker)

**Backend** (Python 3.12+, Postgres non requis grâce au repli SQLite) :

```bash
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend && ../.venv/bin/uvicorn app.main:app --port 8000
cd backend && ../.venv/bin/python seed.py      # données de démo
cd backend && ../.venv/bin/python -m pytest    # 18 tests E2E du MVP
```

**Frontend** (Node 20+) :

```bash
cd frontend && npm install && npm run dev      # http://localhost:3000
```

Sans clé LLM configurée, un moteur déterministe local prend le relais : l'agent reste
pleinement fonctionnel (FAQ, réservation, prospects, transfert) et 100 % testable hors-ligne.

---

## Architecture

```
Canaux (Web Chat / Sandbox / widget embarquable)
   → API Gateway (FastAPI, Next.js proxy /api)
      → Auth + isolation tenant (JWT, rôles super_admin | admin | agent)
         → Conversation Engine (Intent → Context → Retrieval → Rules → Decision → Tool → Response)
            → Memory (session / client / entreprise, isolée par tenant)
            → Knowledge Base + RAG (ingestion → chunking → embeddings → retrieval)
            → Rules Engine (évalué indépendamment du LLM)
            → AI Orchestrator (OpenAI | Anthropic | OpenRouter | NVIDIA | Ollama | policy locale)
            → Tool Engine (exécution réelle, statut success | failed | pending vérifié)
               → Intégrations (calendrier interne, email, WhatsApp à venir)
                  → Observabilité (logs structurés, analytics, journal d'audit)
```

| Brique | Détail |
|---|---|
| Frontend | Next.js 14 + TypeScript + Tailwind, 16 pages (dashboard 11 vues, onboarding guidé, chat public) |
| Backend | FastAPI async, SQLAlchemy async, PyJWT, ingestion PDF/DOCX/XLSX/CSV/TXT/MD/web |
| Données | PostgreSQL + pgvector en production ; repli SQLite (cosinus en process) pour le dev |
| LLM | Abstraction multi-fournisseurs — changer de modèle ne change pas le métier |
| Repli LLM | Quota atteint (429) ou erreur → bascule automatique sur `LLM_FALLBACK_CHAIN`, puis policy locale |
| Embeddings | OpenAI/Ollama si clé fournie, sinon embedding local déterministe (hors-ligne) |

### Bascule automatique de modèle (quota LLM)

Chaque fournisseur gratuit a un quota (rate-limit). Le moteur ne tombe jamais en panne pour
cela : il suit une chaîne de repli ordonnée — modèle courant, puis chaque entrée de
`LLM_FALLBACK_CHAIN`, puis la policy locale.

```bash
LLM_PROVIDER=auto
# ordre essayé quand le modèle courant renvoie 429 / échoue :
LLM_FALLBACK_CHAIN=nvidia:*,openrouter:*
LLM_COOLDOWN_SECONDS=120      # après un 429, le modèle est mis en pause…
LLM_COOLDOWN_MAX_SECONDS=3600 # …qui double à chaque 429, plafonnée à 1 h
```

Comportement :

- **`provider:*` = tous les modèles du catalogue**, rechargés à chaque démarrage :
  `nvidia:*` retient 51 modèles chat sur 85 (embeddings, vision, garde-fous,
  détecteurs et récompenses filtrés — ils échoueraient sur `/chat/completions`) et
  `openrouter:*` garde **uniquement les 15 modèles `:free`** — la gratuité est
  garantie, aucun modèle payant ne peut entrer dans la chaîne. Avec les deux clés :
  **66 modèles** en réserve, triés modèles fiables en tête.
- **Bascule immédiate** : le 429 du modèle courant déclenche aussitôt le modèle suivant ;
  la réponse est servie sans interruption du visiteur.
- **Cooldown escalier** : le modèle en quota est écarté (120 s, puis 240 s, 480 s…) au lieu
  de re-recevoir un 429 à chaque message ; un succès remet le compteur à zéro.
- **Dernier recours** : toute la chaîne en quota → le Conversation Engine répond via la
  policy locale déterministe (jamais d'erreur visible côté visiteur).
- **100 % gratuit** : `NVIDIA_API_KEY` (quota par modèle, ~40 req/min observés) et
  `OPENROUTER_API_KEY` (20 req/min et 50 req/jour partagés entre modèles `:free`)
  coûtent 0 $ — voir `.env.example`.
- **Économie de requêtes** : un modèle qui refuse `response_format` est mémorisé et
  n'est plus interrogé en JSON mode ; le catalogue est appelé une seule fois par
  démarrage (filtre `openrouter:*` : un modèle payant ne peut jamais entrer).

### Sécurité (§24)

- Isolation stricte des tenants : chaque requête, chaque retrieval et chaque outil filtre par `tenant_id` — vérifié par test (`test_tenant_isolation`).
- RBAC : l'agent supervise mais ne configure pas ; seul l'admin configure ; super admin globalement.
- Aucune action annoncée sans résultat réel : le Tool Engine valide les paramètres, exécute, renvoie un statut explicite ; la réponse n'est formulée qu'à partir de ce statut (test `test_failed_action_is_not_announced_as_success`).
- Journal d'audit de tous les événements critiques, mots de passe PBKDF2-SHA256, secrets côté serveur, limitation de débit sur le canal public.

### Critères d'acceptation MVP (§26)

Les 18 tests de `backend/tests/test_mvp.py` couvrent un par un les critères : création
d'entreprise et de réceptionniste, import document + réponse FAQ sourcée, isolation de deux
tenants, détection d'intention, création de prospect avec score explicable, vérification puis
création de rendez-vous réel (et refus hors horaires / délai minimum), refus de confirmer une
action échouée, transfert humain avec résumé, supervision, audit, test sandbox avant publication.

---

## Parcours de démonstration

1. **Onboarding** (`/register` puis `/onboarding`) : entreprise, horaires, identité du
   réceptionniste, prestations et durées.
2. **Knowledge Base** : importez un PDF/DOCX ou collez une FAQ — extraction, nettoyage,
   segmentation et indexation automatiques ; testez la recherche sur place.
3. **Règles métier** : les 6 règles par défaut (transfert plainte/explicite, délai minimum,
   question inconnue, limite d'actions, jour fermé) sont éditables et simulables.
4. **Sandbox** : testez chaque scénario avant publication ; chaque action exécutée apparaît
   avec son statut vérifié.
5. **Publication** : un clic depuis la vue d'ensemble ; copiez le code
   `<script src="…/widget.js" data-slug="…" async></script>` dans votre site, ou ouvrez
   `/chat/<slug>`.
6. **Supervision** : conversations, prospects, rendez-vous, transferts humains (avec résumé
   généré : motif, intention, dernier message, identité connue), analytics, audit.

## Hors périmètre V1 (roadmap §27)

WhatsApp (P9), voix (P10), facturation (P11), CRM complet, téléphonie. L'architecture est
prête : les canaux et le Tool Engine sont des points d'extension.

## Structure du dépôt

```
backend/    FastAPI : app/{routers,engine,llm,rag}, tests/, seed.py, Dockerfile
frontend/   Next.js : app/{login,register,onboarding,dashboard/*,chat/[slug]}, lib/api.ts
docker-compose.yml   Postgres+pgvector, Redis, backend, frontend
.env.example         variables d'environnement documentées
```

"""Chaîne de repli LLM : quota atteint (429) → bascule automatique (§20)."""
import pytest

import app.llm.providers as prov
from app.config import settings
from app.llm.providers import (
    ChatProvider,
    FallbackChatProvider,
    ProviderError,
    RateLimitError,
    resolve_chat_provider,
)


@pytest.fixture(autouse=True)
def _clean_provider_env(monkeypatch):
    """Isole les tests des clés/configs réelles éventuellement présentes dans backend/.env."""
    for attr, value in {
        "llm_provider": "auto",
        "llm_fallback_chain": "",
        "openai_api_key": "",
        "anthropic_api_key": "",
        "openrouter_api_key": "",
        "nvidia_api_key": "",
        "ollama_host": "",
        "openai_model": "gpt-4o-mini",
        "openrouter_model": "google/gemma-4-31b-it:free",
        "nvidia_model": "mistralai/mistral-large-2-instruct",
        "llm_cooldown_seconds": 120.0,
        "llm_cooldown_max_seconds": 3600.0,
    }.items():
        monkeypatch.setattr(settings, attr, value)
    # aucun appel réseau réel en test : catalogue vide par défaut
    monkeypatch.setattr(prov, "_fetch_model_catalog", lambda base_url, api_key="": [])


class Stub(ChatProvider):
    """Provider contrôlé : échoue avec l'exception choisie, sinon renvoie `reply`."""

    def __init__(
        self,
        name: str,
        model: str,
        fail: type[Exception] | None = None,
        reply: str = "réponse-ok",
        msg: str = "quota dépassé (429)",
    ):
        self.name = name
        self.model = model
        self.fail = fail
        self.reply = reply
        self.msg = msg
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        if self.fail is not None:
            raise self.fail(f"{self.name}: {self.msg}")
        return self.reply


def _chain(monkeypatch, cooldown: float = 120.0, max_cooldown: float = 3600.0):
    monkeypatch.setattr(settings, "llm_cooldown_seconds", cooldown)
    monkeypatch.setattr(settings, "llm_cooldown_max_seconds", max_cooldown)
    primary = Stub("primary", "m1", fail=RateLimitError)
    backup = Stub("backup", "m2")
    chain = FallbackChatProvider([primary, backup])
    clock = {"now": 1000.0}
    chain._now = lambda: clock["now"]
    return chain, primary, backup, clock


async def test_quota_atteint_bascule_immediate(monkeypatch):
    """Le 429 du modèle principal déclenche aussitôt le modèle suivant."""
    chain, primary, backup, _ = _chain(monkeypatch)
    out = await chain.chat([{"role": "user", "content": "bonjour"}])
    assert out == "réponse-ok"
    assert primary.calls == 1
    assert backup.calls == 1


async def test_modele_en_quota_evite_pendant_le_cooldown(monkeypatch):
    """Pendant le cooldown, on va directement au repli (zéro requête perdue)."""
    chain, primary, backup, clock = _chain(monkeypatch)
    await chain.chat([])
    await chain.chat([])
    assert primary.calls == 1
    assert backup.calls == 2
    clock["now"] += 121  # cooldown expiré → le modèle principal est retenté
    await chain.chat([])
    assert primary.calls == 2
    assert backup.calls == 3


async def test_escalade_exponentielle_du_cooldown(monkeypatch):
    """Chaque 429 consécutif double le délai avant nouvelle tentative."""
    chain, primary, _, clock = _chain(monkeypatch, cooldown=120.0)
    await chain.chat([])
    key = "primary:m1"
    assert chain._cooldown_until[key] == pytest.approx(1000.0 + 120.0)
    clock["now"] += 121
    await chain.chat([])  # 2e 429 → 240 s
    assert chain._cooldown_until[key] == pytest.approx(1121.0 + 240.0)
    clock["now"] += 241
    await chain.chat([])  # 3e 429 → 480 s
    assert chain._cooldown_until[key] == pytest.approx(1362.0 + 480.0)
    assert chain._cooldown_until[key] - clock["now"] <= settings.llm_cooldown_max_seconds


async def test_cooldown_plafonne(monkeypatch):
    """L'escalade ne dépasse jamais llm_cooldown_max_seconds."""
    chain, primary, _, clock = _chain(monkeypatch, cooldown=1000.0, max_cooldown=1500.0)
    await chain.chat([])
    clock["now"] += 1001
    await chain.chat([])  # streak 2 → 2000 s mais plafonné à 1500 s
    key = "primary:m1"
    assert chain._cooldown_until[key] == pytest.approx(2001.0 + 1500.0)


async def test_succes_remise_a_zero_du_streak(monkeypatch):
    """Un succès remet à zéro le compteur de quota du modèle."""
    chain, primary, _, clock = _chain(monkeypatch)
    await chain.chat([])  # 429 → streak 1
    primary.fail = None  # le quota est rétabli côté fournisseur
    clock["now"] += 121
    out = await chain.chat([])
    assert out == "réponse-ok"
    assert primary.calls == 2
    assert "primary:m1" not in chain._cooldown_until
    assert "primary:m1" not in chain._rate_streak


async def test_erreur_transitoire_bascule_aussi(monkeypatch):
    """Toute erreur du modèle (pas seulement le 429) tente le repli."""
    monkeypatch.setattr(settings, "llm_cooldown_seconds", 120.0)
    primary = Stub("primary", "m1", fail=ProviderError, msg="connexion refusée")
    backup = Stub("backup", "m2")
    chain = FallbackChatProvider([primary, backup])
    clock = {"now": 1000.0}
    chain._now = lambda: clock["now"]
    out = await chain.chat([])
    assert out == "réponse-ok"
    assert backup.calls == 1
    # cooldown plat court (30 s max) pour une erreur non-quota
    assert chain._cooldown_until["primary:m1"] == pytest.approx(1000.0 + 30.0)


async def test_chaine_entierement_en_cooldown_leve_erreur(monkeypatch):
    """Tous les modèles en quota → ProviderError (le moteur tombe en policy)."""
    chain, primary, backup, _ = _chain(monkeypatch)
    primary.fail = RateLimitError
    backup.fail = RateLimitError
    with pytest.raises(RateLimitError):
        await chain.chat([])
    with pytest.raises(ProviderError):  # 2e appel : tout est en cooldown
        await chain.chat([])
    assert primary.calls == 1
    assert backup.calls == 1


async def test_bascule_sur_plusieurs_niveaux(monkeypatch):
    """3 modèles : si les 2 premiers sont en quota, le 3e répond."""
    first = Stub("first", "m1", fail=RateLimitError)
    second = Stub("second", "m2", fail=RateLimitError)
    third = Stub("third", "m3")
    chain = FallbackChatProvider([first, second, third])
    out = await chain.chat([])
    assert out == "réponse-ok"
    assert third.calls == 1


# --------------------------------------------------------------------------- #
# Construction de la chaîne depuis la configuration
# --------------------------------------------------------------------------- #
def test_resolve_sans_repli_renvoie_le_provider_simple(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "auto")
    monkeypatch.setattr(settings, "openrouter_api_key", "or-key")
    monkeypatch.setattr(settings, "openrouter_model", "openai/gpt-4o-mini")
    monkeypatch.setattr(settings, "llm_fallback_chain", "")
    provider = resolve_chat_provider()
    assert not isinstance(provider, FallbackChatProvider)
    assert provider.name == "openrouter"


def test_resolve_construit_la_chaine_configurée(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "auto")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key", "or-key")
    monkeypatch.setattr(settings, "openrouter_model", "openai/gpt-4o-mini")
    monkeypatch.setattr(settings, "nvidia_api_key", "nv-key")
    monkeypatch.setattr(
        settings, "llm_fallback_chain",
        "nvidia:meta/llama-3.3-70b-instruct, openrouter:meta-llama/llama-3.3-70b-instruct:free",
    )
    provider = resolve_chat_provider()
    assert isinstance(provider, FallbackChatProvider)
    labels = [f"{p.name}:{p.model}" for p in provider.candidates]
    assert labels == [
        "nvidia:mistralai/mistral-large-2-instruct",          # courant (auto : nvidia avant openrouter)
        "nvidia:meta/llama-3.3-70b-instruct",                 # repli 1
        "openrouter:meta-llama/llama-3.3-70b-instruct:free",  # repli 2
    ]


def test_resolve_evite_les_doublons(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "auto")
    monkeypatch.setattr(settings, "openrouter_api_key", "or-key")
    monkeypatch.setattr(settings, "openrouter_model", "openai/gpt-4o-mini")
    # même provider:m modèle que le courant → ignoré
    monkeypatch.setattr(settings, "llm_fallback_chain", "openrouter:openai/gpt-4o-mini")
    provider = resolve_chat_provider()
    assert not isinstance(provider, FallbackChatProvider)
    assert provider.name == "openrouter"


def test_resolve_ignore_les_replis_non_configures(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "auto")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key", "or-key")
    monkeypatch.setattr(settings, "nvidia_api_key", "")
    # nvidia sans clé ignoré → chaîne réduite au provider courant
    monkeypatch.setattr(settings, "llm_fallback_chain", "nvidia:meta/llama-3.3-70b-instruct")
    provider = resolve_chat_provider()
    assert not isinstance(provider, FallbackChatProvider)
    assert provider.name == "openrouter"


def test_resolve_mock_ignore_la_chaine(monkeypatch):
    """LLM_PROVIDER=mock reste un coupe-circuit total, chaîne ou non."""
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "openrouter_api_key", "or-key")
    monkeypatch.setattr(settings, "llm_fallback_chain", "openrouter:meta-llama/llama-3.3-70b-instruct:free")
    assert resolve_chat_provider() is None


# --------------------------------------------------------------------------- #
# Expansion provider:* (tous les modèles du catalogue du fournisseur)
# --------------------------------------------------------------------------- #
def _stub_catalog(ids):
    return lambda base_url, api_key="": list(ids)


def test_expansion_filtre_les_modeles_non_chat(monkeypatch):
    """Embeddings / vision / récompenses sont exclus — ils échoueraient en chat."""
    monkeypatch.setattr(settings, "nvidia_api_key", "nv-key")
    monkeypatch.setattr(prov, "_fetch_model_catalog", _stub_catalog([
        "mistralai/mistral-large-2-instruct",     # chat ✓
        "nvidia/embed-qa-4",                        # embedding ✗
        "meta/llama-3.2-90b-vision-instruct",       # vision ✗
        "nvidia/nemotron-4-340b-reward",            # reward ✗
        "meta/llama-guard-4-12b",                   # garde-fou ✗
        "z-ai/glm-5.3",                             # chat ✓
    ]))
    out = prov._expand_wildcard("nvidia")
    assert out == ["mistralai/mistral-large-2-instruct", "z-ai/glm-5.3"]


def test_expansion_openrouter_uniquement_gratuits(monkeypatch):
    """openrouter:* ne garde que les modèles `:free` — gratuité garantie."""
    monkeypatch.setattr(settings, "openrouter_api_key", "or-key")
    monkeypatch.setattr(prov, "_fetch_model_catalog", _stub_catalog([
        "openai/gpt-4o",                       # payant ✗
        "meta/llama-3.3-70b-instruct:free",     # gratuit ✓
        "deepseek/deepseek-v3:free",            # gratuit ✓
    ]))
    out = prov._expand_wildcard("openrouter")
    assert out == ["deepseek/deepseek-v3:free", "meta/llama-3.3-70b-instruct:free"]


def test_expansion_echec_catalogue_modele_par_defaut(monkeypatch):
    """Catalogue inaccessible → modèle par défaut du fournisseur (chaîne intacte)."""
    monkeypatch.setattr(settings, "nvidia_api_key", "nv-key")
    monkeypatch.setattr(settings, "nvidia_model", "mistralai/mistral-large-2-instruct")
    monkeypatch.setattr(prov, "_fetch_model_catalog", _stub_catalog([]))
    assert prov._expand_wildcard("nvidia") == ["mistralai/mistral-large-2-instruct"]


def test_resolve_wildcard_construit_la_chaine_complete(monkeypatch):
    """nvidia:*,openrouter:* → tous les modèles chat/gatuits, sans doublon du courant."""
    monkeypatch.setattr(settings, "llm_provider", "auto")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "nvidia_api_key", "nv-key")
    monkeypatch.setattr(settings, "nvidia_model", "mistralai/mistral-large-2-instruct")
    monkeypatch.setattr(settings, "openrouter_api_key", "or-key")
    monkeypatch.setattr(settings, "llm_fallback_chain", "nvidia:*,openrouter:*")
    monkeypatch.setattr(prov, "_fetch_model_catalog", lambda b, k="": (
        ["mistralai/mistral-large-2-instruct", "z-ai/glm-5.3", "nvidia/embed-qa-1b"]
        if "nvidia" in b else
        ["openai/gpt-4o", "google/gemma-4-31b-it:free"]
    ))
    provider = resolve_chat_provider()
    assert isinstance(provider, FallbackChatProvider)
    labels = [f"{p.name}:{p.model}" for p in provider.candidates]
    assert labels == [
        "nvidia:mistralai/mistral-large-2-instruct",   # modèle courant (auto : nvidia avant openrouter)
        "nvidia:z-ai/glm-5.3",                         # expansion nvidia:* (embed filtré, doublon courant évité)
        "openrouter:google/gemma-4-31b-it:free",       # expansion openrouter:* (payant filtré)
    ]

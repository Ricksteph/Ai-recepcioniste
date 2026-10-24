"""Provider-agnostic LLM + embeddings clients (cahier des charges §20).

The orchestrator never depends on a specific vendor: switching models must not
require business-code changes. When no provider is configured, `chat()` returns
None and the Conversation Engine falls back to the deterministic policy
(engine/policy.py) so the product remains fully testable offline.
"""
import asyncio
import hashlib
import logging
import math
import re
import time

import httpx

from ..config import settings

logger = logging.getLogger("ai_receptionist.llm")


class ProviderError(Exception):
    pass


class RateLimitError(ProviderError):
    """Quota / rate-limit atteint (HTTP 429) — déclenche le cooldown du modèle."""


# --------------------------------------------------------------------------- #
# Chat providers
# --------------------------------------------------------------------------- #
class ChatProvider:
    name = "base"

    async def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.2,
        max_tokens: int = 700,
        json_mode: bool = False,
    ) -> str:
        raise NotImplementedError


class OpenAICompatProvider(ChatProvider):
    """Works for OpenAI, OpenRouter and Ollama (/v1 compatibility mode)."""

    def __init__(self, name: str, base_url: str, api_key: str, model: str):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._json_mode_ok = True  # désactivé après un 400 sur response_format

    async def chat(self, messages, *, temperature=0.2, max_tokens=700, json_mode=False):
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode and self._json_mode_ok:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = f"{self.base_url}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 429:
                    raise RateLimitError(f"{self.name}: quota dépassé (429)")
                if resp.status_code == 400 and "response_format" in payload:
                    # certains modèles n'acceptent pas response_format :
                    # on retente une fois sans, puis on mémorise pour ce modèle
                    payload.pop("response_format", None)
                    resp = await client.post(url, json=payload, headers=headers)
                    if resp.status_code == 429:
                        raise RateLimitError(f"{self.name}: quota dépassé (429)")
                    if resp.status_code < 400:
                        self._json_mode_ok = False
                        logger.info(
                            "Modèle '%s:%s' sans JSON mode — response_format mémorisé",
                            self.name, self.model,
                        )
                resp.raise_for_status()
                data = resp.json()
        except RateLimitError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"{self.name}: {exc}") from exc
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"{self.name}: réponse malformée") from exc


class AnthropicProvider(ChatProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def chat(self, messages, *, temperature=0.2, max_tokens=700, json_mode=False):
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        convo = [m for m in messages if m["role"] != "system"]
        payload = {
            "model": self.model,
            "system": system or "Tu es un réceptionniste virtuel.",
            "messages": convo,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages", json=payload, headers=headers
                )
                if resp.status_code == 429:
                    raise RateLimitError("anthropic: quota dépassé (429)")
                resp.raise_for_status()
                data = resp.json()
        except RateLimitError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"anthropic: {exc}") from exc
        try:
            return "".join(b.get("text", "") for b in data["content"])
        except (KeyError, TypeError) as exc:
            raise ProviderError("anthropic: réponse malformée") from exc


def _make_provider(name: str, model: str | None = None) -> ChatProvider | None:
    """Build a provider instance from settings; None when not usable."""
    if name == "openai" and settings.openai_api_key:
        return OpenAICompatProvider(
            "openai", settings.openai_base_url, settings.openai_api_key,
            model or settings.openai_model,
        )
    if name == "anthropic" and settings.anthropic_api_key:
        return AnthropicProvider(settings.anthropic_api_key, model or settings.anthropic_model)
    if name == "openrouter" and settings.openrouter_api_key:
        return OpenAICompatProvider(
            "openrouter", settings.openrouter_base_url, settings.openrouter_api_key,
            model or settings.openrouter_model,
        )
    if name == "nvidia" and settings.nvidia_api_key:
        return OpenAICompatProvider(
            "nvidia", settings.nvidia_base_url, settings.nvidia_api_key,
            model or settings.nvidia_model,
        )
    if name == "ollama" and settings.ollama_host and settings.environment != "test":
        return OpenAICompatProvider(
            "ollama", f"{settings.ollama_host}/v1", "", model or settings.ollama_model
        )
    return None


def _label(provider: ChatProvider) -> str:
    model = getattr(provider, "model", "")
    return f"{provider.name}:{model}" if model else provider.name


def _looks_rate_limited(message: str) -> bool:
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in ("429", "rate limit", "rate_limit", "too many requests", "quota")
    )


# --------------------------------------------------------------------------- #
# Expansion « provider:* » — tous les modèles utilisables du fournisseur
# --------------------------------------------------------------------------- #
# Modèles non-conversations présents dans les catalogues (embeddings, vision,
# garde-fous, détecteurs, récompenses…) : ils échoueraient ou répondraient hors
# sujet sur /chat/completions → exclus de l'expansion.
_NON_CHAT_MARKERS = (
    "embed", "rerank", "reward", "parse", "vision", "vl", "guard", "safety",
    "detector", "clip", "diffusion", "video", "image", "caption", "deplot",
    "fuyu", "kosmos", "neva", "vila", "muse", "translate", "retriev",
    "calibration", "cosmos", "audio", "speech", "tts", "asr", "stt",
)
# Ordre de préférence dans l'expansion : modèles fiables et généralistes en
# tête, le reste trié par identifiant.
_PREFERRED_PREFIXES = (
    "mistralai/mistral-large-2",
    "z-ai/glm-5",
    "moonshotai/kimi-k2",
    "minimaxai/minimax",
    "deepseek-ai/deepseek-v4",
    "nvidia/nemotron-4-340b",
    "nvidia/nemotron-3-super",
    "nvidia/nemotron-3-ultra",
    "nvidia/nemotron-3.5-lightning",
    "openai/gpt-oss",
    "google/gemma-4",
    "google/gemma-3",
    "meta/llama-3.1-nemotron-70b",
    "thinkingmachines/inkling",
    "liquid/lfm",
)


def _is_chat_model(model_id: str) -> bool:
    low = model_id.lower()
    return not any(marker in low for marker in _NON_CHAT_MARKERS)


def _catalog_rank(model_id: str) -> tuple[int, str]:
    low = model_id.lower()
    for rank, prefix in enumerate(_PREFERRED_PREFIXES):
        if low.startswith(prefix):
            return (rank, low)
    return (len(_PREFERRED_PREFIXES), low)


def _fetch_model_catalog(base_url: str, api_key: str = "") -> list[str]:
    """GET {base_url}/models → identifiants du catalogue.

    Public chez OpenRouter et NVIDIA ; la clé est envoyée si présente (jamais
    journalisée). En cas d'échec réseau : liste vide → modèle par défaut.
    """
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        with httpx.Client(timeout=15, headers=headers) as client:
            resp = client.get(f"{base_url.rstrip('/')}/models")
            resp.raise_for_status()
            data = resp.json().get("data") or []
    except (httpx.HTTPError, ValueError, KeyError, AttributeError) as exc:
        logger.warning(
            "Catalogue de modèles inaccessible (%s) — repli sur le modèle par défaut", exc
        )
        return []
    return [str(m.get("id", "")) for m in data if isinstance(m, dict) and m.get("id")]


def _provider_conn(name: str) -> tuple[str, str, str] | None:
    """(base_url, api_key, modèle_par_défaut) du fournisseur, ou None si absent."""
    if name == "openai" and settings.openai_api_key:
        return settings.openai_base_url, settings.openai_api_key, settings.openai_model
    if name == "anthropic" and settings.anthropic_api_key:
        return "https://api.anthropic.com/v1", settings.anthropic_api_key, settings.anthropic_model
    if name == "openrouter" and settings.openrouter_api_key:
        return settings.openrouter_base_url, settings.openrouter_api_key, settings.openrouter_model
    if name == "nvidia" and settings.nvidia_api_key:
        return settings.nvidia_base_url, settings.nvidia_api_key, settings.nvidia_model
    if name == "ollama" and settings.ollama_host and settings.environment != "test":
        return f"{settings.ollama_host}/v1", "", settings.ollama_model
    return None


def _expand_wildcard(name: str) -> list[str]:
    """`provider:*` → tous les modèles utilisables du fournisseur.

    - openrouter:* → uniquement les modèles `:free` (gratuité garantie).
    - nvidia:* → tout le catalogue chat (offre gratuite à la requête).
    - Modèles non-conversations exclus ; triés modèles préférés en tête.
    En cas d'échec du catalogue : modèle par défaut du fournisseur.
    """
    conn = _provider_conn(name)
    if conn is None:
        return []
    base_url, api_key, default_model = conn
    ids = [i for i in _fetch_model_catalog(base_url, api_key) if _is_chat_model(i)]
    if name == "openrouter":
        ids = [i for i in ids if i.endswith(":free")]  # gratuité garantie
    ids.sort(key=_catalog_rank)
    if not ids:
        logger.warning("Catalogue '%s' vide ou inaccessible — modèle par défaut utilisé", name)
        return [default_model] if default_model else []
    logger.info("Expansion '%s:*' → %d modèles", name, len(ids))
    return ids


class FallbackChatProvider(ChatProvider):
    """Modèle courant + chaîne de repli, avec bascule automatique (§20).

    Le premier modèle disponible répond. En cas de quota dépassé (HTTP 429),
    le modèle est mis en cooldown — escalier exponentiel de
    `llm_cooldown_seconds` jusqu'à `llm_cooldown_max_seconds` sur des 429
    consécutifs — et le modèle suivant de la chaîne est essayé aussitôt.
    Les autres erreurs reçoivent un court cooldown plat. Quand toute la chaîne
    est en cooldown, ProviderError remonte et le Conversation Engine bascule
    sur la policy locale déterministe.
    """

    def __init__(self, candidates: list[ChatProvider]):
        self.candidates = candidates
        self.name = "chain[" + " → ".join(_label(p) for p in candidates) + "]"
        self._cooldown_until: dict[str, float] = {}
        self._rate_streak: dict[str, int] = {}
        self._now = time.monotonic  # surchargeable en test

    def _cool(self, key: str, *, rate_limited: bool) -> None:
        if rate_limited:
            streak = self._rate_streak.get(key, 0) + 1
            self._rate_streak[key] = streak
            delay = min(
                settings.llm_cooldown_seconds * (2 ** (streak - 1)),
                settings.llm_cooldown_max_seconds,
            )
        else:
            delay = min(30.0, settings.llm_cooldown_seconds)
        self._cooldown_until[key] = self._now() + delay
        logger.warning("LLM '%s' en cooldown %ss (quota dépassé=%s)", key, int(delay), rate_limited)

    async def chat(self, messages, *, temperature=0.2, max_tokens=700, json_mode=False):
        now = self._now()
        available = [
            p for p in self.candidates
            if self._cooldown_until.get(_label(p), 0.0) <= now
        ]
        if not available:
            raise ProviderError("tous les modèles de la chaîne sont en cooldown — policy locale")
        last_error: ProviderError | None = None
        for provider in available:
            key = _label(provider)
            try:
                out = await provider.chat(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
            except RateLimitError as exc:
                logger.warning("Quota atteint sur '%s' — bascule sur le modèle suivant", key)
                self._cool(key, rate_limited=True)
                last_error = exc
                continue
            except ProviderError as exc:
                rate_limited = _looks_rate_limited(str(exc))
                logger.warning(
                    "Modèle '%s' en échec (%s) — %s", key, exc,
                    "quota atteint, bascule" if rate_limited else "essai du modèle suivant",
                )
                self._cool(key, rate_limited=rate_limited)
                last_error = exc
                continue
            self._cooldown_until.pop(key, None)
            self._rate_streak.pop(key, None)
            if provider is not self.candidates[0]:
                logger.info("Réponse servie par '%s' (modèle principal indisponible)", key)
            return out
        raise last_error or ProviderError("chaîne LLM épuisée")


def resolve_chat_provider() -> ChatProvider | None:
    """Pick the configured provider.

    `auto` order: openai → anthropic → nvidia → openrouter → ollama.
    LLM_FALLBACK_CHAIN accepts `provider:model`, `provider` (modèle par défaut)
    or `provider:*` (TOUS les modèles utilisables du catalogue : `:free` pour
    openrouter, gratuité garantie ; catalogue chat pour nvidia). Avec des entrées
    supplémentaires, le résultat est enveloppé d'un FallbackChatProvider qui
    bascule de modèle automatiquement au quota (429) ou en cas d'échec, avec un
    cooldown en escalier par modèle.
    """
    choice = settings.llm_provider.lower()
    if choice in ("mock", "none"):
        return None
    candidates: dict[str, ChatProvider | None] = {
        name: _make_provider(name) for name in ("openai", "anthropic", "openrouter", "nvidia", "ollama")
    }
    if choice != "auto":
        primary = candidates.get(choice)
        if primary is None:
            logger.warning("Provider LLM '%s' configuré mais clé absente — fallback policy", choice)
    else:
        primary = next(
            (candidates[k] for k in ("openai", "anthropic", "nvidia", "openrouter") if candidates[k]),
            candidates["ollama"],
        )
    chain: list[ChatProvider] = [primary] if primary is not None else []
    seen = {_label(p) for p in chain}
    for raw in settings.llm_fallback_chain.split(","):
        entry = raw.strip()
        if not entry:
            continue
        name, _, model = entry.partition(":")
        name, model = name.strip().lower(), model.strip()
        if _provider_conn(name) is None:
            logger.warning("Repli '%s' ignoré (fournisseur non configuré ou inconnu)", entry)
            continue
        for mid in (_expand_wildcard(name) if model == "*" else [model or None]):
            fallback = _make_provider(name, mid)
            if fallback is None or _label(fallback) in seen:
                continue
            seen.add(_label(fallback))
            chain.append(fallback)
    if not chain:
        return None
    if len(chain) == 1:
        return chain[0]
    return FallbackChatProvider(chain)


# --------------------------------------------------------------------------- #
# Embeddings
# --------------------------------------------------------------------------- #
def local_embed(text: str, dim: int | None = None) -> list[float]:
    """Deterministic hashing embedding (no external dependency).

    Used for development/tests and as a safe fallback so RAG never hard-fails.
    In production set OPENAI_API_KEY (or OLLAMA_HOST) for real embeddings.
    """
    dim = dim or settings.embedding_dim
    vec = [0.0] * dim
    tokens = re.findall(r"[\wÀ-ÿ']+", text.lower())
    if not tokens:
        return vec
    for tok in tokens:
        digest = hashlib.md5(tok.encode()).digest()
        idx = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
        # bigram feature for short queries
        if len(tok) >= 4:
            idx2 = int.from_bytes(digest[5:9], "little") % dim
            vec[idx2] += 0.5 * sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    provider = settings.embeddings_provider.lower()
    dim = settings.embedding_dim

    use_openai = provider == "openai" or (provider == "auto" and settings.openai_api_key)
    use_ollama = provider == "ollama" or (provider == "auto" and not use_openai and settings.ollama_host)

    if use_openai and settings.openai_api_key:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{settings.openai_base_url.rstrip('/')}/embeddings",
                    json={"model": settings.embedding_model, "input": texts},
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()["data"]
                return [d["embedding"] for d in data]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            logger.warning("Embeddings OpenAI indisponibles (%s) — fallback local", exc)

    if use_ollama and provider != "local":
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                out: list[list[float]] = []
                for t in texts:
                    resp = await client.post(
                        f"{settings.ollama_host.rstrip('/')}/api/embed",
                        json={"model": settings.embedding_model, "input": t},
                    )
                    resp.raise_for_status()
                    out.append(resp.json()["embeddings"][0])
                return out
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            logger.warning("Embeddings Ollama indisponibles (%s) — fallback local", exc)

    await asyncio.sleep(0)  # keep the event loop responsive on large batches
    return [local_embed(t, dim) for t in texts]

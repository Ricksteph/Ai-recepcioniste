"""Application settings for AI Receptionist backend."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AI Receptionist"
    environment: str = "development"
    api_prefix: str = "/api"

    # Database: postgresql+asyncpg://... in production, sqlite+aiosqlite://... for dev/tests
    database_url: str = "sqlite+aiosqlite:///./ai_receptionist.db"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60 * 24

    # LLM providers -----------------------------------------------------------
    # provider: auto | openai | anthropic | openrouter | nvidia | ollama | mock
    llm_provider: str = "auto"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # défaut `:free` — gratuité garantie sans configuration supplémentaire
    openrouter_model: str = "google/gemma-4-31b-it:free"
    # NVIDIA NIM — OpenAI-compatible, gratuit (~40 req/min) : https://build.nvidia.com
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "mistralai/mistral-large-2-instruct"
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    # Chaîne de repli (§20) — si le modèle courant renvoie 429 (quota atteint)
    # ou échoue, le moteur bascule automatiquement sur le modèle suivant de la
    # liste, puis sur la policy locale en dernier recours.
    # Format : "provider:model,provider:model" (model omis = défaut du provider)
    #        ou "provider:*" = TOUS les modèles utilisables du catalogue
    #        (openrouter:* = uniquement :free ; nvidia:* = tout le chat)
    # Ex : LLM_FALLBACK_CHAIN=nvidia:*,openrouter:*
    llm_fallback_chain: str = ""
    llm_cooldown_seconds: float = 120.0       # 1er cooldown après 429 (double ensuite)
    llm_cooldown_max_seconds: float = 3600.0  # plafond d'escalade du cooldown

    # Embeddings: auto | openai | ollama | local
    embeddings_provider: str = "auto"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    # Outgoing email (send_email tool). Empty => tool reports "failed: not configured"
    smtp_url: str = ""

    default_timezone: str = "Europe/Paris"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

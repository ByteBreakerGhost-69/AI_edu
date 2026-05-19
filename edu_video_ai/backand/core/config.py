"""
backend/core/config.py

Centralized configuration management using pydantic-settings.
All values are loaded from environment variables or a .env file.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── FastAPI ────────────────────────────────────────────────────────────
    project_name: str = Field(default="EduAI System", description="Human-readable app name")
    debug: bool = Field(default=False, description="Enable FastAPI debug mode")
    environment: Literal["development", "staging", "production"] = Field(
        default="development"
    )
    api_v1_prefix: str = Field(default="/api/v1")
    allowed_origins: list[str] = Field(
        default=["http://localhost:3000"],
        description="CORS allowed origins",
    )

    # ── PostgreSQL (async) ─────────────────────────────────────────────────
    postgres_dsn: PostgresDsn = Field(
        ...,
        description="Async PostgreSQL DSN, e.g. postgresql+asyncpg://user:pass@host/db",
    )
    postgres_pool_size: int = Field(default=10, ge=1, le=100)
    postgres_max_overflow: int = Field(default=20, ge=0, le=100)
    postgres_echo_sql: bool = Field(default=False, description="Log all SQL statements")

    # ── Redis (async) ──────────────────────────────────────────────────────
    redis_dsn: RedisDsn = Field(
        ...,
        description="Async Redis DSN, e.g. redis://localhost:6379/0",
    )
    redis_max_connections: int = Field(default=20, ge=1)
    redis_default_ttl_seconds: int = Field(
        default=3600,
        ge=60,
        description="Default TTL for short-term agent memory keys",
    )

    # ── Qdrant ────────────────────────────────────────────────────────────
    qdrant_url: str = Field(..., description="Qdrant base URL, e.g. http://localhost:6333")
    qdrant_api_key: str | None = Field(
        default=None,
        description="API key for Qdrant Cloud; leave empty for local instances",
    )
    qdrant_default_collection: str = Field(default="education_knowledge_base")
    qdrant_vector_size: int = Field(
        default=1536,
        description="Embedding dimension — must match the embedding model used",
    )

    # ── Third-party LLM & AI API Keys ─────────────────────────────────────
    anthropic_api_key: str = Field(..., description="Anthropic Claude API key")
    anthropic_default_model: str = Field(default="claude-sonnet-4-5")

    openai_api_key: str | None = Field(default=None, description="OpenAI API key")
    openai_default_model: str = Field(default="gpt-4o")

    grok_api_key: str | None = Field(default=None, description="xAI Grok API key")
    grok_base_url: str = Field(default="https://api.x.ai/v1")
    grok_default_model: str = Field(default="grok-3")

    elevenlabs_api_key: str | None = Field(
        default=None, description="ElevenLabs TTS API key"
    )
    elevenlabs_default_voice_id: str = Field(default="EXAVITQu4vr4xnSDxMaL")

    kling_api_key: str | None = Field(
        default=None, description="Kling AI video generation API key"
    )
    kling_base_url: str = Field(default="https://api.klingai.com")

    # ── Celery / Task Queue ───────────────────────────────────────────────
    celery_broker_url: str = Field(
        default="redis://localhost:6379/1",
        description="Celery broker — separate Redis DB from short-term memory",
    )
    celery_result_backend: str = Field(default="redis://localhost:6379/2")

    # ── Derived helpers ───────────────────────────────────────────────────
    @field_validator("postgres_dsn", mode="before")
    @classmethod
    def ensure_async_driver(cls, v: str) -> str:
        """Auto-correct plain 'postgresql://' to 'postgresql+asyncpg://'."""
        if isinstance(v, str) and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return a cached singleton Settings instance.

    Usage in FastAPI dependencies:
        from backend.core.config import get_settings
        settings = get_settings()
    """
    return Settings()


# Module-level singleton for direct imports
settings: Settings = get_settings()
  

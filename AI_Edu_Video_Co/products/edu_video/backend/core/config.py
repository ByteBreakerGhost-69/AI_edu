"""
core/config.py
Centralized configuration for edu_video backend.
All values are loaded from environment variables / .env file.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LLMProvider(str, Enum):
    CLAUDE = "claude"
    OPENAI = "openai"
    GROK = "grok"


class StorageProvider(str, Enum):
    S3 = "s3"
    GCS = "gcs"


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    APP_NAME: str = "edu-video-backend"
    DEBUG: bool = False
    ENVIRONMENT: Environment = Environment.DEVELOPMENT

    # ------------------------------------------------------------------
    # PostgreSQL (async DSN — asyncpg dialect)
    # Example: postgresql+asyncpg://user:pass@host:5432/dbname
    # ------------------------------------------------------------------
    DATABASE_URL: str = Field(
        ...,
        description="Async PostgreSQL DSN (postgresql+asyncpg://...)",
    )
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # ------------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------------
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )

    # ------------------------------------------------------------------
    # Qdrant (vector DB)
    # ------------------------------------------------------------------
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: SecretStr | None = None  # optional for local dev
    QDRANT_COLLECTION_NAME: str = "edu_video_knowledge"

    # ------------------------------------------------------------------
    # LLM — provider selection + API keys
    # ------------------------------------------------------------------
    LLM_PROVIDER: LLMProvider = LLMProvider.CLAUDE

    ANTHROPIC_API_KEY: SecretStr | None = None
    ANTHROPIC_DEFAULT_MODEL: str = "claude-sonnet-4-20250514"
    ANTHROPIC_MAX_TOKENS: int = 8192

    OPENAI_API_KEY: SecretStr | None = None          # also used for Grok via base_url
    OPENAI_DEFAULT_MODEL: str = "gpt-4o"
    OPENAI_BASE_URL: str | None = None               # override for Grok: https://api.x.ai/v1

    @model_validator(mode="after")
    def _validate_llm_keys(self) -> "Settings":
        """Raise early if the selected LLM provider has no API key."""
        if self.LLM_PROVIDER == LLMProvider.CLAUDE and not self.ANTHROPIC_API_KEY:
            raise ValueError(
                "LLM_PROVIDER is 'claude' but ANTHROPIC_API_KEY is not set."
            )
        if self.LLM_PROVIDER in (LLMProvider.OPENAI, LLMProvider.GROK):
            if not self.OPENAI_API_KEY:
                raise ValueError(
                    f"LLM_PROVIDER is '{self.LLM_PROVIDER}' but OPENAI_API_KEY is not set."
                )
            if self.LLM_PROVIDER == LLMProvider.GROK and not self.OPENAI_BASE_URL:
                raise ValueError(
                    "LLM_PROVIDER is 'grok' but OPENAI_BASE_URL is not set "
                    "(expected e.g. https://api.x.ai/v1)."
                )
        return self

    # ------------------------------------------------------------------
    # TTS — ElevenLabs
    # ------------------------------------------------------------------
    ELEVENLABS_API_KEY: SecretStr | None = None
    ELEVENLABS_DEFAULT_VOICE_ID: str = "21m00Tcm4TlvDq8ikWAM"  # Rachel

    # ------------------------------------------------------------------
    # Storage — S3 or GCS
    # ------------------------------------------------------------------
    STORAGE_PROVIDER: StorageProvider = StorageProvider.S3

    # AWS S3
    AWS_ACCESS_KEY_ID: SecretStr | None = None
    AWS_SECRET_ACCESS_KEY: SecretStr | None = None
    AWS_REGION: str = "ap-southeast-1"
    AWS_BUCKET_NAME: str | None = None

    # GCS (mutually exclusive with S3)
    GCS_PROJECT_ID: str | None = None
    GCS_BUCKET_NAME: str | None = None
    GCS_SERVICE_ACCOUNT_JSON: str | None = None  # path to JSON keyfile

    @model_validator(mode="after")
    def _validate_storage_config(self) -> "Settings":
        if self.STORAGE_PROVIDER == StorageProvider.S3:
            missing = [
                k for k, v in {
                    "AWS_ACCESS_KEY_ID": self.AWS_ACCESS_KEY_ID,
                    "AWS_SECRET_ACCESS_KEY": self.AWS_SECRET_ACCESS_KEY,
                    "AWS_BUCKET_NAME": self.AWS_BUCKET_NAME,
                }.items() if not v
            ]
            if missing:
                raise ValueError(
                    f"STORAGE_PROVIDER is 's3' but missing: {', '.join(missing)}"
                )
        if self.STORAGE_PROVIDER == StorageProvider.GCS:
            missing = [
                k for k, v in {
                    "GCS_PROJECT_ID": self.GCS_PROJECT_ID,
                    "GCS_BUCKET_NAME": self.GCS_BUCKET_NAME,
                    "GCS_SERVICE_ACCOUNT_JSON": self.GCS_SERVICE_ACCOUNT_JSON,
                }.items() if not v
            ]
            if missing:
                raise ValueError(
                    f"STORAGE_PROVIDER is 'gcs' but missing: {', '.join(missing)}"
                )
        return self

    # ------------------------------------------------------------------
    # Celery (task queue — broker & result via Redis by default)
    # ------------------------------------------------------------------
    CELERY_BROKER_URL: str = Field(
        default="redis://localhost:6379/1",
        description="Celery broker URL",
    )
    CELERY_RESULT_BACKEND: str = Field(
        default="redis://localhost:6379/2",
        description="Celery result backend URL",
    )
    CELERY_TASK_SERIALIZER: Literal["json", "msgpack"] = "json"
    CELERY_WORKER_CONCURRENCY: int = 4

    # ------------------------------------------------------------------
    # Auth — JWT
    # ------------------------------------------------------------------
    JWT_SECRET_KEY: SecretStr = Field(
        ...,
        description="Secret key used to sign JWT tokens",
    )
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60 * 24  # 24 hours

    # ------------------------------------------------------------------
    # Cost tracking
    # ------------------------------------------------------------------
    COST_TRACKING_ENABLED: bool = True
    DEFAULT_MODEL_COST_PER_1K_TOKEN: float = 0.003  # USD, rough default

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    SENTRY_DSN: str | None = None  # optional error tracking

    # ------------------------------------------------------------------
    # Derived helpers (not env vars)
    # ------------------------------------------------------------------

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == Environment.PRODUCTION

    @property
    def qdrant_url(self) -> str:
        return f"http://{self.QDRANT_HOST}:{self.QDRANT_PORT}"

    @property
    def active_bucket(self) -> str:
        """Return the bucket name for the configured storage provider."""
        if self.STORAGE_PROVIDER == StorageProvider.GCS:
            return self.GCS_BUCKET_NAME or ""
        return self.AWS_BUCKET_NAME or ""


# ---------------------------------------------------------------------------
# Global singleton — import this everywhere:
#   from core.config import settings
# ---------------------------------------------------------------------------

settings = Settings()
  

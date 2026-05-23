# products/edu_video/backend/core/config.py
"""
Application configuration using Pydantic BaseSettings v2.
Loads from .env file with environment variable overrides.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "get_settings"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---
    APP_NAME: str = "EduVideo"
    APP_ENV: str = "dev"  # dev | staging | prod
    DEBUG: bool = False
    SECRET_KEY: str

    # --- Database ---
    POSTGRES_URL: str  # postgresql+asyncpg://user:pass@host/db
    REDIS_URL: str     # redis://localhost:6379/0

    # --- Qdrant ---
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: str | None = None
    QDRANT_COLLECTION_NAME: str = "edu_video_knowledge"

    # --- LLM ---
    ANTHROPIC_API_KEY: str
    GROQ_API_KEY: str
    DEFAULT_LLM_PROVIDER: str = "claude"  # "claude" | "grok"

    # --- Auth ---
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # --- Storage ---
    GCS_BUCKET_NAME: str
    GCS_PROJECT_ID: str

    # --- Billing ---
    STRIPE_SECRET_KEY: str
    STRIPE_WEBHOOK_SECRET: str


@lru_cache()
def get_settings() -> Settings:
    """Return cached Settings instance. Call once at startup."""
    return Settings()

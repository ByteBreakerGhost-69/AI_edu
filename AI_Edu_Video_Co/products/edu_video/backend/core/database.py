# products/edu_video/backend/core/database.py
"""
Async database connections: PostgreSQL via SQLAlchemy + Redis via redis.asyncio.
Provides FastAPI dependency generators and startup initializer.
"""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from redis.asyncio import Redis, from_url
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from core.config import get_settings

__all__ = [
    "Base",
    "AsyncSessionLocal",
    "get_db",
    "get_redis",
    "init_db",
]

logger = structlog.get_logger(__name__)
settings = get_settings()

# --- SQLAlchemy ---

engine = create_async_engine(
    settings.POSTGRES_URL,
    pool_size=10,
    max_overflow=20,
    echo=settings.DEBUG,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async DB session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create all tables on application startup. Safe to call multiple times."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("database.tables_created")


# --- Redis ---

_redis_client: Redis | None = None


async def _create_redis_client() -> Redis:
    """Create Redis client with retry logic (3 attempts, exponential backoff)."""
    attempts = 3
    delay = 1.0
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            client: Redis = from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
            await client.ping()
            logger.info("redis.connected", attempt=attempt)
            return client
        except RedisConnectionError as exc:
            last_exc = exc
            logger.warning(
                "redis.connection_failed",
                attempt=attempt,
                retry_in=delay,
                error=str(exc),
            )
            if attempt < attempts:
                await asyncio.sleep(delay)
                delay *= 2.0

    raise RuntimeError(
        f"Redis unavailable after {attempts} attempts"
    ) from last_exc


async def get_redis() -> AsyncGenerator[Redis, None]:
    """FastAPI dependency: yields the shared Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = await _create_redis_client()
    yield _redis_client

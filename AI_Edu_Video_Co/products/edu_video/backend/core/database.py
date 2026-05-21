"""
core/database.py
Async database connections: PostgreSQL (SQLAlchemy + asyncpg) and Redis.
Call startup_db() on app startup and shutdown_db() on app shutdown.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as aioredis
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from core.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SQLAlchemy — Base declarative class (shared across models/)
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


# ---------------------------------------------------------------------------
# PostgreSQL engine & session factory
# ---------------------------------------------------------------------------

engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,          # verify connections before use
    pool_recycle=3600,           # recycle connections every hour
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ---------------------------------------------------------------------------
# Redis client (module-level singleton, initialised in startup_db)
# ---------------------------------------------------------------------------

_redis_client: Redis | None = None  # type: ignore[type-arg]


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency — yields an async DB session and guarantees cleanup.

    Usage::

        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            raise


async def get_redis() -> Redis:  # type: ignore[type-arg]
    """
    FastAPI dependency — returns the shared Redis client.

    Usage::

        @router.get("/cache")
        async def cached(redis: Redis = Depends(get_redis)):
            ...
    """
    if _redis_client is None:
        raise RuntimeError(
            "Redis client is not initialised. "
            "Ensure startup_db() was called during app startup."
        )
    return _redis_client


# ---------------------------------------------------------------------------
# Schema initialisation (dev / testing only — prefer Alembic in production)
# ---------------------------------------------------------------------------


async def init_db() -> None:
    """
    Create all tables defined via ORM models.

    In production use Alembic migrations instead.
    Safe to call in development and CI environments.
    """
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialised via Base.metadata.create_all.")
    except SQLAlchemyError as exc:
        logger.error("Failed to initialise database schema: %s", exc)
        raise


# ---------------------------------------------------------------------------
# Lifecycle helpers
# ---------------------------------------------------------------------------


async def startup_db() -> None:
    """
    Initialise PostgreSQL connection pool and Redis client.
    Call this inside the FastAPI lifespan startup block.
    """
    global _redis_client  # noqa: PLW0603

    # --- PostgreSQL health check ---
    logger.info("Connecting to PostgreSQL …")
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info(
            "PostgreSQL connection pool ready (pool_size=%d, max_overflow=%d).",
            settings.DATABASE_POOL_SIZE,
            settings.DATABASE_MAX_OVERFLOW,
        )
    except OperationalError as exc:
        logger.error("PostgreSQL connection failed: %s", exc)
        raise

    # --- Redis ---
    logger.info("Connecting to Redis …")
    try:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        await _redis_client.ping()
        logger.info("Redis connection established: %s", settings.REDIS_URL)
    except Exception as exc:
        logger.error("Redis connection failed: %s", exc)
        raise


async def shutdown_db() -> None:
    """
    Gracefully dispose the PostgreSQL engine and close the Redis client.
    Call this inside the FastAPI lifespan shutdown block.
    """
    logger.info("Disposing PostgreSQL connection pool …")
    await engine.dispose()
    logger.info("PostgreSQL engine disposed.")

    if _redis_client is not None:
        logger.info("Closing Redis connection …")
        await _redis_client.aclose()
        logger.info("Redis connection closed.")


async def close_db_connection() -> None:
    """Alias for shutdown_db(); kept for explicitness in shutdown hooks."""
    await shutdown_db()


async def close_redis() -> None:
    """Close only the Redis client (used in tests or partial teardown)."""
    if _redis_client is not None:
        await _redis_client.aclose()
        logger.info("Redis connection closed.")


# ---------------------------------------------------------------------------
# Convenience: raw Redis access outside dependency injection
# ---------------------------------------------------------------------------


def get_redis_client() -> Redis:  # type: ignore[type-arg]
    """
    Return the Redis client directly (non-dependency form).
    Useful inside background workers and Celery tasks.

    Raises RuntimeError if startup_db() has not been called.
    """
    if _redis_client is None:
        raise RuntimeError(
            "Redis client is not initialised. Call startup_db() first."
        )
    return _redis_client


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: list[str] = [
    # SQLAlchemy
    "Base",
    "engine",
    "AsyncSessionLocal",
    # FastAPI dependencies
    "get_db",
    "get_redis",
    # Direct access (workers / tasks)
    "get_redis_client",
    # Lifecycle
    "init_db",
    "startup_db",
    "shutdown_db",
    "close_db_connection",
    "close_redis",
]
  

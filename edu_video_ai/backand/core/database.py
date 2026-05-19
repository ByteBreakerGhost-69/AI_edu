"""
backend/core/database.py

Manages async connections for:
  - PostgreSQL via SQLAlchemy (AsyncSession)
  - Redis via redis.asyncio

Provides FastAPI dependency `get_db_session()` and lifecycle helpers
`init_db_connections()` / `close_db_connections()` for use in main.py startup/shutdown.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from backend.core.config import settings

logger = logging.getLogger(__name__)


# ── SQLAlchemy Base ──────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    """
    Declarative base for all ORM models.
    Import this in each model file:
        from backend.core.database import Base
    """
    pass


# ── Module-level singletons (populated during startup) ───────────────────────

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_redis_pool: aioredis.ConnectionPool | None = None
_redis_client: aioredis.Redis | None = None  # type: ignore[type-arg]


# ── Initialization & Teardown ────────────────────────────────────────────────


async def init_db_connections() -> None:
    """
    Create async engine, session factory, and Redis pool.
    Call this once inside the FastAPI lifespan startup hook.
    """
    global _engine, _session_factory, _redis_pool, _redis_client

    # ── PostgreSQL ──
    logger.info("Initialising PostgreSQL async engine …")
    _engine = create_async_engine(
        str(settings.postgres_dsn),
        echo=settings.postgres_echo_sql,
        pool_size=settings.postgres_pool_size,
        max_overflow=settings.postgres_max_overflow,
        pool_pre_ping=True,          # validate connections before use
        # Use NullPool in test environments to avoid connection leaks:
        # poolclass=NullPool,
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,       # avoid lazy-load surprises after commit
        autoflush=False,
    )
    logger.info("PostgreSQL engine ready.")

    # ── Redis ──
    logger.info("Initialising Redis async pool …")
    _redis_pool = aioredis.ConnectionPool.from_url(
        str(settings.redis_dsn),
        max_connections=settings.redis_max_connections,
        decode_responses=True,        # return str, not bytes
    )
    _redis_client = aioredis.Redis(connection_pool=_redis_pool)

    # Smoke-test the Redis connection
    pong = await _redis_client.ping()
    if not pong:
        raise RuntimeError("Redis ping failed during startup — check REDIS_DSN.")
    logger.info("Redis pool ready.")


async def close_db_connections() -> None:
    """
    Gracefully close all connections.
    Call this inside the FastAPI lifespan shutdown hook.
    """
    global _engine, _redis_client, _redis_pool

    if _engine is not None:
        logger.info("Disposing PostgreSQL engine …")
        await _engine.dispose()
        _engine = None

    if _redis_client is not None:
        logger.info("Closing Redis client …")
        await _redis_client.aclose()
        _redis_client = None

    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None

    logger.info("All DB connections closed.")


# ── FastAPI Dependency ────────────────────────────────────────────────────────


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields a transactional AsyncSession.

    Usage:
        @router.post("/jobs")
        async def create_job(db: AsyncSession = Depends(get_db_session)):
            ...
    """
    if _session_factory is None:
        raise RuntimeError(
            "Database not initialised. "
            "Ensure `init_db_connections()` is called during app startup."
        )

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Redis Accessors ───────────────────────────────────────────────────────────


def get_redis() -> aioredis.Redis:  # type: ignore[type-arg]
    """
    Return the shared Redis client.
    Raises RuntimeError if called before `init_db_connections()`.
    """
    if _redis_client is None:
        raise RuntimeError(
            "Redis not initialised. "
            "Ensure `init_db_connections()` is called during app startup."
        )
    return _redis_client


@asynccontextmanager
async def redis_pipeline() -> AsyncGenerator[Any, None]:
    """
    Yield a Redis pipeline for batched commands.

    Usage:
        async with redis_pipeline() as pipe:
            pipe.set("key1", "val1")
            pipe.expire("key1", 3600)
            await pipe.execute()
    """
    client = get_redis()
    async with client.pipeline(transaction=True) as pipe:
        yield pipe


# ── Table Creation Helper (dev / test only) ───────────────────────────────────


async def create_all_tables() -> None:
    """
    Create all SQLAlchemy-mapped tables.
    Intended for development and integration tests only — use Alembic in production.
    """
    if _engine is None:
        raise RuntimeError("Engine not initialised.")
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("All tables created (dev mode).")
  

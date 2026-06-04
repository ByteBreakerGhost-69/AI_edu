# products/edu_video/backend/utils/cache.py
"""
Redis cache decorators, invalidation helpers, and local LRU cache.
Provides a layered caching strategy:
  L1: in-process LRU cache (fast, no network, limited size)
  L2: Redis cache (shared across processes, configurable TTL)
"""

import asyncio
import functools
import json
import time
from collections import OrderedDict
from typing import Any, Callable, TypeVar

from core.config import get_settings
from core.database import _redis_client, _create_redis_client
from utils.logging import get_logger

__all__ = [
    "cache_result",
    "invalidate_cache",
    "invalidate_pattern",
    "LRUCache",
    "local_lru_cache",
    "CacheStats",
    "get_cache_stats",
]

F = TypeVar("F", bound=Callable[..., Any])
_log = get_logger(__name__)
_settings = get_settings()

_CACHE_PREFIX = "edu_video:cache"


# --------------------------------------------------------------------------- #
# Redis helper                                                                  #
# --------------------------------------------------------------------------- #

async def _get_redis():
    from core.database import _redis_client  # noqa: PLC0415
    if _redis_client is None:
        return await _create_redis_client()
    return _redis_client


# --------------------------------------------------------------------------- #
# Local LRU cache                                                               #
# --------------------------------------------------------------------------- #

class LRUCache:
    """
    Thread-safe in-process LRU cache with optional TTL per entry.
    Used as L1 cache before hitting Redis.

    Usage:
        _tier_cache = LRUCache(maxsize=128, default_ttl=300)
        value = _tier_cache.get("tier:premium")
        if value is None:
            value = compute_expensive_thing()
            _tier_cache.set("tier:premium", value, ttl=600)
    """

    def __init__(self, maxsize: int = 256, default_ttl: float = 60.0) -> None:
        """
        Args:
            maxsize:     Maximum number of entries before LRU eviction.
            default_ttl: Default TTL in seconds. Use 0 for no expiry.
        """
        self._maxsize = maxsize
        self._default_ttl = default_ttl
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key: str) -> Any | None:
        """Return cached value or None if missing/expired."""
        if key not in self._cache:
            self._misses += 1
            return None

        value, expires_at = self._cache[key]

        if expires_at > 0 and time.monotonic() > expires_at:
            del self._cache[key]
            self._misses += 1
            return None

        # Move to end (most recently used)
        self._cache.move_to_end(key)
        self._hits += 1
        return value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Set a cache entry with optional TTL override."""
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expires_at = (
            time.monotonic() + effective_ttl if effective_ttl > 0 else 0.0
        )

        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = (value, expires_at)

        while len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)
            self._evictions += 1

    def delete(self, key: str) -> bool:
        """Delete a cache entry. Returns True if it existed."""
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self) -> None:
        """Remove all entries."""
        self._cache.clear()

    def invalidate_prefix(self, prefix: str) -> int:
        """Remove all entries whose key starts with prefix. Returns count removed."""
        to_remove = [k for k in self._cache if k.startswith(prefix)]
        for k in to_remove:
            del self._cache[k]
        return len(to_remove)

    @property
    def stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "maxsize": self._maxsize,
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "hit_rate": round(self._hits / total, 4) if total > 0 else 0.0,
        }


# --------------------------------------------------------------------------- #
# Module-level local caches                                                     #
# --------------------------------------------------------------------------- #

# Small, fast caches for frequently-read, rarely-changing data
_tier_config_cache = LRUCache(maxsize=10, default_ttl=300.0)
_subject_profile_cache = LRUCache(maxsize=20, default_ttl=600.0)
_curriculum_prompt_cache = LRUCache(maxsize=30, default_ttl=3600.0)


# --------------------------------------------------------------------------- #
# Cache key builder                                                             #
# --------------------------------------------------------------------------- #

def _build_cache_key(prefix: str, *args: Any, **kwargs: Any) -> str:
    """
    Build a deterministic Redis cache key from function arguments.

    Strategy:
        - Positional args: serialised as JSON
        - Keyword args: sorted by key, serialised as JSON
        - Result: "{prefix}:{args_hash}:{kwargs_hash}"
    """
    import hashlib  # noqa: PLC0415

    def _serialise(obj: Any) -> str:
        try:
            return json.dumps(obj, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(obj)

    parts = [prefix]
    if args:
        parts.append(hashlib.md5(_serialise(args).encode()).hexdigest()[:8])
    if kwargs:
        parts.append(
            hashlib.md5(_serialise(sorted(kwargs.items())).encode()).hexdigest()[:8]
        )
    return ":".join(parts)


# --------------------------------------------------------------------------- #
# cache_result decorator                                                        #
# --------------------------------------------------------------------------- #

def cache_result(
    ttl: int = 300,
    prefix: str | None = None,
    key_args: list[str] | None = None,
    skip_cache_if: Callable[..., bool] | None = None,
    local_lru: LRUCache | None = None,
) -> Callable[[F], F]:
    """
    Decorator: cache async function results in Redis (L2) with optional L1 LRU.

    Args:
        ttl:           Redis cache TTL in seconds.
        prefix:        Cache key prefix. Defaults to "{module}.{qualname}".
        key_args:      If set, only use these kwarg names to build the key.
                       Useful to exclude non-serialisable args like `db`.
        skip_cache_if: Callable(*args, **kwargs) → bool.
                       If returns True, bypass cache entirely for this call.
        local_lru:     Optional L1 LRU cache to check before Redis.

    Usage:
        @cache_result(ttl=3600, prefix="rag:query", key_args=["query", "curriculum"])
        async def query_rag(self, query: str, curriculum: str, db: AsyncSession):
            ...

        @cache_result(ttl=300, local_lru=_tier_config_cache)
        async def get_tier_features(tier: str) -> TierFeatures:
            ...
    """
    def decorator(func: F) -> F:
        cache_prefix = prefix or f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Optionally bypass cache
            if skip_cache_if is not None and skip_cache_if(*args, **kwargs):
                return await func(*args, **kwargs)

            # Build cache key from selected kwargs or all kwargs
            key_kwargs = (
                {k: kwargs[k] for k in key_args if k in kwargs}
                if key_args
                else kwargs
            )
            cache_key = _build_cache_key(
                f"{_CACHE_PREFIX}:{cache_prefix}", *args, **key_kwargs
            )

            # L1: check local LRU first
            if local_lru is not None:
                cached = local_lru.get(cache_key)
                if cached is not None:
                    return cached

            # L2: check Redis
            try:
                redis = await _get_redis()
                raw = await redis.get(cache_key)
                if raw is not None:
                    value = json.loads(raw)
                    if local_lru is not None:
                        local_lru.set(cache_key, value, ttl=min(ttl, 60.0))
                    return value
            except Exception as exc:
                _log.warning("cache.redis_get_failed", key=cache_key, error=str(exc))

            # Cache miss — compute
            result = await func(*args, **kwargs)

            # Store in Redis
            try:
                redis = await _get_redis()
                serialised = json.dumps(result, default=str)
                await redis.setex(cache_key, ttl, serialised)
            except Exception as exc:
                _log.warning("cache.redis_set_failed", key=cache_key, error=str(exc))

            # Store in L1
            if local_lru is not None:
                local_lru.set(cache_key, result, ttl=min(ttl, 60.0))

            return result

        return wrapper  # type: ignore[return-value]

    return decorator


# --------------------------------------------------------------------------- #
# Cache invalidation                                                            #
# --------------------------------------------------------------------------- #

async def invalidate_cache(
    func_or_key: Any,
    *args: Any,
    prefix: str | None = None,
    key_args: list[str] | None = None,
    **kwargs: Any,
) -> bool:
    """
    Invalidate a specific cache entry.

    Usage:
        # Invalidate by function + args (mirrors cache_result key building):
        await invalidate_cache(get_tier_features, "premium")

        # Invalidate by explicit key:
        await invalidate_cache("edu_video:cache:rag:query:abc123")
    """
    if isinstance(func_or_key, str):
        cache_key = func_or_key
    else:
        func = func_or_key
        cache_prefix = prefix or f"{func.__module__}.{func.__qualname__}"
        key_kwargs = (
            {k: kwargs[k] for k in key_args if k in kwargs}
            if key_args
            else kwargs
        )
        cache_key = _build_cache_key(
            f"{_CACHE_PREFIX}:{cache_prefix}", *args, **key_kwargs
        )

    try:
        redis = await _get_redis()
        deleted = await redis.delete(cache_key)
        _log.debug("cache.invalidated", key=cache_key, existed=bool(deleted))
        return bool(deleted)
    except Exception as exc:
        _log.warning("cache.invalidate_failed", key=cache_key, error=str(exc))
        return False


async def invalidate_pattern(pattern: str) -> int:
    """
    Invalidate all Redis cache keys matching a glob pattern.
    WARNING: Uses SCAN — safe for production (non-blocking), but slow on large keybases.
    Returns count of deleted keys.

    Usage:
        # Invalidate all RAG query caches:
        await invalidate_pattern("edu_video:cache:layer3_rag*")

        # Invalidate all caches for a specific job:
        await invalidate_pattern(f"*job_id={job_id}*")
    """
    deleted = 0
    try:
        redis = await _get_redis()
        async for key in redis.scan_iter(match=pattern, count=100):
            await redis.delete(key)
            deleted += 1
        _log.info("cache.pattern_invalidated", pattern=pattern, deleted=deleted)
    except Exception as exc:
        _log.warning("cache.pattern_invalidate_failed", pattern=pattern, error=str(exc))
    return deleted


# --------------------------------------------------------------------------- #
# local_lru_cache decorator (sync, pure in-process)                            #
# --------------------------------------------------------------------------- #

def local_lru_cache(
    maxsize: int = 128,
    ttl: float = 60.0,
) -> Callable[[F], F]:
    """
    Decorator for sync functions using module-level LRU cache.
    Useful for config lookups, profile registry reads, and tier feature checks.

    Usage:
        @local_lru_cache(maxsize=32, ttl=300)
        def get_subject_keywords(subject: str) -> list[str]:
            ...
    """
    _cache = LRUCache(maxsize=maxsize, default_ttl=ttl)

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = _build_cache_key(
                f"{func.__module__}.{func.__qualname__}", *args, **kwargs
            )
            cached = _cache.get(key)
            if cached is not None:
                return cached
            result = func(*args, **kwargs)
            _cache.set(key, result)
            return result

        wrapper.cache_clear = _cache.clear  # type: ignore[attr-defined]
        wrapper.cache_stats = lambda: _cache.stats  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator


# --------------------------------------------------------------------------- #
# Cache statistics                                                               #
# --------------------------------------------------------------------------- #

class CacheStats:
    """Aggregated cache statistics across all local caches."""

    @staticmethod
    def all() -> dict[str, Any]:
        return {
            "tier_config_cache": _tier_config_cache.stats,
            "subject_profile_cache": _subject_profile_cache.stats,
            "curriculum_prompt_cache": _curriculum_prompt_cache.stats,
        }


async def get_cache_stats() -> dict[str, Any]:
    """
    Return local and Redis cache statistics for monitoring.
    Called by /ready endpoint and admin dashboard.
    """
    local = CacheStats.all()

    redis_stats: dict[str, Any] = {}
    try:
        redis = await _get_redis()
        info = await redis.info("memory")
        redis_stats = {
            "used_memory_mb": round(info.get("used_memory", 0) / 1_048_576, 2),
            "used_memory_peak_mb": round(
                info.get("used_memory_peak", 0) / 1_048_576, 2
            ),
            "maxmemory_mb": round(info.get("maxmemory", 0) / 1_048_576, 2),
        }
    except Exception as exc:
        redis_stats = {"error": str(exc)}

    return {"local": local, "redis": redis_stats}

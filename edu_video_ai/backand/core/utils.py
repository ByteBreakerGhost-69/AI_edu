"""
backend/core/utils.py

Core utility functions used across all layers.

Includes:
  - Prefixed unique ID generation (job_, scene_, asset_, etc.)
  - Timezone-aware UTC timestamps
  - Secure string hashing (for deduplication & cache keys)
  - Lightweight retry decorator for async functions
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# ── ID Prefixes ───────────────────────────────────────────────────────────────


class IDPrefix(str, Enum):
    JOB = "job"
    SCENE = "scene"
    ASSET = "asset"
    USER = "usr"
    FEEDBACK = "fb"
    SESSION = "sess"
    CHUNK = "chk"


# ── ID Generation ─────────────────────────────────────────────────────────────


def generate_id(prefix: IDPrefix | str = IDPrefix.JOB) -> str:
    """
    Generate a URL-safe, collision-resistant unique ID with a typed prefix.

    Format: <prefix>_<uuid4_no_hyphens>
    Example: "job_3f2504e04f8911d39a0c0305e82c3301"

    Args:
        prefix: An IDPrefix enum member or a raw string prefix.

    Returns:
        Prefixed unique ID string.
    """
    raw_prefix = prefix.value if isinstance(prefix, IDPrefix) else prefix
    uid = uuid.uuid4().hex  # 32 lowercase hex chars, no hyphens
    return f"{raw_prefix}_{uid}"


def generate_job_id() -> str:
    return generate_id(IDPrefix.JOB)


def generate_scene_id() -> str:
    return generate_id(IDPrefix.SCENE)


def generate_asset_id() -> str:
    return generate_id(IDPrefix.ASSET)


def generate_session_id() -> str:
    return generate_id(IDPrefix.SESSION)


def generate_chunk_id() -> str:
    return generate_id(IDPrefix.CHUNK)


# ── Timestamps ────────────────────────────────────────────────────────────────


def utc_now() -> datetime:
    """
    Return the current UTC datetime (timezone-aware).

    Always use this instead of `datetime.utcnow()` which returns a naive
    datetime and is deprecated in Python 3.12+.
    """
    return datetime.now(UTC)


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string with 'Z' suffix."""
    return utc_now().isoformat(timespec="milliseconds").replace("+00:00", "Z")


def elapsed_ms(start: datetime) -> int:
    """
    Compute elapsed time in milliseconds from a past UTC datetime.

    Args:
        start: A timezone-aware UTC datetime captured earlier.

    Returns:
        Elapsed time in milliseconds (integer).
    """
    delta = utc_now() - start
    return int(delta.total_seconds() * 1000)


# ── Hashing ───────────────────────────────────────────────────────────────────


def sha256_hex(data: str | bytes) -> str:
    """
    Return the SHA-256 hex digest of a string or bytes object.

    Used for:
      - Deduplication keys in RAG ingestion pipeline
      - Cache key derivation from arbitrary content
      - Integrity checks on stored assets

    Args:
        data: Input string (UTF-8 encoded internally) or raw bytes.

    Returns:
        64-character lowercase hex string.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def content_cache_key(prefix: str, *parts: str) -> str:
    """
    Build a structured Redis cache key from a prefix and variable content parts.

    The content parts are joined, hashed, and combined with the prefix.
    This ensures keys are always a fixed length regardless of input size.

    Example:
        content_cache_key("rag", "mathematics", "grade-10", "pythagorean theorem")
        → "rag:a3f9..."

    Args:
        prefix: Key namespace (e.g. "rag", "tts", "scene").
        *parts: Variable content parts to hash.

    Returns:
        Redis-safe cache key string.
    """
    combined = ":".join(parts)
    digest = sha256_hex(combined)[:16]  # first 16 chars sufficient for cache keys
    return f"{prefix}:{digest}"


# ── Async Retry Decorator ─────────────────────────────────────────────────────


def async_retry(
    max_attempts: int = 3,
    delay_seconds: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """
    Decorator that retries an async function on specified exceptions.

    Args:
        max_attempts:   Total number of attempts (including the first call).
        delay_seconds:  Initial wait time between retries in seconds.
        backoff_factor: Multiplier applied to delay after each failure.
        exceptions:     Tuple of exception types that trigger a retry.

    Usage:
        @async_retry(max_attempts=3, delay_seconds=0.5, exceptions=(httpx.TimeoutException,))
        async def call_external_api() -> dict:
            ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_delay = delay_seconds
            last_exc: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        logger.error(
                            "Function '%s' failed after %d attempts. Last error: %s",
                            func.__name__,
                            max_attempts,
                            exc,
                        )
                        raise
                    logger.warning(
                        "Function '%s' attempt %d/%d failed (%s). Retrying in %.1fs …",
                        func.__name__,
                        attempt,
                        max_attempts,
                        type(exc).__name__,
                        current_delay,
                    )
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff_factor

            raise last_exc  # type: ignore[misc]  # unreachable, satisfies type checker

        return wrapper  # type: ignore[return-value]
    return decorator


# ── Miscellaneous ─────────────────────────────────────────────────────────────


def truncate_string(text: str, max_length: int = 200, suffix: str = "…") -> str:
    """
    Safely truncate a string for log messages or preview fields.

    Args:
        text:       Input string.
        max_length: Maximum character length before truncation.
        suffix:     Appended when truncation occurs.

    Returns:
        Original string if within limit, else truncated string with suffix.
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def chunk_list(items: list[Any], chunk_size: int) -> list[list[Any]]:
    """
    Split a list into fixed-size chunks.

    Used by the RAG ingestion pipeline to batch embed documents.

    Args:
        items:      Source list.
        chunk_size: Maximum items per chunk.

    Returns:
        List of sub-lists, each at most `chunk_size` elements.
    """
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]
  

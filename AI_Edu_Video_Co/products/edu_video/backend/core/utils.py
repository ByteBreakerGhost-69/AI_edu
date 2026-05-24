# products/edu_video/backend/core/utils.py
"""
Shared utility functions. No external dependencies beyond stdlib + python-dateutil.
Import freely across all layers — this module must not import from other core files.
"""

import asyncio
import json
import re
import unicodedata
import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from typing import Any, TypeVar

__all__ = [
    "generate_uuid",
    "slugify",
    "utcnow",
    "truncate_text",
    "chunk_list",
    "safe_json_loads",
    "retry_async",
    "mask_sensitive",
    "format_cost_usd",
]

T = TypeVar("T")


def generate_uuid() -> str:
    """Return a random UUID4 as a lowercase string."""
    return str(uuid.uuid4())


def slugify(text: str) -> str:
    """
    Convert text to a URL-safe lowercase slug.
    Example: "Aljabar Linear (Matriks)" → "aljabar-linear-matriks"
    """
    # Normalize unicode → ASCII
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    # Lowercase and replace non-alphanumeric with hyphens
    slug = re.sub(r"[^\w\s-]", "", ascii_text).strip().lower()
    slug = re.sub(r"[\s_-]+", "-", slug)
    slug = re.sub(r"^-+|-+$", "", slug)
    return slug


def utcnow() -> datetime:
    """Return the current UTC datetime, timezone-aware."""
    return datetime.now(tz=timezone.utc)


def truncate_text(text: str, max_chars: int, suffix: str = "...") -> str:
    """
    Truncate text to max_chars, appending suffix if truncated.
    Truncation happens at a word boundary where possible.
    """
    if len(text) <= max_chars:
        return text
    cutoff = max_chars - len(suffix)
    truncated = text[:cutoff]
    # Step back to last whitespace to avoid mid-word cuts
    last_space = truncated.rfind(" ")
    if last_space > cutoff // 2:
        truncated = truncated[:last_space]
    return truncated + suffix


def chunk_list(lst: list[Any], size: int) -> list[list[Any]]:
    """
    Split a list into sub-lists of at most `size` items.
    Example: chunk_list([1,2,3,4,5], 2) → [[1,2],[3,4],[5]]
    """
    if size <= 0:
        raise ValueError("Chunk size must be a positive integer.")
    return [lst[i : i + size] for i in range(0, len(lst), size)]


def safe_json_loads(s: str) -> dict[str, Any] | None:
    """
    Parse a JSON string without raising. Returns None on any parse error.
    Useful for handling untrusted or LLM-generated JSON strings.
    """
    try:
        result = json.loads(s)
        if isinstance(result, dict):
            return result
        return None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def retry_async(
    retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable:
    """
    Async retry decorator with exponential backoff.

    Usage:
        @retry_async(retries=3, delay=0.5, backoff=2.0)
        async def call_external_api(): ...

    Args:
        retries: Maximum number of attempts (including first).
        delay: Initial wait between attempts in seconds.
        backoff: Multiplier applied to delay after each failure.
        exceptions: Tuple of exception types to catch and retry.
    """
    def decorator(func: Callable[..., Coroutine]) -> Callable:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_delay = delay
            last_exc: Exception | None = None
            for attempt in range(1, retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < retries:
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator


def mask_sensitive(data: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """
    Return a shallow copy of data with specified keys redacted.
    Useful for safe logging of dicts that may contain API keys or passwords.

    Example:
        mask_sensitive({"api_key": "sk-123", "user": "bob"}, ["api_key"])
        → {"api_key": "***REDACTED***", "user": "bob"}
    """
    masked = dict(data)
    for key in keys:
        if key in masked:
            masked[key] = "***REDACTED***"
    return masked


def format_cost_usd(amount: float) -> str:
    """
    Format a USD cost for display in logs and UI.
    Example: 0.002431 → "$0.002431", 1.5 → "$1.500000"
    Always shows 6 decimal places for micro-cost visibility.
    """
    return f"${amount:.6f}"

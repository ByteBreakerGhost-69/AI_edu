# products/edu_video/backend/core/cost_tracker.py
"""
Cost tracking for LLM calls and rendering jobs.
Redis-backed, per-job and per-user monthly aggregation.
Budget limits read from config/tier_limits.yaml.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
import yaml
from pydantic import BaseModel
from redis.asyncio import Redis

from core.config import get_settings
from core.utils import format_cost_usd, utcnow

__all__ = [
    "CostTracker",
    "CostSummary",
    "CostLineItem",
]

logger = structlog.get_logger(__name__)
settings = get_settings()

# --- Load tier limits once at module import ---

_TIER_LIMITS_PATH = Path(__file__).parents[4] / "config" / "tier_limits.yaml"


def _load_tier_limits() -> dict[str, Any]:
    """Read budget caps from config/tier_limits.yaml."""
    if not _TIER_LIMITS_PATH.exists():
        logger.warning("cost_tracker.tier_limits_not_found", path=str(_TIER_LIMITS_PATH))
        return {"free": {"monthly_budget_usd": 2.0}, "premium": {"monthly_budget_usd": 50.0}}
    with _TIER_LIMITS_PATH.open() as f:
        return yaml.safe_load(f)


_TIER_LIMITS: dict[str, Any] = _load_tier_limits()


# --- Pydantic models ---

class CostLineItem(BaseModel):
    """Single cost entry within a job."""
    category: str        # "llm" | "render"
    provider: str        # "claude", "grok", "manim", "elevenlabs", etc.
    cost_usd: float
    recorded_at: str     # ISO 8601


class CostSummary(BaseModel):
    """Aggregated cost for a single job."""
    user_id: str
    job_id: str
    llm_cost: float
    render_cost: float
    total_cost: float
    breakdown: list[CostLineItem]


class CostTracker:
    """
    Records and queries cost data in Redis.
    Key schema:
        cost:{user_id}:{job_id}:items   → JSON list of CostLineItem
        cost:{user_id}:{year}:{month}:total → float (monthly aggregate)
    TTL: 90 days for job items; monthly keys expire at end of month + 7d buffer.
    """

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    # --- Internal helpers ---

    def _items_key(self, user_id: str, job_id: str) -> str:
        return f"cost:{user_id}:{job_id}:items"

    def _monthly_key(self, user_id: str, year: int, month: int) -> str:
        return f"cost:{user_id}:{year}:{month:02d}:total"

    async def _append_item(
        self,
        user_id: str,
        job_id: str,
        item: CostLineItem,
    ) -> None:
        """Append a cost line item to the job's Redis list."""
        key = self._items_key(user_id, job_id)
        await self.redis.rpush(key, item.model_dump_json())
        await self.redis.expire(key, 60 * 60 * 24 * 90)  # 90 days TTL

    async def _increment_monthly(
        self,
        user_id: str,
        cost_usd: float,
    ) -> None:
        """Increment this month's running total for a user."""
        now = utcnow()
        key = self._monthly_key(user_id, now.year, now.month)
        await self.redis.incrbyfloat(key, cost_usd)
        # Expire at end of month + 7-day buffer (approx 38 days)
        await self.redis.expire(key, 60 * 60 * 24 * 38)

    # --- Public API ---

    async def record_llm_cost(
        self,
        user_id: str,
        job_id: str,
        provider: str,
        tokens: int,
        cost_usd: float,
    ) -> None:
        """Record cost for an LLM API call."""
        item = CostLineItem(
            category="llm",
            provider=provider,
            cost_usd=cost_usd,
            recorded_at=utcnow().isoformat(),
        )
        await self._append_item(user_id, job_id, item)
        await self._increment_monthly(user_id, cost_usd)
        logger.info(
            "cost.llm_recorded",
            user_id=user_id,
            job_id=job_id,
            provider=provider,
            tokens=tokens,
            cost=format_cost_usd(cost_usd),
        )

    async def record_render_cost(
        self,
        user_id: str,
        job_id: str,
        service: str,
        duration_sec: int,
        cost_usd: float,
    ) -> None:
        """Record cost for a rendering service call (TTS, Manim, Kling, etc.)."""
        item = CostLineItem(
            category="render",
            provider=service,
            cost_usd=cost_usd,
            recorded_at=utcnow().isoformat(),
        )
        await self._append_item(user_id, job_id, item)
        await self._increment_monthly(user_id, cost_usd)
        logger.info(
            "cost.render_recorded",
            user_id=user_id,
            job_id=job_id,
            service=service,
            duration_sec=duration_sec,
            cost=format_cost_usd(cost_usd),
        )

    async def get_job_cost(self, user_id: str, job_id: str) -> CostSummary:
        """Return aggregated cost breakdown for a specific job."""
        key = self._items_key(user_id, job_id)
        raw_items = await self.redis.lrange(key, 0, -1)

        breakdown: list[CostLineItem] = [
            CostLineItem.model_validate_json(r) for r in raw_items
        ]
        llm_cost = sum(i.cost_usd for i in breakdown if i.category == "llm")
        render_cost = sum(i.cost_usd for i in breakdown if i.category == "render")

        return CostSummary(
            user_id=user_id,
            job_id=job_id,
            llm_cost=round(llm_cost, 6),
            render_cost=round(render_cost, 6),
            total_cost=round(llm_cost + render_cost, 6),
            breakdown=breakdown,
        )

    async def get_user_monthly_cost(
        self,
        user_id: str,
        year: int,
        month: int,
    ) -> float:
        """Return total spend (USD) for a user in the given calendar month."""
        key = self._monthly_key(user_id, year, month)
        raw = await self.redis.get(key)
        if raw is None:
            return 0.0
        return round(float(raw), 6)

    async def check_budget_limit(self, user_id: str, tier: str) -> bool:
        """
        Return True if user is within their monthly budget limit.
        Tier limits are read from config/tier_limits.yaml.
        Returns True (within limit) on any lookup error to avoid blocking users.
        """
        try:
            tier_cfg = _TIER_LIMITS.get(tier, {})
            budget: float = tier_cfg.get("monthly_budget_usd", 2.0)
            now = utcnow()
            spent = await self.get_user_monthly_cost(user_id, now.year, now.month)
            within = spent < budget
            logger.info(
                "cost.budget_check",
                user_id=user_id,
                tier=tier,
                spent=format_cost_usd(spent),
                budget=format_cost_usd(budget),
                within_limit=within,
            )
            return within
        except Exception as exc:
            logger.error(
                "cost.budget_check_error",
                user_id=user_id,
                error=str(exc),
            )
            return True  # fail open — don't block user on tracking error

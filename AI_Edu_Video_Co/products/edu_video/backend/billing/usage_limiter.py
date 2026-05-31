# products/edu_video/backend/billing/usage_limiter.py
"""
UsageLimiter: enforces per-user monthly video quota.
Exposes check_video_quota as a FastAPI dependency for layer1/api_gateway.py.
"""

from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from billing.tier_config import FeatureGateResult, tier_config
from core.auth import get_current_user
from core.config import get_settings
from core.database import get_db
from core.utils import utcnow
from models.subscription import Subscription
from models.user import User

__all__ = [
    "UsageLimiter",
    "QuotaStatus",
    "UsageLimitError",
    "usage_limiter",
    "check_video_quota",
    "router",
]

logger = structlog.get_logger(__name__)
settings = get_settings()

router = APIRouter()


# --------------------------------------------------------------------------- #
# Pydantic models                                                              #
# --------------------------------------------------------------------------- #

class QuotaStatus(BaseModel):
    user_id: str
    tier: str
    videos_used: int
    videos_limit: int
    videos_remaining: int
    resets_at: datetime
    is_exceeded: bool
    percentage_used: float


class UsageLimitError(HTTPException):
    """HTTP 402 raised when a user's monthly video quota is exceeded."""

    def __init__(self, quota: QuotaStatus) -> None:
        super().__init__(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "quota_exceeded",
                "message": (
                    f"Monthly video quota exceeded ({quota.videos_used}/{quota.videos_limit}). "
                    "Upgrade to premium for 50 videos/month."
                ),
                "quota_status": quota.model_dump(),
            },
        )


# --------------------------------------------------------------------------- #
# UsageLimiter                                                                 #
# --------------------------------------------------------------------------- #

class UsageLimiter:
    """
    Manages video quota enforcement and monthly usage counters.
    SELECT FOR UPDATE prevents race conditions on concurrent job creation.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(self.__class__.__name__)

    async def get_quota_status(
        self,
        user_id: str,
        db: AsyncSession,
    ) -> QuotaStatus:
        """Return current quota status for a user."""
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            tier = "free"
            videos_used = 0
            videos_limit = settings.FREE_VIDEOS_PER_MONTH
            resets_at = _next_month_start()
        else:
            tier = subscription.tier
            videos_used = subscription.videos_used_this_month
            videos_limit = subscription.videos_limit_per_month
            resets_at = subscription.current_period_end or _next_month_start()

        videos_remaining = max(0, videos_limit - videos_used)
        is_exceeded = videos_used >= videos_limit

        return QuotaStatus(
            user_id=str(user_id),
            tier=tier,
            videos_used=videos_used,
            videos_limit=videos_limit,
            videos_remaining=videos_remaining,
            resets_at=resets_at,
            is_exceeded=is_exceeded,
            percentage_used=round((videos_used / max(videos_limit, 1)) * 100, 1),
        )

    async def increment_usage(
        self,
        user_id: str,
        db: AsyncSession,
    ) -> int:
        """
        Atomically increment videos_used_this_month.
        Uses SELECT FOR UPDATE to prevent double-increments on concurrent requests.
        Returns new count.
        """
        result = await db.execute(
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .with_for_update()
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            subscription = Subscription(
                id=uuid4(),
                user_id=user_id,
                tier="free",
                status="active",
                videos_used_this_month=0,
                videos_limit_per_month=settings.FREE_VIDEOS_PER_MONTH,
            )
            db.add(subscription)

        subscription.videos_used_this_month += 1
        await db.commit()

        self.log.info(
            "usage_incremented",
            user_id=str(user_id),
            new_count=subscription.videos_used_this_month,
            limit=subscription.videos_limit_per_month,
        )
        return subscription.videos_used_this_month

    async def reset_monthly_usage(
        self,
        user_id: str,
        db: AsyncSession,
    ) -> None:
        """Reset counter at the start of a new billing period. Called by webhook_handler."""
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        subscription = result.scalar_one_or_none()
        if subscription:
            subscription.videos_used_this_month = 0
            await db.commit()
            self.log.info("usage_reset", user_id=str(user_id))

    async def check_feature_gate(
        self,
        user_id: str,
        feature: str,
        value: str | None = None,
        db: AsyncSession | None = None,
    ) -> FeatureGateResult:
        """
        Check if user's tier allows a feature/value.
        db is optional — if not provided, defaults to free tier check.
        """
        if db is not None:
            quota = await self.get_quota_status(user_id, db)
            tier = quota.tier
        else:
            tier = "free"
        return tier_config.check_feature(tier, feature, value)


# --------------------------------------------------------------------------- #
# FastAPI dependency                                                           #
# --------------------------------------------------------------------------- #

async def check_video_quota(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QuotaStatus:
    """
    FastAPI dependency for job creation endpoint.
    Raises UsageLimitError (HTTP 402) if quota is exceeded.
    Returns QuotaStatus for use in endpoint logic.
    """
    quota = await usage_limiter.get_quota_status(str(current_user.id), db)
    if quota.is_exceeded:
        raise UsageLimitError(quota)
    return quota


# --------------------------------------------------------------------------- #
# Router                                                                       #
# --------------------------------------------------------------------------- #

@router.get("/quota", summary="Get current user's video quota status")
async def get_quota_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QuotaStatus:
    """Return quota status for the authenticated user."""
    return await usage_limiter.get_quota_status(str(current_user.id), db)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _next_month_start() -> datetime:
    """Return the first moment of next calendar month in UTC."""
    now = utcnow()
    if now.month == 12:
        return now.replace(
            year=now.year + 1, month=1, day=1,
            hour=0, minute=0, second=0, microsecond=0,
        )
    return now.replace(
        month=now.month + 1, day=1,
        hour=0, minute=0, second=0, microsecond=0,
    )


usage_limiter = UsageLimiter()

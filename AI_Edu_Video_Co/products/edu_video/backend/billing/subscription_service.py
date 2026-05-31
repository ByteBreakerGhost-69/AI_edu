# products/edu_video/backend/billing/subscription_service.py
"""
SubscriptionService: manages subscription lifecycle — create, upgrade, cancel, query.
Syncs between Stripe and local DB. All Stripe SDK calls are wrapped in executor
to avoid blocking the event loop.
"""

import asyncio
from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from billing.tier_config import TierFeatures, tier_config
from core.auth import get_current_user
from core.config import get_settings
from core.database import get_db
from core.utils import utcnow
from models.subscription import Subscription
from models.user import User

__all__ = [
    "SubscriptionService",
    "SubscriptionResponse",
    "SubscriptionCreateRequest",
    "SubscriptionUpgradeRequest",
    "SubscriptionCancelRequest",
    "subscription_service",
    "router",
]

logger = structlog.get_logger(__name__)
settings = get_settings()
router = APIRouter()


# --------------------------------------------------------------------------- #
# Pydantic schemas                                                             #
# --------------------------------------------------------------------------- #

class SubscriptionCreateRequest(BaseModel):
    tier: str = "free"
    trial: bool = False


class SubscriptionUpgradeRequest(BaseModel):
    target_tier: str = "premium"
    payment_method_id: str


class SubscriptionCancelRequest(BaseModel):
    cancel_immediately: bool = False


class SubscriptionResponse(BaseModel):
    subscription_id: str
    user_id: str
    tier: str
    status: str
    stripe_subscription_id: str | None
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    videos_used: int
    videos_limit: int
    trial_end: datetime | None
    features: TierFeatures


# --------------------------------------------------------------------------- #
# SubscriptionService                                                          #
# --------------------------------------------------------------------------- #

class SubscriptionService:
    """
    Orchestrates subscription management between the local DB and Stripe.
    Stripe SDK calls run in a thread executor to avoid event-loop blocking.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(self.__class__.__name__)

    async def get_or_create_free(
        self,
        user_id: str,
        db: AsyncSession,
    ) -> Subscription:
        """Return existing subscription or create a free-tier one for new users."""
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
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
            await db.commit()
            self.log.info("free_subscription_created", user_id=str(user_id))

        return subscription

    async def upgrade_to_premium(
        self,
        user_id: str,
        payment_method_id: str,
        db: AsyncSession,
    ) -> SubscriptionResponse:
        """
        Upgrade user to premium via Stripe.

        Flow:
        1. Create or fetch Stripe Customer
        2. Attach + set default payment method
        3. Create Stripe Subscription (with optional trial)
        4. Sync local DB record
        """
        import stripe  # noqa: PLC0415

        user = await db.get(User, user_id)
        if not user:
            raise ValueError(f"User {user_id} not found.")

        subscription = await self.get_or_create_free(user_id, db)
        loop = asyncio.get_event_loop()

        # ---- Stripe customer -------------------------------------------- #
        stripe_customer_id = subscription.stripe_customer_id
        if not stripe_customer_id:
            customer = await loop.run_in_executor(
                None,
                lambda: stripe.Customer.create(
                    api_key=settings.STRIPE_SECRET_KEY,
                    email=user.email,
                    name=user.full_name or user.email,
                    metadata={"user_id": str(user_id)},
                ),
            )
            stripe_customer_id = customer.id
            subscription.stripe_customer_id = stripe_customer_id
            await db.commit()
            self.log.info("stripe_customer_created", customer_id=stripe_customer_id)

        # ---- Attach payment method -------------------------------------- #
        await loop.run_in_executor(
            None,
            lambda: stripe.PaymentMethod.attach(
                payment_method_id,
                customer=stripe_customer_id,
                api_key=settings.STRIPE_SECRET_KEY,
            ),
        )
        await loop.run_in_executor(
            None,
            lambda: stripe.Customer.modify(
                stripe_customer_id,
                invoice_settings={"default_payment_method": payment_method_id},
                api_key=settings.STRIPE_SECRET_KEY,
            ),
        )

        # ---- Create Stripe Subscription --------------------------------- #
        sub_params: dict = {
            "customer": stripe_customer_id,
            "items": [{"price": settings.STRIPE_PREMIUM_PRICE_ID}],
            "payment_settings": {
                "payment_method_types": ["card"],
                "save_default_payment_method": "on_subscription",
            },
            "expand": ["latest_invoice.payment_intent"],
            "metadata": {"user_id": str(user_id)},
            "api_key": settings.STRIPE_SECRET_KEY,
        }
        if settings.SUBSCRIPTION_TRIAL_DAYS > 0:
            sub_params["trial_period_days"] = settings.SUBSCRIPTION_TRIAL_DAYS

        stripe_sub = await loop.run_in_executor(
            None, lambda: stripe.Subscription.create(**sub_params)
        )

        # ---- Sync local DB ---------------------------------------------- #
        subscription.tier = "premium"
        subscription.status = stripe_sub.status
        subscription.stripe_subscription_id = stripe_sub.id
        subscription.videos_limit_per_month = settings.PREMIUM_VIDEOS_PER_MONTH
        subscription.current_period_start = datetime.fromtimestamp(
            stripe_sub.current_period_start, tz=timezone.utc
        )
        subscription.current_period_end = datetime.fromtimestamp(
            stripe_sub.current_period_end, tz=timezone.utc
        )
        if stripe_sub.trial_end:
            subscription.trial_end = datetime.fromtimestamp(
                stripe_sub.trial_end, tz=timezone.utc
            )
        await db.commit()

        self.log.info(
            "upgraded_to_premium",
            user_id=str(user_id),
            stripe_subscription_id=stripe_sub.id,
        )
        return self._to_response(subscription)

    async def cancel_subscription(
        self,
        user_id: str,
        cancel_immediately: bool,
        db: AsyncSession,
    ) -> SubscriptionResponse:
        """
        Cancel premium subscription.
        cancel_immediately=True: cancel now (prorated refund via Stripe).
        cancel_immediately=False: cancel at end of current billing period.
        """
        import stripe  # noqa: PLC0415

        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        subscription = result.scalar_one_or_none()

        if not subscription or not subscription.stripe_subscription_id:
            raise ValueError("No active premium subscription found.")

        loop = asyncio.get_event_loop()

        if cancel_immediately:
            await loop.run_in_executor(
                None,
                lambda: stripe.Subscription.cancel(
                    subscription.stripe_subscription_id,
                    api_key=settings.STRIPE_SECRET_KEY,
                ),
            )
            subscription.status = "cancelled"
            subscription.tier = "free"
            subscription.videos_limit_per_month = settings.FREE_VIDEOS_PER_MONTH
        else:
            await loop.run_in_executor(
                None,
                lambda: stripe.Subscription.modify(
                    subscription.stripe_subscription_id,
                    cancel_at_period_end=True,
                    api_key=settings.STRIPE_SECRET_KEY,
                ),
            )
            subscription.cancel_at_period_end = True

        await db.commit()
        self.log.info(
            "subscription_cancelled",
            user_id=str(user_id),
            immediately=cancel_immediately,
        )
        return self._to_response(subscription)

    async def get_subscription(
        self,
        user_id: str,
        db: AsyncSession,
    ) -> SubscriptionResponse:
        """Return the current subscription for a user (creates free tier if none)."""
        subscription = await self.get_or_create_free(user_id, db)
        return self._to_response(subscription)

    def _to_response(self, subscription: Subscription) -> SubscriptionResponse:
        features = tier_config.get_tier(subscription.tier)
        return SubscriptionResponse(
            subscription_id=str(subscription.id),
            user_id=str(subscription.user_id),
            tier=subscription.tier,
            status=subscription.status,
            stripe_subscription_id=subscription.stripe_subscription_id,
            current_period_start=subscription.current_period_start,
            current_period_end=subscription.current_period_end,
            cancel_at_period_end=subscription.cancel_at_period_end,
            videos_used=subscription.videos_used_this_month,
            videos_limit=subscription.videos_limit_per_month,
            trial_end=subscription.trial_end,
            features=features,
        )


# --------------------------------------------------------------------------- #
# Router endpoints                                                             #
# --------------------------------------------------------------------------- #

@router.get("/subscription", summary="Get current subscription")
async def get_subscription(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubscriptionResponse:
    return await subscription_service.get_subscription(str(current_user.id), db)


@router.post("/subscription/upgrade", summary="Upgrade to premium")
async def upgrade_subscription(
    body: SubscriptionUpgradeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubscriptionResponse:
    return await subscription_service.upgrade_to_premium(
        str(current_user.id), body.payment_method_id, db
    )


@router.post("/subscription/cancel", summary="Cancel subscription")
async def cancel_subscription(
    body: SubscriptionCancelRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubscriptionResponse:
    return await subscription_service.cancel_subscription(
        str(current_user.id), body.cancel_immediately, db
    )


subscription_service = SubscriptionService()

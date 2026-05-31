# products/edu_video/backend/billing/payment_gateway.py
"""
PaymentGateway: creates Stripe Checkout sessions and manages payment methods.
Exposes endpoints for the frontend Stripe Elements integration.
"""

import asyncio
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.auth import get_current_user
from core.config import get_settings
from core.database import get_db
from models.user import User
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models.subscription import Subscription

__all__ = ["PaymentGateway", "payment_gateway", "router"]

logger = structlog.get_logger(__name__)
settings = get_settings()
router = APIRouter()


class CheckoutSessionRequest(BaseModel):
    success_url: str
    cancel_url: str
    trial: bool = True


class CheckoutSessionResponse(BaseModel):
    session_id: str
    checkout_url: str


class SetupIntentResponse(BaseModel):
    client_secret: str
    setup_intent_id: str


class PaymentMethodResponse(BaseModel):
    payment_method_id: str
    brand: str
    last4: str
    exp_month: int
    exp_year: int
    is_default: bool


class PaymentGateway:
    """
    Manages Stripe Checkout sessions and SetupIntents.
    All Stripe SDK calls run in executor to avoid blocking.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(self.__class__.__name__)

    async def create_checkout_session(
        self,
        user: User,
        success_url: str,
        cancel_url: str,
        trial: bool,
        db: AsyncSession,
    ) -> CheckoutSessionResponse:
        """
        Create a Stripe Checkout Session for the premium subscription.
        On completion, Stripe redirects to success_url with session_id param.
        """
        import stripe  # noqa: PLC0415

        loop = asyncio.get_event_loop()

        # Fetch or create Stripe customer
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscription = result.scalar_one_or_none()
        stripe_customer_id = subscription.stripe_customer_id if subscription else None

        if not stripe_customer_id:
            customer = await loop.run_in_executor(
                None,
                lambda: stripe.Customer.create(
                    api_key=settings.STRIPE_SECRET_KEY,
                    email=user.email,
                    name=user.full_name or user.email,
                    metadata={"user_id": str(user.id)},
                ),
            )
            stripe_customer_id = customer.id
            if subscription:
                subscription.stripe_customer_id = stripe_customer_id
                await db.commit()

        session_params: dict = {
            "api_key": settings.STRIPE_SECRET_KEY,
            "customer": stripe_customer_id,
            "mode": "subscription",
            "line_items": [{"price": settings.STRIPE_PREMIUM_PRICE_ID, "quantity": 1}],
            "success_url": success_url + "?session_id={CHECKOUT_SESSION_ID}",
            "cancel_url": cancel_url,
            "metadata": {"user_id": str(user.id)},
            "subscription_data": {
                "metadata": {"user_id": str(user.id)},
            },
        }
        if trial and settings.SUBSCRIPTION_TRIAL_DAYS > 0:
            session_params["subscription_data"]["trial_period_days"] = (
                settings.SUBSCRIPTION_TRIAL_DAYS
            )

        session = await loop.run_in_executor(
            None,
            lambda: stripe.checkout.Session.create(**session_params),
        )

        self.log.info(
            "checkout_session_created",
            user_id=str(user.id),
            session_id=session.id,
        )
        return CheckoutSessionResponse(
            session_id=session.id,
            checkout_url=session.url,
        )

    async def create_setup_intent(
        self, user: User, db: AsyncSession
    ) -> SetupIntentResponse:
        """
        Create a SetupIntent for saving a payment method without an immediate charge.
        Used by the frontend Stripe Elements card update flow.
        """
        import stripe  # noqa: PLC0415

        loop = asyncio.get_event_loop()

        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscription = result.scalar_one_or_none()
        customer_id = subscription.stripe_customer_id if subscription else None

        intent_params: dict = {
            "api_key": settings.STRIPE_SECRET_KEY,
            "payment_method_types": ["card"],
            "metadata": {"user_id": str(user.id)},
        }
        if customer_id:
            intent_params["customer"] = customer_id

        intent = await loop.run_in_executor(
            None, lambda: stripe.SetupIntent.create(**intent_params)
        )
        return SetupIntentResponse(
            client_secret=intent.client_secret,
            setup_intent_id=intent.id,
        )

    async def list_payment_methods(
        self, user: User, db: AsyncSession
    ) -> list[PaymentMethodResponse]:
        """Return all saved payment methods for a user's Stripe customer."""
        import stripe  # noqa: PLC0415

        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscription = result.scalar_one_or_none()
        if not subscription or not subscription.stripe_customer_id:
            return []

        loop = asyncio.get_event_loop()

        customer = await loop.run_in_executor(
            None,
            lambda: stripe.Customer.retrieve(
                subscription.stripe_customer_id,
                expand=["invoice_settings.default_payment_method"],
                api_key=settings.STRIPE_SECRET_KEY,
            ),
        )
        default_pm_id = None
        inv_settings = customer.get("invoice_settings", {})
        if isinstance(inv_settings.get("default_payment_method"), dict):
            default_pm_id = inv_settings["default_payment_method"].get("id")
        elif isinstance(inv_settings.get("default_payment_method"), str):
            default_pm_id = inv_settings["default_payment_method"]

        pms = await loop.run_in_executor(
            None,
            lambda: stripe.PaymentMethod.list(
                customer=subscription.stripe_customer_id,
                type="card",
                api_key=settings.STRIPE_SECRET_KEY,
            ),
        )

        return [
            PaymentMethodResponse(
                payment_method_id=pm.id,
                brand=pm.card.brand,
                last4=pm.card.last4,
                exp_month=pm.card.exp_month,
                exp_year=pm.card.exp_year,
                is_default=(pm.id == default_pm_id),
            )
            for pm in pms.data
        ]


# --------------------------------------------------------------------------- #
# Router endpoints                                                             #
# --------------------------------------------------------------------------- #

@router.post("/checkout", summary="Create Stripe Checkout Session")
async def create_checkout(
    body: CheckoutSessionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CheckoutSessionResponse:
    return await payment_gateway.create_checkout_session(
        user=current_user,
        success_url=body.success_url,
        cancel_url=body.cancel_url,
        trial=body.trial,
        db=db,
    )


@router.post("/setup-intent", summary="Create payment method SetupIntent")
async def create_setup_intent(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SetupIntentResponse:
    return await payment_gateway.create_setup_intent(current_user, db)


@router.get("/payment-methods", summary="List saved payment methods")
async def list_payment_methods(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PaymentMethodResponse]:
    return await payment_gateway.list_payment_methods(current_user, db)


payment_gateway = PaymentGateway()

# products/edu_video/backend/billing/webhook_handler.py
"""
WebhookHandler: processes Stripe webhook events and keeps the local DB
in sync with Stripe subscription state.

All Stripe events arrive at POST /webhooks/stripe.
Signature verification rejects tampered payloads before any DB work.
"""

import asyncio
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from core.config import get_settings
from core.database import AsyncSessionLocal
from core.utils import utcnow
from models.invoice import Invoice
from models.subscription import Subscription
from models.user import User

__all__ = ["WebhookHandler", "webhook_handler", "router"]

logger = structlog.get_logger(__name__)
settings = get_settings()
router = APIRouter()

# Stripe events this handler processes — ignore everything else
_HANDLED_EVENTS = {
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.payment_succeeded",
    "invoice.payment_failed",
    "customer.subscription.trial_will_end",
}


class WebhookHandler:
    """
    Processes Stripe webhook events.
    Each handler method opens its own DB session — webhook processing is
    independent of the request lifecycle.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(self.__class__.__name__)

    async def handle_event(self, event: dict) -> None:
        """Dispatch a verified Stripe event to the appropriate handler."""
        event_type: str = event.get("type", "")
        event_id: str = event.get("id", "")
        log = self.log.bind(event_type=event_type, event_id=event_id)

        if event_type not in _HANDLED_EVENTS:
            log.debug("webhook.event_ignored")
            return

        log.info("webhook.processing")

        try:
            match event_type:
                case "customer.subscription.created":
                    await self._on_subscription_created(event["data"]["object"])
                case "customer.subscription.updated":
                    await self._on_subscription_updated(event["data"]["object"])
                case "customer.subscription.deleted":
                    await self._on_subscription_deleted(event["data"]["object"])
                case "invoice.payment_succeeded":
                    await self._on_payment_succeeded(event["data"]["object"])
                case "invoice.payment_failed":
                    await self._on_payment_failed(event["data"]["object"])
                case "customer.subscription.trial_will_end":
                    await self._on_trial_will_end(event["data"]["object"])
        except Exception as exc:
            log.error("webhook.handler_failed", error=str(exc))
            raise

    # ------------------------------------------------------------------ #
    # Event handlers                                                        #
    # ------------------------------------------------------------------ #

    async def _on_subscription_created(self, stripe_sub: dict) -> None:
        """Sync a newly created Stripe subscription to the local DB."""
        user_id = stripe_sub.get("metadata", {}).get("user_id")
        if not user_id:
            return

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Subscription).where(Subscription.user_id == user_id)
            )
            subscription = result.scalar_one_or_none()
            if not subscription:
                self.log.warning(
                    "webhook.subscription_created_no_local_record",
                    user_id=user_id,
                )
                return

            self._apply_stripe_sub_to_model(subscription, stripe_sub)
            await session.commit()
            self.log.info("webhook.subscription_created_synced", user_id=user_id)

    async def _on_subscription_updated(self, stripe_sub: dict) -> None:
        """
        Sync subscription updates: upgrades, downgrades, cancellations, renewals.
        On renewal (new period start): reset monthly video counter.
        """
        user_id = stripe_sub.get("metadata", {}).get("user_id")
        stripe_sub_id = stripe_sub.get("id")
        if not user_id and not stripe_sub_id:
            return

        async with AsyncSessionLocal() as session:
            # Find by stripe_subscription_id if user_id missing from metadata
            if user_id:
                result = await session.execute(
                    select(Subscription).where(Subscription.user_id == user_id)
                )
            else:
                result = await session.execute(
                    select(Subscription).where(
                        Subscription.stripe_subscription_id == stripe_sub_id
                    )
                )
            subscription = result.scalar_one_or_none()
            if not subscription:
                return

            old_period_end = subscription.current_period_end
            self._apply_stripe_sub_to_model(subscription, stripe_sub)

            # Detect billing period renewal → reset usage counter
            new_period_end = subscription.current_period_end
            if (
                old_period_end
                and new_period_end
                and new_period_end > old_period_end
            ):
                subscription.videos_used_this_month = 0
                self.log.info(
                    "webhook.usage_reset_on_renewal",
                    user_id=str(subscription.user_id),
                )

            await session.commit()
            self.log.info(
                "webhook.subscription_updated",
                user_id=str(subscription.user_id),
                status=stripe_sub.get("status"),
            )

    async def _on_subscription_deleted(self, stripe_sub: dict) -> None:
        """Downgrade user to free tier when their subscription is deleted."""
        stripe_sub_id = stripe_sub.get("id")

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Subscription).where(
                    Subscription.stripe_subscription_id == stripe_sub_id
                )
            )
            subscription = result.scalar_one_or_none()
            if not subscription:
                return

            subscription.tier = "free"
            subscription.status = "cancelled"
            subscription.cancel_at_period_end = False
            subscription.videos_limit_per_month = settings.FREE_VIDEOS_PER_MONTH
            subscription.updated_at = utcnow()
            await session.commit()
            self.log.info(
                "webhook.subscription_deleted_downgraded",
                user_id=str(subscription.user_id),
            )

    async def _on_payment_succeeded(self, invoice: dict) -> None:
        """
        Record a successful payment as an Invoice DB record.
        Also activates subscription if it was past_due.
        """
        subscription_id = invoice.get("subscription")
        stripe_invoice_id = invoice.get("id")
        amount_paid = invoice.get("amount_paid", 0) / 100  # cents → USD
        customer_id = invoice.get("customer")

        async with AsyncSessionLocal() as session:
            # Find local subscription
            result = await session.execute(
                select(Subscription).where(
                    Subscription.stripe_subscription_id == subscription_id
                )
            )
            subscription = result.scalar_one_or_none()

            if subscription and subscription.status == "past_due":
                subscription.status = "active"
                await session.flush()

            # Upsert Invoice record
            existing = await session.execute(
                select(Invoice).where(
                    Invoice.stripe_invoice_id == stripe_invoice_id
                )
            )
            inv = existing.scalar_one_or_none()
            if not inv and subscription:
                from uuid import uuid4  # noqa: PLC0415
                inv = Invoice(
                    id=uuid4(),
                    user_id=subscription.user_id,
                    subscription_id=subscription.id,
                    stripe_invoice_id=stripe_invoice_id,
                    stripe_payment_intent_id=invoice.get("payment_intent"),
                    amount_usd=amount_paid,
                    currency=invoice.get("currency", "usd"),
                    status="paid",
                    description=f"EduVideo Premium - {invoice.get('billing_reason', 'subscription')}",
                    invoice_pdf_url=invoice.get("invoice_pdf"),
                    hosted_invoice_url=invoice.get("hosted_invoice_url"),
                    paid_at=utcnow(),
                )
                session.add(inv)

            await session.commit()
            self.log.info(
                "webhook.payment_succeeded",
                stripe_invoice_id=stripe_invoice_id,
                amount_usd=amount_paid,
            )

    async def _on_payment_failed(self, invoice: dict) -> None:
        """Mark subscription as past_due and update local Invoice record."""
        subscription_id = invoice.get("subscription")

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Subscription).where(
                    Subscription.stripe_subscription_id == subscription_id
                )
            )
            subscription = result.scalar_one_or_none()
            if subscription:
                subscription.status = "past_due"
                subscription.updated_at = utcnow()
                await session.commit()
                self.log.warning(
                    "webhook.payment_failed",
                    user_id=str(subscription.user_id),
                    stripe_subscription_id=subscription_id,
                )

    async def _on_trial_will_end(self, stripe_sub: dict) -> None:
        """Log trial ending soon — placeholder for email notification."""
        user_id = stripe_sub.get("metadata", {}).get("user_id", "unknown")
        trial_end = stripe_sub.get("trial_end")
        self.log.info(
            "webhook.trial_will_end",
            user_id=user_id,
            trial_end=trial_end,
            note="Send trial-ending email notification here.",
        )

    # ------------------------------------------------------------------ #
    # Helpers                                                               #
    # ------------------------------------------------------------------ #

    def _apply_stripe_sub_to_model(
        self, subscription: Subscription, stripe_sub: dict
    ) -> None:
        """Apply Stripe subscription fields to the local Subscription model."""
        subscription.status = stripe_sub.get("status", subscription.status)
        subscription.stripe_subscription_id = stripe_sub.get(
            "id", subscription.stripe_subscription_id
        )
        subscription.cancel_at_period_end = stripe_sub.get(
            "cancel_at_period_end", False
        )

        period_start = stripe_sub.get("current_period_start")
        period_end = stripe_sub.get("current_period_end")
        if period_start:
            subscription.current_period_start = datetime.fromtimestamp(
                period_start, tz=timezone.utc
            )
        if period_end:
            subscription.current_period_end = datetime.fromtimestamp(
                period_end, tz=timezone.utc
            )

        trial_end = stripe_sub.get("trial_end")
        if trial_end:
            subscription.trial_end = datetime.fromtimestamp(
                trial_end, tz=timezone.utc
            )

        # Sync tier from Stripe subscription status
        if stripe_sub.get("status") == "active" and subscription.tier != "premium":
            subscription.tier = "premium"
            subscription.videos_limit_per_month = settings.PREMIUM_VIDEOS_PER_MONTH

        subscription.updated_at = utcnow()


# --------------------------------------------------------------------------- #
# Webhook endpoint                                                             #
# --------------------------------------------------------------------------- #

@router.post("/stripe", summary="Stripe webhook receiver")
async def stripe_webhook(request: Request) -> dict:
    """
    Receive and verify Stripe webhook events.
    Signature verification runs before any business logic.
    Returns 200 immediately after dispatching — Stripe expects fast ACK.
    """
    import stripe  # noqa: PLC0415

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except stripe.error.SignatureVerificationError as exc:
        logger.warning("webhook.signature_invalid", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature.",
        )
    except Exception as exc:
        logger.error("webhook.parse_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload could not be parsed.",
        )

    # Dispatch asynchronously — return 200 to Stripe immediately
    asyncio.create_task(webhook_handler.handle_event(dict(event)))
    return {"received": True}


webhook_handler = WebhookHandler()

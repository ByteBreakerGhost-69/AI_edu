# products/edu_video/backend/models/subscription.py
"""
Subscription ORM model — one per user, tracks tier, Stripe linkage, and quota.
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, ConfigDict, computed_field
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base

if TYPE_CHECKING:
    from models.invoice import Invoice
    from models.user import User

__all__ = [
    "Subscription",
    "SubscriptionCreate",
    "SubscriptionUpdate",
    "SubscriptionResponse",
    "SubscriptionTierUpdate",
]


class Subscription(Base):
    """Per-user subscription record. One-to-one with User."""

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    tier: Mapped[str] = mapped_column(String(32), nullable=False, default="free")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(
        String(256), unique=True, nullable=True
    )
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(
        String(256), unique=True, nullable=True
    )
    current_period_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    videos_used_this_month: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    videos_limit_per_month: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    trial_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # --- Relationships ---
    user: Mapped["User"] = relationship("User", back_populates="subscription")
    invoices: Mapped[list["Invoice"]] = relationship(
        "Invoice", back_populates="subscription", lazy="select"
    )

    __table_args__ = (
        Index("ix_subscriptions_stripe_customer", "stripe_customer_id"),
        Index("ix_subscriptions_tier_status", "tier", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<Subscription id={self.id} user_id={self.user_id} "
            f"tier={self.tier!r} status={self.status!r}>"
        )


# --- Pydantic Schemas ---

class SubscriptionCreate(BaseModel):
    user_id: uuid.UUID
    tier: str = "free"
    stripe_customer_id: Optional[str] = None


class SubscriptionUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tier: Optional[str] = None
    status: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: Optional[bool] = None
    videos_used_this_month: Optional[int] = None
    videos_limit_per_month: Optional[int] = None


class SubscriptionTierUpdate(BaseModel):
    """Used when upgrading/downgrading a subscription tier."""
    model_config = ConfigDict(from_attributes=True)

    tier: str
    videos_limit_per_month: int


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    tier: str
    status: str
    stripe_customer_id: Optional[str]
    stripe_subscription_id: Optional[str]
    current_period_start: Optional[datetime]
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool
    videos_used_this_month: int
    videos_limit_per_month: int
    trial_end: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def is_active(self) -> bool:
        """True when the subscription is in active or trialing state."""
        return self.status in ("active", "trialing")

    @computed_field
    @property
    def videos_remaining(self) -> int:
        """How many video generations remain this month."""
        return max(0, self.videos_limit_per_month - self.videos_used_this_month)

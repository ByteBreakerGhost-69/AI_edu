# products/edu_video/backend/models/invoice.py
"""
Invoice ORM model — mirrors Stripe invoice records for billing history.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base

if TYPE_CHECKING:
    from models.subscription import Subscription
    from models.user import User

__all__ = [
    "Invoice",
    "InvoiceCreate",
    "InvoiceUpdate",
    "InvoiceResponse",
    "InvoiceSummary",
]

VALID_INVOICE_STATUSES = {"draft", "open", "paid", "uncollectible", "void"}


class Invoice(Base):
    """Billing invoice record, synced from Stripe webhook events."""

    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subscription_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    stripe_invoice_id: Mapped[Optional[str]] = mapped_column(
        String(256), unique=True, nullable=True
    )
    stripe_payment_intent_id: Mapped[Optional[str]] = mapped_column(
        String(256), nullable=True
    )
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="usd")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    invoice_pdf_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    hosted_invoice_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    billing_period_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    billing_period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # --- Relationships ---
    user: Mapped["User"] = relationship("User", back_populates="invoices")
    subscription: Mapped[Optional["Subscription"]] = relationship(
        "Subscription", back_populates="invoices"
    )

    __table_args__ = (
        Index("ix_invoices_user_status", "user_id", "status"),
        Index("ix_invoices_stripe_invoice", "stripe_invoice_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Invoice id={self.id} user_id={self.user_id} "
            f"amount={self.amount_usd} status={self.status!r}>"
        )


# --- Pydantic Schemas ---

class InvoiceCreate(BaseModel):
    user_id: uuid.UUID
    subscription_id: Optional[uuid.UUID] = None
    stripe_invoice_id: Optional[str] = None
    amount_usd: Decimal
    status: str
    description: Optional[str] = None


class InvoiceUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: Optional[str] = None
    paid_at: Optional[datetime] = None
    invoice_pdf_url: Optional[str] = None
    hosted_invoice_url: Optional[str] = None
    stripe_payment_intent_id: Optional[str] = None


class InvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    subscription_id: Optional[uuid.UUID]
    stripe_invoice_id: Optional[str]
    stripe_payment_intent_id: Optional[str]
    amount_usd: Decimal
    currency: str
    status: str
    description: Optional[str]
    invoice_pdf_url: Optional[str]
    hosted_invoice_url: Optional[str]
    billing_period_start: Optional[datetime]
    billing_period_end: Optional[datetime]
    paid_at: Optional[datetime]
    created_at: datetime


class InvoiceSummary(BaseModel):
    """Lightweight schema for invoice list endpoints."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    amount_usd: Decimal
    status: str
    paid_at: Optional[datetime]
    billing_period_start: Optional[datetime]
    billing_period_end: Optional[datetime]

# products/edu_video/backend/billing/invoice_service.py
"""
InvoiceService: retrieves, lists, and sends invoice documents.
Invoice records are created by webhook_handler on payment_succeeded events.
"""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user
from core.database import get_db
from core.utils import utcnow
from models.invoice import Invoice, InvoiceSummary
from models.user import User

__all__ = ["InvoiceService", "invoice_service", "router"]

logger = structlog.get_logger(__name__)
router = APIRouter()


class InvoiceListResponse(BaseModel):
    total: int
    page: int
    limit: int
    items: list[InvoiceSummary]


class InvoiceService:
    """Provides invoice retrieval and listing for users and admins."""

    def __init__(self) -> None:
        self.log = structlog.get_logger(self.__class__.__name__)

    async def list_user_invoices(
        self,
        user_id: str,
        db: AsyncSession,
        page: int = 1,
        limit: int = 20,
    ) -> InvoiceListResponse:
        """Return paginated invoice list for a user."""
        offset = (page - 1) * limit

        count_result = await db.execute(
            select(Invoice.id).where(Invoice.user_id == user_id)
        )
        total = len(count_result.all())

        result = await db.execute(
            select(Invoice)
            .where(Invoice.user_id == user_id)
            .order_by(desc(Invoice.created_at))
            .offset(offset)
            .limit(limit)
        )
        invoices = result.scalars().all()

        return InvoiceListResponse(
            total=total,
            page=page,
            limit=limit,
            items=[InvoiceSummary.model_validate(inv) for inv in invoices],
        )

    async def get_invoice(
        self,
        invoice_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> Invoice:
        """
        Return a specific invoice. Enforces user ownership.
        Raises 404 if not found or not owned by this user.
        """
        result = await db.execute(
            select(Invoice)
            .where(Invoice.id == invoice_id)
            .where(Invoice.user_id == user_id)
        )
        invoice = result.scalar_one_or_none()
        if not invoice:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invoice not found.",
            )
        return invoice

    async def send_invoice_email(
        self,
        invoice_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> dict:
        """
        Re-send an invoice to the user's email via Stripe.
        Stripe will deliver the hosted invoice URL by email.
        """
        import asyncio  # noqa: PLC0415
        import stripe  # noqa: PLC0415
        from core.config import get_settings  # noqa: PLC0415

        invoice = await self.get_invoice(invoice_id, user_id, db)
        if not invoice.stripe_invoice_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This invoice is not linked to a Stripe invoice.",
            )

        _settings = get_settings()
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: stripe.Invoice.send_invoice(
                    invoice.stripe_invoice_id,
                    api_key=_settings.STRIPE_SECRET_KEY,
                ),
            )
            self.log.info(
                "invoice_email_sent",
                invoice_id=invoice_id,
                user_id=user_id,
            )
            return {"sent": True, "invoice_id": invoice_id}
        except Exception as exc:
            self.log.error("invoice_email_failed", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to send invoice email: {exc}",
            )


# --------------------------------------------------------------------------- #
# Router endpoints                                                             #
# --------------------------------------------------------------------------- #

@router.get("/invoices", summary="List user invoices")
async def list_invoices(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> InvoiceListResponse:
    return await invoice_service.list_user_invoices(
        str(current_user.id), db, page, limit
    )


@router.get("/invoices/{invoice_id}", summary="Get invoice detail")
async def get_invoice(
    invoice_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from models.invoice import InvoiceResponse  # noqa: PLC0415
    invoice = await invoice_service.get_invoice(invoice_id, str(current_user.id), db)
    return InvoiceResponse.model_validate(invoice)


@router.post("/invoices/{invoice_id}/send", summary="Re-send invoice email")
async def send_invoice(
    invoice_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    return await invoice_service.send_invoice_email(
        invoice_id, str(current_user.id), db
    )


invoice_service = InvoiceService()

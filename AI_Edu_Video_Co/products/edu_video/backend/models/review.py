# products/edu_video/backend/models/review.py
"""
Review ORM model — human review queue record for a generated job.
One review record per job (unique FK on job_id).
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base

if TYPE_CHECKING:
    from models.job import Job
    from models.user import User

__all__ = [
    "Review",
    "ReviewCreate",
    "ReviewUpdate",
    "ReviewResponse",
    "ReviewQueueItem",
]

VALID_REVIEW_STATUSES = {
    "pending", "in_progress", "approved", "rejected", "requires_revision"
}
VALID_PRIORITIES = {"low", "normal", "high", "urgent"}
VALID_TRIGGER_REASONS = {
    "new_subject", "low_confidence", "flagged_content", "user_reported",
    "curriculum_mismatch", "high_cost_anomaly", "manual",
}
VALID_REJECTION_REASONS = {
    "factual_error", "curriculum_mismatch", "poor_quality",
    "inappropriate_content", "other",
}


class Review(Base):
    """
    Human review record for a generated video job.
    Enters the queue automatically when validators flag low confidence
    or when triggered manually by users/admins.
    """

    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    reviewer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    trigger_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    correction_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    correction_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auto_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    assigned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
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
    job: Mapped["Job"] = relationship("Job", back_populates="review")
    reviewer: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="reviews",
        foreign_keys=[reviewer_id],
    )

    __table_args__ = (
        Index("ix_reviews_status_priority", "status", "priority"),
        Index("ix_reviews_reviewer_status", "reviewer_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<Review id={self.id} job_id={self.job_id} "
            f"status={self.status!r} priority={self.priority!r}>"
        )


# --- Pydantic Schemas ---

class ReviewCreate(BaseModel):
    job_id: uuid.UUID
    trigger_reason: str
    priority: str = "normal"
    confidence_score: Optional[float] = None

    @field_validator("trigger_reason")
    @classmethod
    def valid_trigger(cls, v: str) -> str:
        if v not in VALID_TRIGGER_REASONS:
            raise ValueError(f"trigger_reason must be one of {VALID_TRIGGER_REASONS}")
        return v

    @field_validator("priority")
    @classmethod
    def valid_priority(cls, v: str) -> str:
        if v not in VALID_PRIORITIES:
            raise ValueError(f"priority must be one of {VALID_PRIORITIES}")
        return v

    @field_validator("confidence_score")
    @classmethod
    def valid_confidence(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError("confidence_score must be between 0.0 and 1.0")
        return v


class ReviewUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    reviewer_id: Optional[uuid.UUID] = None
    status: Optional[str] = None
    reviewer_notes: Optional[str] = None
    rejection_reason: Optional[str] = None
    correction_applied: Optional[bool] = None
    correction_notes: Optional[str] = None
    assigned_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ReviewResponse(BaseModel):
    """Full review detail, includes denormalized job info for display."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    reviewer_id: Optional[uuid.UUID]
    status: str
    priority: str
    trigger_reason: str
    reviewer_notes: Optional[str]
    rejection_reason: Optional[str]
    correction_applied: bool
    correction_notes: Optional[str]
    auto_approved: bool
    confidence_score: Optional[float]
    assigned_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    # Denormalized from job — populated by endpoint
    job_title: Optional[str] = None
    job_subject: Optional[str] = None

    @classmethod
    def from_orm_with_job(cls, review: "Review") -> "ReviewResponse":
        """Build response and inject job title/subject from loaded relationship."""
        obj = cls.model_validate(review)
        if review.job:
            obj.job_title = review.job.title
            obj.job_subject = review.job.subject
        return obj


class ReviewQueueItem(BaseModel):
    """Lightweight schema for the admin review queue list view."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    status: str
    priority: str
    trigger_reason: str
    confidence_score: Optional[float]
    created_at: datetime
    reviewer_id: Optional[uuid.UUID]

# products/edu_video/backend/models/feedback.py
"""
Feedback ORM model — user-submitted feedback on a job or specific scene.
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base

if TYPE_CHECKING:
    from models.job import Job
    from models.user import User

__all__ = [
    "Feedback",
    "FeedbackCreate",
    "FeedbackUpdate",
    "FeedbackResponse",
]

VALID_FEEDBACK_TYPES = {
    "incorrect_content",
    "poor_animation",
    "audio_issue",
    "wrong_difficulty",
    "curriculum_mismatch",
    "other",
}


class Feedback(Base):
    """User-submitted feedback, optionally scoped to a specific scene."""

    __tablename__ = "feedbacks"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scene_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    feedback_type: Mapped[str] = mapped_column(String(64), nullable=False)
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # --- Relationships ---
    job: Mapped["Job"] = relationship("Job", back_populates="feedbacks")
    user: Mapped["User"] = relationship("User", back_populates="feedbacks")

    __table_args__ = (
        Index("ix_feedbacks_job_type", "job_id", "feedback_type"),
        Index("ix_feedbacks_resolved", "is_resolved"),
    )

    def __repr__(self) -> str:
        return (
            f"<Feedback id={self.id} job_id={self.job_id} "
            f"type={self.feedback_type!r} resolved={self.is_resolved}>"
        )


# --- Pydantic Schemas ---

class FeedbackCreate(BaseModel):
    job_id: uuid.UUID
    scene_index: Optional[int] = None
    feedback_type: str
    rating: Optional[int] = None
    comment: Optional[str] = None

    @field_validator("rating")
    @classmethod
    def rating_range(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 5):
            raise ValueError("Rating must be between 1 and 5.")
        return v

    @field_validator("feedback_type")
    @classmethod
    def valid_type(cls, v: str) -> str:
        if v not in VALID_FEEDBACK_TYPES:
            raise ValueError(f"feedback_type must be one of {VALID_FEEDBACK_TYPES}")
        return v


class FeedbackUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    is_resolved: Optional[bool] = None
    resolved_at: Optional[datetime] = None


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    user_id: uuid.UUID
    scene_index: Optional[int]
    feedback_type: str
    rating: Optional[int]
    comment: Optional[str]
    is_resolved: bool
    resolved_at: Optional[datetime]
    created_at: datetime

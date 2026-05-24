# products/edu_video/backend/models/job.py
"""
Job ORM model — represents a single video generation request.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, ConfigDict, computed_field
from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base

if TYPE_CHECKING:
    from models.feedback import Feedback
    from models.review import Review
    from models.scene import Scene
    from models.user import User

__all__ = [
    "Job",
    "JobCreate",
    "JobUpdate",
    "JobResponse",
    "JobStatusUpdate",
]

VALID_SUBJECTS = {
    "mathematics", "physics", "chemistry", "biology", "history",
    "geography", "economics", "literature", "computer_science", "language",
}
VALID_CURRICULA = {"IB", "Cambridge", "AP", "general"}
VALID_DIFFICULTIES = {"beginner", "intermediate", "advanced"}
VALID_STATUSES = {
    "pending", "queued", "orchestrating", "rendering", "review", "done", "failed"
}


class Job(Base):
    """Single video generation job, owned by a user."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str] = mapped_column(String(64), nullable=False)
    curriculum: Mapped[str] = mapped_column(String(32), nullable=False)
    difficulty_level: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    input_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    input_image_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False, default=Decimal("0")
    )
    duration_seconds: Mapped[Optional[int]] = mapped_column(nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Relationships ---
    user: Mapped["User"] = relationship("User", back_populates="jobs")
    scenes: Mapped[list["Scene"]] = relationship(
        "Scene",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="Scene.scene_index",
        lazy="select",
    )
    feedbacks: Mapped[list["Feedback"]] = relationship(
        "Feedback", back_populates="job", lazy="select"
    )
    review: Mapped[Optional["Review"]] = relationship(
        "Review", back_populates="job", uselist=False, lazy="select"
    )

    __table_args__ = (
        Index("ix_jobs_user_status", "user_id", "status"),
        Index("ix_jobs_subject_curriculum", "subject", "curriculum"),
    )

    def __repr__(self) -> str:
        return (
            f"<Job id={self.id} title={self.title!r} "
            f"status={self.status!r} subject={self.subject!r}>"
        )


# --- Pydantic Schemas ---

class JobCreate(BaseModel):
    title: str
    subject: str
    curriculum: str
    difficulty_level: str
    language: str = "en"
    input_text: Optional[str] = None
    input_image_url: Optional[str] = None


class JobUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: Optional[str] = None
    error_message: Optional[str] = None
    total_cost_usd: Optional[Decimal] = None
    duration_seconds: Optional[int] = None
    video_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    completed_at: Optional[datetime] = None


class JobStatusUpdate(BaseModel):
    """Minimal update used by Celery workers to advance job status."""
    model_config = ConfigDict(from_attributes=True)

    status: str


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    subject: str
    curriculum: str
    difficulty_level: str
    language: str
    input_text: Optional[str]
    input_image_url: Optional[str]
    status: str
    error_message: Optional[str]
    total_cost_usd: Decimal
    duration_seconds: Optional[int]
    video_url: Optional[str]
    thumbnail_url: Optional[str]
    metadata: Optional[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
    scene_count: int = 0  # injected by endpoint after loading scenes

    @classmethod
    def from_orm_with_scenes(cls, job: "Job") -> "JobResponse":
        """Build response and inject scene_count from loaded relationship."""
        obj = cls.model_validate(job)
        obj.scene_count = len(job.scenes)
        return obj

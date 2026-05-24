# products/edu_video/backend/models/scene.py
"""
Scene ORM model — individual rendered segments within a Job.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base

if TYPE_CHECKING:
    from models.job import Job

__all__ = [
    "Scene",
    "SceneCreate",
    "SceneUpdate",
    "SceneResponse",
    "SceneCostUpdate",
]

VALID_RENDERER_TYPES = {
    "manim", "lottie", "flux_sdxl", "kling",
    "timeline", "diagram", "graph", "code",
}
VALID_SCENE_STATUSES = {"pending", "rendering", "done", "failed"}


class Scene(Base):
    """One rendered segment (narration + visual + audio) within a job."""

    __tablename__ = "scenes"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scene_index: Mapped[int] = mapped_column(nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    narration_text: Mapped[str] = mapped_column(Text, nullable=False)
    visual_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    renderer_type: Mapped[str] = mapped_column(String(32), nullable=False)
    animation_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    audio_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    subtitle_srt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    render_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    llm_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False, default=Decimal("0")
    )
    render_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False, default=Decimal("0")
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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
    job: Mapped["Job"] = relationship("Job", back_populates="scenes")

    __table_args__ = (
        UniqueConstraint("job_id", "scene_index", name="uq_scene_job_index"),
        Index("ix_scenes_job_status", "job_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<Scene id={self.id} job_id={self.job_id} "
            f"index={self.scene_index} status={self.status!r}>"
        )


# --- Pydantic Schemas ---

class SceneCreate(BaseModel):
    job_id: uuid.UUID
    scene_index: int
    narration_text: str
    visual_description: Optional[str] = None
    renderer_type: str
    render_metadata: Optional[dict[str, Any]] = None


class SceneUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    animation_url: Optional[str] = None
    audio_url: Optional[str] = None
    subtitle_srt: Optional[str] = None
    duration_seconds: Optional[float] = None
    status: Optional[str] = None
    error_message: Optional[str] = None
    render_metadata: Optional[dict[str, Any]] = None


class SceneCostUpdate(BaseModel):
    """Used by cost_tracker to update per-scene costs after rendering."""
    model_config = ConfigDict(from_attributes=True)

    llm_cost_usd: Optional[Decimal] = None
    render_cost_usd: Optional[Decimal] = None


class SceneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    scene_index: int
    title: Optional[str]
    narration_text: str
    visual_description: Optional[str]
    renderer_type: str
    animation_url: Optional[str]
    audio_url: Optional[str]
    subtitle_srt: Optional[str]
    duration_seconds: Optional[float]
    status: str
    render_metadata: Optional[dict[str, Any]]
    llm_cost_usd: Decimal
    render_cost_usd: Decimal
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime

# products/edu_video/backend/models/user.py
"""
User ORM model and Pydantic schemas.
Root model — no FK dependencies on other domain models.
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import structlog
from pydantic import BaseModel, ConfigDict, EmailStr, field_validator
from sqlalchemy import Boolean, DateTime, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base

if TYPE_CHECKING:
    from models.feedback import Feedback
    from models.invoice import Invoice
    from models.job import Job
    from models.review import Review
    from models.subscription import Subscription

logger = structlog.get_logger(__name__)

__all__ = [
    "User",
    "UserCreate",
    "UserUpdate",
    "UserResponse",
]


class User(Base):
    """Platform user. Roles: free | premium | admin."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(320), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(1024), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="free")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
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
    jobs: Mapped[list["Job"]] = relationship(
        "Job", back_populates="user", cascade="all, delete-orphan", lazy="select"
    )
    subscription: Mapped[Optional["Subscription"]] = relationship(
        "Subscription", back_populates="user", uselist=False, lazy="select"
    )
    feedbacks: Mapped[list["Feedback"]] = relationship(
        "Feedback", back_populates="user", lazy="select"
    )
    invoices: Mapped[list["Invoice"]] = relationship(
        "Invoice", back_populates="user", lazy="select"
    )
    reviews: Mapped[list["Review"]] = relationship(
        "Review", back_populates="reviewer", foreign_keys="Review.reviewer_id", lazy="select"
    )

    __table_args__ = (
        Index("ix_users_email_active", "email", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role!r}>"


# --- Pydantic Schemas ---

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v


class UserUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: Optional[str]
    role: str
    is_active: bool
    is_verified: bool
    avatar_url: Optional[str]
    created_at: datetime
    updated_at: datetime
    tier: Optional[str] = None  # populated from subscription.tier if loaded

    @classmethod
    def from_orm_with_tier(cls, user: "User") -> "UserResponse":
        """Build response and inject tier from loaded subscription."""
        obj = cls.model_validate(user)
        if user.subscription:
            obj.tier = user.subscription.tier
        else:
            obj.tier = "free"
        return obj

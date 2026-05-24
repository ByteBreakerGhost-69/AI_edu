# products/edu_video/backend/layer1_input/schemas.py
"""
All Pydantic v2 request/response schemas for Layer 1 (Input Processing).
No internal project imports — this is the base schema file.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "SubjectEnum",
    "CurriculumEnum",
    "DifficultyEnum",
    "VideoJobRequest",
    "VideoJobResponse",
    "JobStatusResponse",
    "JobListResponse",
    "SubjectDetectionResult",
    "CurriculumSelectionResult",
    "ValidationResult",
    "ValidationError",
    "QueuedJob",
    "QueueStats",
    "ParsedImageContent",
]


class SubjectEnum(StrEnum):
    mathematics = "mathematics"
    physics = "physics"
    chemistry = "chemistry"
    biology = "biology"
    history = "history"
    geography = "geography"
    economics = "economics"
    literature = "literature"
    computer_science = "computer_science"
    language = "language"


class CurriculumEnum(StrEnum):
    IB = "IB"
    Cambridge = "Cambridge"
    AP = "AP"
    general = "general"


class DifficultyEnum(StrEnum):
    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"


class VideoJobRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    subject: Optional[SubjectEnum] = None
    curriculum: Optional[CurriculumEnum] = None
    difficulty_level: DifficultyEnum = DifficultyEnum.intermediate
    language: str = Field(default="en", pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    input_text: Optional[str] = Field(default=None, min_length=20)
    input_image_url: Optional[str] = None

    @model_validator(mode="after")
    def at_least_one_input(self) -> "VideoJobRequest":
        if self.input_text is None and self.input_image_url is None:
            raise ValueError(
                "At least one of input_text or input_image_url must be provided."
            )
        return self


class VideoJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: uuid.UUID
    status: str
    title: str
    subject: str
    curriculum: str
    estimated_duration_seconds: int
    queue_position: int
    created_at: datetime
    message: str


class JobStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    updated_at: datetime
    error_message: Optional[str] = None
    queue_position: Optional[int] = None


class JobListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    subject: str
    curriculum: str
    status: str
    created_at: datetime
    video_url: Optional[str] = None
    thumbnail_url: Optional[str] = None


class JobListResponse(BaseModel):
    total: int
    page: int
    limit: int
    items: list[JobListItem]


class SubjectDetectionResult(BaseModel):
    detected_subject: SubjectEnum
    confidence: float = Field(..., ge=0.0, le=1.0)
    alternative_subjects: list[SubjectEnum] = Field(default_factory=list)
    reasoning: str


class CurriculumSelectionResult(BaseModel):
    selected_curriculum: CurriculumEnum
    reasoning: str
    key_standards: list[str] = Field(default_factory=list)


class ValidationError(BaseModel):
    field: str
    code: str
    message: str


class ValidationResult(BaseModel):
    is_valid: bool
    errors: list[ValidationError] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sanitized_input: Optional[str] = None


class QueuedJob(BaseModel):
    job_id: uuid.UUID
    user_id: uuid.UUID
    queue_name: str
    position: int
    enqueued_at: datetime


class QueueStats(BaseModel):
    total_jobs: int
    priority_jobs: int
    standard_jobs: int
    oldest_job_age_seconds: Optional[float] = None


class ParsedImageContent(BaseModel):
    extracted_text: str
    detected_subject: Optional[SubjectEnum] = None
    image_type: str  # "textbook_page"|"handwritten_notes"|"diagram"|"equation"|"mixed"
    confidence: float = Field(..., ge=0.0, le=1.0)
    additional_context: Optional[str] = None

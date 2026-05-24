# products/edu_video/backend/layer1_input/api_gateway.py
"""
Layer 1 API Gateway: entry point for video job creation and management.
Handles auth gating, quota checks, LLM-based detection, validation, and queuing.
"""

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user, require_role
from core.database import get_db, get_redis
from layer1_input.curriculum_selector import curriculum_selector
from layer1_input.queue_service import QueueFullError, queue_service
from layer1_input.schemas import (
    CurriculumEnum,
    JobListResponse,
    JobStatusResponse,
    SubjectEnum,
    VideoJobRequest,
    VideoJobResponse,
    JobListItem,
)
from layer1_input.subject_detector import subject_detector
from layer1_input.validator import job_validator
from layer1_input.vision_parser import VisionParserError, vision_parser
from models.job import Job, JobCreate
from models.subscription import Subscription
from models.user import User

__all__ = ["router"]

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Statuses that allow a job to be cancelled
_CANCELLABLE_STATUSES = {"pending", "queued", "failed"}

# Rough estimate: 60s per scene, ~5 scenes per job
_ESTIMATED_SECONDS_PER_JOB = 300


# --- Exception handlers ---

@router.exception_handler(QueueFullError)
async def queue_full_handler(request, exc: QueueFullError):
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Queue is full. Please try again in a few minutes.",
    )


# --- Endpoints ---

@router.post("/create", status_code=status.HTTP_201_CREATED, response_model=VideoJobResponse)
async def create_job(
    body: VideoJobRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> VideoJobResponse:
    """
    Submit a new video generation job.

    Flow:
    1. Quota check → 2. Image parse (if needed) → 3. Subject detect →
    4. Curriculum select → 5. Validate → 6. DB insert → 7. Enqueue
    """
    log = logger.bind(user_id=str(current_user.id))

    # 1. Quota check
    subscription = await _load_subscription(db, current_user.id)
    if (
        subscription.videos_used_this_month
        >= subscription.videos_limit_per_month
    ):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "Monthly video quota exceeded. "
                "Upgrade to premium to generate more videos."
            ),
        )

    # 2. Image parsing
    parsed_image = None
    if body.input_image_url:
        try:
            parsed_image = await vision_parser.parse_image_content(
                image_url=body.input_image_url,
                job_id="pre-create",
            )
        except VisionParserError as exc:
            log.warning("api_gateway.vision_parse_failed", error=str(exc))
            # Non-fatal: continue without parsed image

    # Determine effective text for detection/selection
    effective_text = body.input_text or ""
    if parsed_image and parsed_image.extracted_text:
        effective_text = f"{effective_text}\n{parsed_image.extracted_text}".strip()

    # 3. Subject detection
    detected_subject = body.subject
    if detected_subject is None:
        try:
            detection = await subject_detector.detect_subject(
                text=effective_text,
                parsed_image=parsed_image,
                job_id="pre-create",
            )
            detected_subject = detection.detected_subject
        except Exception as exc:
            log.warning("api_gateway.subject_detect_failed", error=str(exc))
            detected_subject = SubjectEnum.mathematics

    # 4. Curriculum selection
    selected_curriculum = body.curriculum
    if selected_curriculum is None:
        try:
            curriculum_result = await curriculum_selector.select_curriculum(
                subject=detected_subject,
                text=effective_text,
                language=body.language,
                job_id="pre-create",
            )
            selected_curriculum = curriculum_result.selected_curriculum
        except Exception as exc:
            log.warning("api_gateway.curriculum_select_failed", error=str(exc))
            selected_curriculum = CurriculumEnum.general

    # 5. Validation
    enriched_request = body.model_copy(
        update={"subject": detected_subject, "curriculum": selected_curriculum}
    )
    validation = await job_validator.validate_job_input(
        request=enriched_request,
        user=current_user,
        parsed_image=parsed_image,
    )
    if not validation.is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[e.model_dump() for e in validation.errors],
        )

    # 6. Create Job DB record
    job = Job(
        user_id=current_user.id,
        title=body.title,
        subject=detected_subject.value,
        curriculum=selected_curriculum.value,
        difficulty_level=body.difficulty_level.value,
        language=body.language,
        input_text=validation.sanitized_input or body.input_text,
        input_image_url=body.input_image_url,
        status="queued",
        created_at=datetime.now(tz=timezone.utc),
        updated_at=datetime.now(tz=timezone.utc),
    )
    db.add(job)
    await db.flush()  # assigns job.id before enqueue

    log = log.bind(job_id=str(job.id))

    # 7. Increment quota
    subscription.videos_used_this_month += 1
    await db.flush()

    # 8. Enqueue (Redis failure must not roll back DB)
    queued = None
    try:
        queued = await queue_service.enqueue_job(job=job, user=current_user, redis=redis)
    except QueueFullError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Queue is full. Please try again in a few minutes.",
        )
    except Exception as exc:
        log.error("api_gateway.enqueue_failed", error=str(exc))
        # Job stays in DB with status=queued; worker can pick it up via DB poll

    await db.commit()
    log.info("api_gateway.job_created")

    return VideoJobResponse(
        job_id=job.id,
        status=job.status,
        title=job.title,
        subject=job.subject,
        curriculum=job.curriculum,
        estimated_duration_seconds=_ESTIMATED_SECONDS_PER_JOB,
        queue_position=queued.position if queued else 0,
        created_at=job.created_at,
        message=(
            "Job created successfully. "
            f"Warnings: {validation.warnings}" if validation.warnings
            else "Job created successfully."
        ),
    )


@router.get("/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status(
    job_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> JobStatusResponse:
    """Return current status for a job owned by the authenticated user."""
    job = await _get_owned_job(db, job_id, current_user.id)

    queue_position: int | None = None
    if job.status == "queued":
        try:
            queue_position = await queue_service.get_queue_position(
                str(job.id), redis
            )
        except Exception:
            pass

    return JobStatusResponse(
        id=job.id,
        status=job.status,
        updated_at=job.updated_at,
        error_message=job.error_message,
        queue_position=queue_position,
    )


@router.get("/", response_model=JobListResponse)
async def list_jobs(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
) -> JobListResponse:
    """Return a paginated list of the authenticated user's jobs."""
    query = select(Job).where(Job.user_id == current_user.id)
    if status:
        query = query.where(Job.status == status)

    # Total count
    count_query = select(Job.id).where(Job.user_id == current_user.id)
    if status:
        count_query = count_query.where(Job.status == status)
    total_result = await db.execute(count_query)
    total = len(total_result.all())

    # Paginated fetch
    offset = (page - 1) * limit
    query = (
        query.order_by(Job.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    jobs = result.scalars().all()

    return JobListResponse(
        total=total,
        page=page,
        limit=limit,
        items=[JobListItem.model_validate(j) for j in jobs],
    )


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_job(
    job_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> None:
    """
    Cancel a job (soft delete — sets status='cancelled').
    Only allowed for jobs in: pending, queued, failed.
    """
    job = await _get_owned_job(db, job_id, current_user.id)

    if job.status not in _CANCELLABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot cancel a job with status '{job.status}'. "
                f"Only {_CANCELLABLE_STATUSES} jobs can be cancelled."
            ),
        )

    job.status = "cancelled"
    job.updated_at = datetime.now(tz=timezone.utc)

    try:
        await queue_service.remove_from_queue(str(job.id), redis)
    except Exception as exc:
        logger.warning(
            "api_gateway.queue_remove_failed",
            job_id=str(job.id),
            error=str(exc),
        )

    await db.commit()
    logger.info("api_gateway.job_cancelled", job_id=str(job.id))


# --- Helpers ---

async def _load_subscription(
    db: AsyncSession, user_id
) -> Subscription:
    """Load subscription for user, creating a default free one if missing."""
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    )
    subscription = result.scalar_one_or_none()
    if subscription is None:
        subscription = Subscription(
            user_id=user_id,
            tier="free",
            status="active",
            videos_used_this_month=0,
            videos_limit_per_month=3,
        )
        db.add(subscription)
        await db.flush()
    return subscription


async def _get_owned_job(
    db: AsyncSession, job_id: UUID, user_id
) -> Job:
    """Fetch a job by ID, enforcing ownership. Raises 404 if not found or not owned."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None or job.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found.",
        )
    return job

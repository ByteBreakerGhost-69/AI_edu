# products/edu_video/backend/layer6_delivery/review/approval_service.py
"""
ApprovalService: processes human reviewer decisions (approve/reject) on
queued videos. Updates DB, triggers delivery or correction accordingly.
"""

import structlog
from pydantic import BaseModel
from sqlalchemy import select

from core.database import AsyncSessionLocal
from core.utils import utcnow
from models.job import Job
from models.review import Review

__all__ = ["ApprovalService", "ApprovalDecision", "ApprovalResult", "approval_service"]

logger = structlog.get_logger(__name__)

_VALID_STATUSES = {"approved", "rejected", "requires_revision"}
_VALID_REJECTION_REASONS = {
    "factual_error",
    "curriculum_mismatch",
    "poor_quality",
    "inappropriate_content",
    "other",
}


class ApprovalDecision(BaseModel):
    review_id: str
    decision: str                    # "approved" | "rejected" | "requires_revision"
    reviewer_id: str
    reviewer_notes: str | None = None
    rejection_reason: str | None = None
    correction_notes: str | None = None


class ApprovalResult(BaseModel):
    review_id: str
    job_id: str
    decision: str
    job_status_updated_to: str
    correction_logged: bool


class ApprovalService:
    """
    Handles reviewer approve/reject decisions.
    On approve: updates job to "done", records completion.
    On reject: updates job to "failed", logs correction, triggers partial regen if applicable.
    On requires_revision: keeps job in "review", queues for content correction.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(__name__)

    async def process_decision(self, decision: ApprovalDecision) -> ApprovalResult:
        """
        Apply a reviewer's approval decision.
        Updates Review and Job DB records. Triggers downstream actions.
        """
        log = self.log.bind(
            review_id=decision.review_id,
            decision=decision.decision,
            reviewer_id=decision.reviewer_id,
        )
        log.info("approval_service.processing")

        if decision.decision not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid decision '{decision.decision}'. "
                f"Must be one of: {_VALID_STATUSES}"
            )

        correction_logged = False
        job_id: str = ""
        new_job_status: str = "review"

        async with AsyncSessionLocal() as session:
            # Load review record
            result = await session.execute(
                select(Review).where(Review.id == decision.review_id)
            )
            review = result.scalar_one_or_none()
            if not review:
                raise ValueError(f"Review {decision.review_id} not found.")

            job_id = str(review.job_id)
            job = await session.get(Job, job_id)

            # ---- Apply decision ---------------------------------------- #
            review.status = decision.decision
            review.reviewer_id = decision.reviewer_id
            review.reviewer_notes = decision.reviewer_notes
            review.completed_at = utcnow()
            review.updated_at = utcnow()

            if decision.decision == "approved":
                review.correction_applied = False
                new_job_status = "done"
                if job:
                    job.status = "done"
                    job.completed_at = utcnow()
                    job.updated_at = utcnow()
                log.info("approval_service.approved", job_id=job_id)

            elif decision.decision == "rejected":
                review.rejection_reason = decision.rejection_reason or "other"
                review.correction_notes = decision.correction_notes
                review.correction_applied = bool(decision.correction_notes)
                new_job_status = "failed"
                if job:
                    job.status = "failed"
                    job.error_message = (
                        f"Rejected by reviewer: {decision.rejection_reason}"
                    )
                    job.updated_at = utcnow()
                log.info(
                    "approval_service.rejected",
                    job_id=job_id,
                    reason=decision.rejection_reason,
                )

            elif decision.decision == "requires_revision":
                review.correction_notes = decision.correction_notes
                new_job_status = "review"
                if job:
                    job.updated_at = utcnow()
                log.info("approval_service.requires_revision", job_id=job_id)

            await session.commit()

        # ---- Log correction for rejected/revision ----------------------- #
        if decision.decision in ("rejected", "requires_revision") and decision.correction_notes:
            try:
                from layer6_delivery.review.correction_log import correction_log_service  # noqa
                await correction_log_service.log_correction(
                    job_id=job_id,
                    scene_index=None,
                    reported_error=decision.correction_notes,
                    error_type=decision.rejection_reason or "reviewer_correction",
                )
                correction_logged = True
                log.info("approval_service.correction_logged")
            except Exception as exc:
                log.error("approval_service.correction_log_failed", error=str(exc))

        return ApprovalResult(
            review_id=decision.review_id,
            job_id=job_id,
            decision=decision.decision,
            job_status_updated_to=new_job_status,
            correction_logged=correction_logged,
        )

    async def auto_approve(
        self,
        job_id: str,
        confidence_score: float,
    ) -> ApprovalResult:
        """
        Auto-approve a job that exceeded the quality threshold.
        Creates a synthetic Review record marked auto_approved=True.
        """
        log = self.log.bind(job_id=job_id, confidence_score=confidence_score)

        async with AsyncSessionLocal() as session:
            # Check if review record exists for this job
            result = await session.execute(
                select(Review).where(Review.job_id == job_id)
            )
            review = result.scalar_one_or_none()

            if review:
                review.status = "approved"
                review.auto_approved = True
                review.confidence_score = confidence_score
                review.completed_at = utcnow()
                review.updated_at = utcnow()
                review_id = str(review.id)
            else:
                # No explicit review record — just update job
                review_id = "auto"

            job = await session.get(Job, job_id)
            if job:
                job.status = "done"
                job.completed_at = utcnow()
                job.updated_at = utcnow()

            await session.commit()

        log.info("approval_service.auto_approved")
        return ApprovalResult(
            review_id=review_id,
            job_id=job_id,
            decision="approved",
            job_status_updated_to="done",
            correction_logged=False,
        )


approval_service = ApprovalService()

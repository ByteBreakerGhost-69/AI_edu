# products/edu_video/backend/layer6_delivery/feedback_service.py
"""
FeedbackService: stores user feedback on delivered videos and triggers
downstream actions (partial regen, review queue, correction log).
"""

import json
from uuid import uuid4

import structlog
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.utils import utcnow
from models.feedback import Feedback
from models.job import Job

__all__ = ["FeedbackService", "FeedbackRequest", "FeedbackResult", "feedback_service"]

logger = structlog.get_logger(__name__)

AUTO_REGEN_CONDITIONS: dict[str, bool] = {
    "poor_animation":       True,
    "audio_issue":          True,
    "incorrect_content":    False,
    "wrong_difficulty":     False,
    "curriculum_mismatch":  False,
    "other":                False,
}

AUTO_REVIEW_CONDITIONS: dict[str, bool] = {
    "incorrect_content":    True,
    "curriculum_mismatch":  True,
    "wrong_difficulty":     False,
    "poor_animation":       False,
    "audio_issue":          False,
    "other":                False,
}

_ACTION_MESSAGES: dict[str, str] = {
    "partial_regen":    "We're regenerating the affected scene. Check back in a few minutes.",
    "review_queue":     "Your feedback has been flagged for expert review.",
    "correction_log":   "Thank you — we've logged this for content accuracy review.",
    "none":             "Thank you for your feedback.",
}


class FeedbackRequest(BaseModel):
    job_id: str
    scene_index: int | None = None
    feedback_type: str
    rating: int | None = None
    comment: str | None = None


class FeedbackResult(BaseModel):
    feedback_id: str
    action_triggered: str
    message: str


class FeedbackService:
    """
    Receives user feedback, persists it, and routes to the appropriate
    downstream action without blocking the API response.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(__name__)

    async def submit_feedback(
        self,
        feedback_request: FeedbackRequest,
        user_id: str,
        db_session: AsyncSession,
    ) -> FeedbackResult:
        """
        Validate ownership, store feedback in DB, determine and trigger action.
        """
        log = self.log.bind(
            job_id=feedback_request.job_id,
            user_id=user_id,
            feedback_type=feedback_request.feedback_type,
        )

        # ---- Step 1: Validate job ownership ----------------------------- #
        job = await db_session.get(Job, feedback_request.job_id)
        if not job or str(job.user_id) != user_id:
            raise ValueError("Job not found or unauthorized.")

        # ---- Step 2: Persist Feedback record ---------------------------- #
        feedback = Feedback(
            id=uuid4(),
            job_id=feedback_request.job_id,
            user_id=user_id,
            scene_index=feedback_request.scene_index,
            feedback_type=feedback_request.feedback_type,
            rating=feedback_request.rating,
            comment=feedback_request.comment,
            is_resolved=False,
        )
        db_session.add(feedback)
        await db_session.flush()

        # ---- Step 3: Determine action ----------------------------------- #
        feedback_type = feedback_request.feedback_type
        action = "none"

        if (
            AUTO_REGEN_CONDITIONS.get(feedback_type)
            and feedback_request.scene_index is not None
        ):
            action = "partial_regen"
            try:
                await self._trigger_partial_regen(
                    job_id=feedback_request.job_id,
                    scene_indices=[feedback_request.scene_index],
                    reason=f"user_feedback:{feedback_type}",
                )
                log.info("feedback_service.partial_regen_triggered")
            except Exception as exc:
                log.error("feedback_service.partial_regen_failed", error=str(exc))

        elif AUTO_REVIEW_CONDITIONS.get(feedback_type):
            action = "review_queue"
            try:
                from layer6_delivery.review.review_queue import review_queue_service  # noqa
                await review_queue_service.enqueue_for_review(
                    job_id=feedback_request.job_id,
                    trigger_reason="user_reported",
                    priority="normal",
                )
                log.info("feedback_service.review_queue_triggered")
            except Exception as exc:
                log.error("feedback_service.review_queue_failed", error=str(exc))

        # Log factual errors to correction_log regardless of review status
        if feedback_type == "incorrect_content" and feedback_request.comment:
            try:
                from layer6_delivery.review.correction_log import correction_log_service  # noqa
                await correction_log_service.log_correction(
                    job_id=feedback_request.job_id,
                    scene_index=feedback_request.scene_index,
                    reported_error=feedback_request.comment,
                    error_type="user_reported_factual_error",
                )
                if action == "none":
                    action = "correction_log"
                log.info("feedback_service.correction_log_triggered")
            except Exception as exc:
                log.error("feedback_service.correction_log_failed", error=str(exc))

        # ---- Step 4: Finalise DB record --------------------------------- #
        feedback.is_resolved = action != "none"
        await db_session.commit()

        log.info("feedback_service.submitted", action=action)

        return FeedbackResult(
            feedback_id=str(feedback.id),
            action_triggered=action,
            message=_ACTION_MESSAGES.get(action, _ACTION_MESSAGES["none"]),
        )

    async def _trigger_partial_regen(
        self,
        job_id: str,
        scene_indices: list[int],
        reason: str,
    ) -> None:
        """Push a partial regeneration task to Redis queue."""
        from core.database import _redis_client  # noqa: PLC0415

        payload = json.dumps({
            "job_id": job_id,
            "scene_indices": scene_indices,
            "reason": reason,
            "triggered_at": utcnow().isoformat(),
        })
        redis = _redis_client
        if redis is None:
            raise RuntimeError("Redis client not initialised.")
        await redis.lpush("edu_video:partial_regen_queue", payload)


feedback_service = FeedbackService()

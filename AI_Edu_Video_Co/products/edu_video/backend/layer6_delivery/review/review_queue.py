# products/edu_video/backend/layer6_delivery/review/review_queue.py
"""
ReviewQueueService: pushes jobs into the human review queue in Redis and DB.
Workers (review_worker.py) consume from this queue.
"""

import json
import time

import structlog
from pydantic import BaseModel

from core.config import get_settings
from core.database import AsyncSessionLocal
from core.utils import generate_uuid, utcnow
from models.job import Job
from models.review import Review

__all__ = ["ReviewQueueService", "ReviewQueueItem", "review_queue_service"]

logger = structlog.get_logger(__name__)
settings = get_settings()

_VALID_PRIORITIES = {"low", "normal", "high", "urgent"}
_VALID_TRIGGERS = {
    "new_subject", "low_confidence", "flagged_content", "user_reported",
    "curriculum_mismatch", "high_cost_anomaly", "manual",
}


class ReviewQueueItem(BaseModel):
    review_id: str
    job_id: str
    trigger_reason: str
    priority: str
    confidence_score: float | None
    enqueued_at: str
    queue_position: int


class ReviewQueueService:
    """
    Manages the human review queue.
    Priority queue implemented as a Redis ZSET (score = timestamp, lower = earlier).
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(__name__)

    async def enqueue_for_review(
        self,
        job_id: str,
        trigger_reason: str,
        priority: str = "normal",
        confidence_score: float | None = None,
    ) -> ReviewQueueItem:
        """
        Create a Review DB record and push job_id to Redis review queue.
        Returns a ReviewQueueItem with position information.
        """
        log = self.log.bind(job_id=job_id, trigger_reason=trigger_reason)

        # Validate inputs
        if trigger_reason not in _VALID_TRIGGERS:
            trigger_reason = "manual"
        if priority not in _VALID_PRIORITIES:
            priority = "normal"

        # Priority → score offset (lower score = processed first)
        priority_offset = {"urgent": -300, "high": -200, "normal": 0, "low": 200}
        score = time.time() + priority_offset.get(priority, 0)

        # ---- Create Review DB record ------------------------------------ #
        review_id = generate_uuid()
        try:
            async with AsyncSessionLocal() as session:
                # Update job status to "review"
                job = await session.get(Job, job_id)
                if job:
                    job.status = "review"
                    await session.flush()

                review = Review(
                    id=review_id,
                    job_id=job_id,
                    reviewer_id=None,
                    status="pending",
                    priority=priority,
                    trigger_reason=trigger_reason,
                    confidence_score=confidence_score,
                    auto_approved=False,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
                session.add(review)
                await session.commit()
                log.info("review_queue.db_record_created", review_id=review_id)

        except Exception as exc:
            log.error("review_queue.db_failed", error=str(exc))

        # ---- Push to Redis ZSET ----------------------------------------- #
        payload = json.dumps({
            "review_id": review_id,
            "job_id": job_id,
            "trigger_reason": trigger_reason,
            "priority": priority,
            "confidence_score": confidence_score,
            "enqueued_at": utcnow().isoformat(),
        })

        position = 0
        try:
            from core.database import _redis_client  # noqa: PLC0415
            redis = _redis_client
            if redis:
                await redis.zadd(settings.REVIEW_QUEUE_KEY, {payload: score})
                position = await redis.zrank(settings.REVIEW_QUEUE_KEY, payload) or 0
                position = int(position) + 1
                log.info("review_queue.enqueued", position=position)
        except Exception as exc:
            log.error("review_queue.redis_failed", error=str(exc))

        return ReviewQueueItem(
            review_id=review_id,
            job_id=job_id,
            trigger_reason=trigger_reason,
            priority=priority,
            confidence_score=confidence_score,
            enqueued_at=utcnow().isoformat(),
            queue_position=position,
        )

    async def dequeue_next(self) -> dict | None:
        """
        Dequeue the next review item (lowest score = highest priority + earliest).
        Called by review_worker.py.
        Returns the payload dict or None if queue is empty.
        """
        try:
            from core.database import _redis_client  # noqa: PLC0415
            redis = _redis_client
            if not redis:
                return None
            result = await redis.zpopmin(settings.REVIEW_QUEUE_KEY, count=1)
            if result:
                raw, _ = result[0]
                return json.loads(raw)
        except Exception as exc:
            self.log.error("review_queue.dequeue_failed", error=str(exc))
        return None

    async def get_queue_depth(self) -> int:
        """Return total number of items in the review queue."""
        try:
            from core.database import _redis_client  # noqa: PLC0415
            redis = _redis_client
            if redis:
                return int(await redis.zcard(settings.REVIEW_QUEUE_KEY))
        except Exception:
            pass
        return 0

    async def remove_from_queue(self, job_id: str) -> bool:
        """Remove all queue entries for a given job_id. Returns True if any removed."""
        try:
            from core.database import _redis_client  # noqa: PLC0415
            redis = _redis_client
            if not redis:
                return False
            # Scan ZSET members for matching job_id
            all_members = await redis.zrange(settings.REVIEW_QUEUE_KEY, 0, -1)
            removed = 0
            for raw in all_members:
                try:
                    payload = json.loads(raw)
                    if str(payload.get("job_id")) == str(job_id):
                        await redis.zrem(settings.REVIEW_QUEUE_KEY, raw)
                        removed += 1
                except (json.JSONDecodeError, AttributeError):
                    continue
            return removed > 0
        except Exception as exc:
            self.log.error("review_queue.remove_failed", job_id=job_id, error=str(exc))
            return False


review_queue_service = ReviewQueueService()

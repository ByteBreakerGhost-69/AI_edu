# products/edu_video/backend/workers/review_worker.py
"""
ReviewWorker: processes human review queue.
Dequeues review items, attempts auto-approval, routes remainder to human reviewers.
Also handles correction log ingestion and DB review record updates.

Run as: python -m workers.review_worker
"""

import asyncio
import json
import signal
import time
from datetime import datetime

import structlog
from pydantic import BaseModel

from core.config import get_settings
from core.database import AsyncSessionLocal, _redis_client, _create_redis_client
from core.utils import generate_uuid, utcnow
from models.review import Review
from sqlalchemy import select

__all__ = ["ReviewWorker", "review_worker"]

logger = structlog.get_logger(__name__)
settings = get_settings()

WORKER_ID: str = f"review_worker_{generate_uuid()[:8]}"
HEARTBEAT_KEY: str = f"edu_video:worker:heartbeat:{WORKER_ID}"

# Score thresholds for auto-approval decisions
_AUTO_APPROVE_SCORE = settings.REVIEW_AUTO_APPROVE_THRESHOLD
_CRITICAL_REJECT_SCORE = 0.30  # below this → auto-reject, not approve


class ReviewWorkerStats(BaseModel):
    worker_id: str
    items_processed: int = 0
    auto_approved: int = 0
    routed_to_human: int = 0
    auto_rejected: int = 0
    errors: int = 0
    started_at: datetime
    last_item_at: datetime | None = None


class ReviewWorker:
    """
    Polls the review queue (Redis ZSET, lowest score = highest priority),
    applies auto-approval logic, and routes borderline cases to human reviewers.

    Auto-approval rules:
      score >= REVIEW_AUTO_APPROVE_THRESHOLD → auto-approve, mark job done
      score < 0.30 (critical_reject) → auto-reject, mark job failed
      0.30 <= score < threshold → route to human reviewer (leave in "review" status)

    Trigger reasons that bypass auto-approval (always route to human):
      "flagged_content", "user_reported", "high_cost_anomaly"
    """

    _ALWAYS_HUMAN_TRIGGERS = frozenset({
        "flagged_content",
        "user_reported",
        "high_cost_anomaly",
    })

    def __init__(self) -> None:
        self.worker_id = WORKER_ID
        self.settings = get_settings()
        self.log = structlog.get_logger(__name__).bind(worker_id=self.worker_id)
        self.stats = ReviewWorkerStats(
            worker_id=self.worker_id,
            started_at=utcnow(),
        )
        self._running = False
        self._semaphore = asyncio.Semaphore(
            max(self.settings.WORKER_CONCURRENCY // 2, 1)
        )

    async def run(self) -> None:
        """Entry point. Runs until SIGTERM/SIGINT."""
        self._running = True
        self.log.info(
            "review_worker_started",
            queue=self.settings.REVIEW_QUEUE_KEY,
            auto_approve_threshold=_AUTO_APPROVE_SCORE,
        )

        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        try:
            while self._running:
                item = await self._dequeue_next()
                if item is None:
                    await asyncio.sleep(self.settings.WORKER_POLL_INTERVAL_SECONDS)
                    continue
                asyncio.create_task(self._process_with_semaphore(item))
        except asyncio.CancelledError:
            self.log.info("review_worker_cancelled")
        finally:
            self._running = False
            heartbeat_task.cancel()
            await self._cleanup()
            self.log.info("review_worker_stopped", stats=self.stats.model_dump())

    async def _process_with_semaphore(self, item: dict) -> None:
        async with self._semaphore:
            await self._process_review_item(item)

    # ------------------------------------------------------------------ #
    # Dequeue                                                              #
    # ------------------------------------------------------------------ #

    async def _dequeue_next(self) -> dict | None:
        """
        ZPOPMIN from review ZSET (lowest score = highest priority + earliest).
        Returns parsed item dict or None.
        """
        redis = await _get_redis()
        result = await redis.zpopmin(self.settings.REVIEW_QUEUE_KEY, count=1)
        if not result:
            return None
        raw, score = result[0]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            self.log.error("invalid_review_payload", raw=str(raw)[:100])
            return None

    # ------------------------------------------------------------------ #
    # Processing                                                            #
    # ------------------------------------------------------------------ #

    async def _process_review_item(self, item: dict) -> None:
        """
        Apply auto-approval decision logic for one review queue item.

        Decision flow:
          1. Load job confidence_score + trigger_reason from item
          2. Check if trigger requires mandatory human review
          3. Auto-approve / auto-reject / route to human
          4. Update Review DB record status
          5. Log decision to correction_log if rejected
        """
        job_id = str(item.get("job_id", "unknown"))
        review_id = str(item.get("review_id", ""))
        trigger_reason = str(item.get("trigger_reason", "manual"))
        confidence_score = float(item.get("confidence_score") or 0.0)
        priority = str(item.get("priority", "normal"))

        log = self.log.bind(
            job_id=job_id,
            review_id=review_id,
            trigger_reason=trigger_reason,
            confidence_score=confidence_score,
        )
        log.info("review_item_processing")
        start = time.perf_counter()

        try:
            decision = self._compute_decision(trigger_reason, confidence_score)
            log.info("review_decision_computed", decision=decision)

            if decision == "auto_approve":
                await self._execute_auto_approve(job_id, review_id, confidence_score, log)
                self.stats.auto_approved += 1

            elif decision == "auto_reject":
                await self._execute_auto_reject(job_id, review_id, confidence_score, log)
                self.stats.auto_rejected += 1

            else:  # "route_to_human"
                await self._execute_route_to_human(
                    job_id, review_id, trigger_reason, confidence_score, priority, log
                )
                self.stats.routed_to_human += 1

            elapsed = time.perf_counter() - start
            log.info(
                "review_item_done",
                decision=decision,
                duration_ms=int(elapsed * 1000),
            )

        except Exception as exc:
            self.stats.errors += 1
            log.error("review_item_error", error=str(exc))
            # On error: leave review record in "pending" state
            # A human admin can pick it up via admin panel

        finally:
            self.stats.items_processed += 1
            self.stats.last_item_at = utcnow()

    def _compute_decision(
        self, trigger_reason: str, confidence_score: float
    ) -> str:
        """
        Return "auto_approve", "auto_reject", or "route_to_human".

        Rules:
          - Certain trigger reasons always go to human regardless of score
          - High confidence (>= threshold) → auto-approve
          - Very low confidence (< 0.30) → auto-reject
          - Middle ground → route to human
        """
        if trigger_reason in self._ALWAYS_HUMAN_TRIGGERS:
            return "route_to_human"

        if confidence_score >= _AUTO_APPROVE_SCORE:
            return "auto_approve"

        if confidence_score < _CRITICAL_REJECT_SCORE:
            return "auto_reject"

        return "route_to_human"

    async def _execute_auto_approve(
        self,
        job_id: str,
        review_id: str,
        confidence_score: float,
        log,
    ) -> None:
        """Mark review as auto-approved and job as done."""
        from layer6_delivery.review.approval_service import approval_service  # noqa

        result = await approval_service.auto_approve(
            job_id=job_id,
            confidence_score=confidence_score,
        )
        log.info(
            "review_auto_approved",
            job_id=job_id,
            review_id=result.review_id,
        )

    async def _execute_auto_reject(
        self,
        job_id: str,
        review_id: str,
        confidence_score: float,
        log,
    ) -> None:
        """
        Auto-reject jobs with critically low quality scores.
        Updates Review + Job DB records and logs to correction_log.
        """
        from layer6_delivery.review.approval_service import (  # noqa
            approval_service, ApprovalDecision,
        )
        from layer6_delivery.review.correction_log import correction_log_service  # noqa

        decision = ApprovalDecision(
            review_id=review_id,
            decision="rejected",
            reviewer_id=f"auto_reviewer:{self.worker_id}",
            reviewer_notes=(
                f"Auto-rejected: quality score {confidence_score:.2f} "
                f"below critical threshold {_CRITICAL_REJECT_SCORE}."
            ),
            rejection_reason="poor_quality",
        )

        try:
            result = await approval_service.process_decision(decision)
            log.warning(
                "review_auto_rejected",
                job_id=job_id,
                confidence_score=confidence_score,
            )
        except Exception as exc:
            log.error("auto_reject_db_failed", error=str(exc))
            # Fall through — still log correction
            result = None

        await correction_log_service.log_correction(
            job_id=job_id,
            scene_index=None,
            reported_error=(
                f"Auto-rejected due to low quality score: {confidence_score:.3f}"
            ),
            error_type="poor_quality",
            source="auto_reviewer",
        )

    async def _execute_route_to_human(
        self,
        job_id: str,
        review_id: str,
        trigger_reason: str,
        confidence_score: float,
        priority: str,
        log,
    ) -> None:
        """
        Update Review DB record to "pending" so human reviewers can see it
        in the admin panel. Job stays in "review" status.
        """
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Review).where(Review.id == review_id)
                )
                review = result.scalar_one_or_none()

                if review:
                    review.status = "pending"
                    review.confidence_score = confidence_score
                    review.updated_at = utcnow()
                    await session.commit()

        except Exception as exc:
            log.error("route_to_human_db_failed", error=str(exc))

        log.info(
            "review_routed_to_human",
            job_id=job_id,
            trigger_reason=trigger_reason,
            confidence_score=confidence_score,
            priority=priority,
        )

        # Notify via Redis pub/sub so admin panel can update in real time
        try:
            redis = await _get_redis()
            await redis.publish(
                "edu_video:review:new_item",
                json.dumps({
                    "job_id": job_id,
                    "review_id": review_id,
                    "trigger_reason": trigger_reason,
                    "confidence_score": confidence_score,
                    "priority": priority,
                    "routed_at": utcnow().isoformat(),
                }),
            )
        except Exception as exc:
            log.warning("review_pubsub_notify_failed", error=str(exc))

    # ------------------------------------------------------------------ #
    # Helpers                                                               #
    # ------------------------------------------------------------------ #

    async def _heartbeat_loop(self) -> None:
        redis = await _get_redis()
        while self._running:
            try:
                queue_depth = await redis.zcard(self.settings.REVIEW_QUEUE_KEY)
                await redis.hset(
                    HEARTBEAT_KEY,
                    mapping={
                        "worker_id": self.worker_id,
                        "worker_type": "review",
                        "timestamp": utcnow().isoformat(),
                        "items_processed": self.stats.items_processed,
                        "auto_approved": self.stats.auto_approved,
                        "routed_to_human": self.stats.routed_to_human,
                        "queue_depth": queue_depth,
                        "status": "running",
                    },
                )
                await redis.expire(
                    HEARTBEAT_KEY,
                    self.settings.WORKER_HEARTBEAT_INTERVAL * 3,
                )
            except Exception as exc:
                self.log.warning("heartbeat_failed", error=str(exc))
            await asyncio.sleep(self.settings.WORKER_HEARTBEAT_INTERVAL)

    async def _cleanup(self) -> None:
        try:
            redis = await _get_redis()
            await redis.delete(HEARTBEAT_KEY)
        except Exception:
            pass


review_worker = ReviewWorker()


async def _get_redis():
    from core.database import _redis_client  # noqa
    if _redis_client is None:
        return await _create_redis_client()
    return _redis_client


def _handle_signal(signum, frame) -> None:
    logger.info("shutdown_signal_received", signal=signum)
    review_worker._running = False


async def _main() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    await review_worker.run()


if __name__ == "__main__":
    asyncio.run(_main())

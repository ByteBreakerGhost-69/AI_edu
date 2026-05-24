# products/edu_video/backend/layer1_input/queue_service.py
"""
Redis-backed job queue service.
Premium users go into a priority ZSET; free users into a standard LIST.
Workers call dequeue_job() which drains priority first.
"""

import json
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import structlog
from redis.asyncio import Redis

from layer1_input.schemas import QueuedJob, QueueStats

if TYPE_CHECKING:
    from models.job import Job
    from models.user import User

__all__ = [
    "QueueService",
    "QueueFullError",
    "JobNotFoundInQueueError",
    "queue_service",
    "QUEUE_KEY",
    "PRIORITY_QUEUE_KEY",
    "JOB_DATA_KEY_PREFIX",
    "POSITION_TRACKER_KEY",
]

logger = structlog.get_logger(__name__)

# --- Queue key constants ---
QUEUE_KEY = "edu_video:job_queue"
PRIORITY_QUEUE_KEY = "edu_video:job_queue:priority"
JOB_DATA_KEY_PREFIX = "edu_video:job:"
POSITION_TRACKER_KEY = "edu_video:queue:positions"

MAX_QUEUE_SIZE = 100
JOB_DATA_TTL = 86400  # 24 hours


class QueueFullError(Exception):
    def __init__(self, current_size: int, max_size: int) -> None:
        super().__init__(
            f"Queue is full ({current_size}/{max_size}). Try again later."
        )
        self.current_size = current_size
        self.max_size = max_size


class JobNotFoundInQueueError(Exception):
    def __init__(self, job_id: str) -> None:
        super().__init__(f"Job {job_id} not found in queue.")
        self.job_id = job_id


class QueueService:
    """
    Manages the two-tier Redis job queue.
    Priority queue (ZSET): premium users, drained first.
    Standard queue (LIST): free users, FIFO via LPUSH/BRPOP.
    """

    async def enqueue_job(
        self,
        job: "Job",
        user: "User",
        redis: Redis,
    ) -> QueuedJob:
        """
        Serialize and enqueue a job. Raises QueueFullError if total > MAX_QUEUE_SIZE.
        Premium users go to the priority ZSET; free users to the standard LIST.

        Returns QueuedJob with current queue position.
        """
        log = logger.bind(job_id=str(job.id), user_id=str(job.user_id))

        # Check total queue depth before enqueuing
        try:
            standard_len = await redis.llen(QUEUE_KEY)
            priority_len = await redis.zcard(PRIORITY_QUEUE_KEY)
            total = standard_len + priority_len

            if total >= MAX_QUEUE_SIZE:
                raise QueueFullError(current_size=total, max_size=MAX_QUEUE_SIZE)
        except QueueFullError:
            raise
        except Exception as exc:
            log.warning("queue_service.size_check_failed", error=str(exc))
            # Don't block enqueue on Redis read failure

        job_payload = self._serialize_job(job)
        job_id_str = str(job.id)
        enqueue_ts = time.time()

        try:
            # Determine tier from loaded subscription (may be None for new users)
            tier = "free"
            if hasattr(user, "subscription") and user.subscription:
                tier = user.subscription.tier

            if tier == "premium":
                await redis.zadd(
                    PRIORITY_QUEUE_KEY,
                    {job_id_str: enqueue_ts},
                )
                queue_name = PRIORITY_QUEUE_KEY
                log.info("queue_service.enqueued_priority")
            else:
                await redis.lpush(QUEUE_KEY, json.dumps(job_payload))
                queue_name = QUEUE_KEY
                log.info("queue_service.enqueued_standard")

            # Store job data hash for retrieval by worker
            data_key = f"{JOB_DATA_KEY_PREFIX}{job_id_str}"
            await redis.hset(data_key, mapping={k: str(v) for k, v in job_payload.items()})
            await redis.expire(data_key, JOB_DATA_TTL)

            # Record position timestamp
            await redis.hset(POSITION_TRACKER_KEY, job_id_str, str(enqueue_ts))

        except QueueFullError:
            raise
        except Exception as exc:
            log.error("queue_service.enqueue_failed", error=str(exc))
            # Queue failure must not block DB write — return a placeholder position
            return QueuedJob(
                job_id=job.id,
                user_id=job.user_id,
                queue_name="unknown",
                position=0,
                enqueued_at=datetime.now(tz=timezone.utc),
            )

        position = await self.get_queue_position(job_id_str, redis)
        return QueuedJob(
            job_id=job.id,
            user_id=job.user_id,
            queue_name=queue_name,
            position=position,
            enqueued_at=datetime.fromtimestamp(enqueue_ts, tz=timezone.utc),
        )

    async def get_queue_position(self, job_id: str, redis: Redis) -> int:
        """
        Return 1-based queue position for a job.
        Premium queue positions are prepended ahead of standard queue.
        Returns 0 if job is not found in either queue.
        """
        try:
            # Check priority queue first
            priority_rank = await redis.zrank(PRIORITY_QUEUE_KEY, job_id)
            if priority_rank is not None:
                return int(priority_rank) + 1

            # Check standard queue (LIST — O(n) scan via lrange)
            items = await redis.lrange(QUEUE_KEY, 0, -1)
            priority_size = await redis.zcard(PRIORITY_QUEUE_KEY)
            for i, raw in enumerate(items):
                try:
                    payload = json.loads(raw)
                    if str(payload.get("id")) == job_id:
                        return priority_size + i + 1
                except (json.JSONDecodeError, AttributeError):
                    continue

            return 0
        except Exception as exc:
            logger.warning(
                "queue_service.position_lookup_failed",
                job_id=job_id,
                error=str(exc),
            )
            return 0

    async def dequeue_job(self, redis: Redis) -> dict[str, Any] | None:
        """
        Dequeue next job for a worker.
        Drains priority ZSET first (lowest score = earliest enqueue),
        then falls back to standard LIST with 1s blocking timeout.
        """
        try:
            # Priority: ZPOPMIN returns [(member, score), ...]
            priority_result = await redis.zpopmin(PRIORITY_QUEUE_KEY, count=1)
            if priority_result:
                job_id = priority_result[0][0]  # (member, score)
                data_key = f"{JOB_DATA_KEY_PREFIX}{job_id}"
                job_data = await redis.hgetall(data_key)
                if job_data:
                    await redis.hdel(POSITION_TRACKER_KEY, job_id)
                    logger.info("queue_service.dequeued_priority", job_id=job_id)
                    return dict(job_data)
                # Data expired — skip silently
                return await self.dequeue_job(redis)

            # Standard: BRPOP blocks up to 1 second
            result = await redis.brpop([QUEUE_KEY], timeout=1)
            if result is None:
                return None

            _, raw = result  # (key, value)
            payload = json.loads(raw)
            job_id = str(payload.get("id", ""))
            await redis.hdel(POSITION_TRACKER_KEY, job_id)
            logger.info("queue_service.dequeued_standard", job_id=job_id)
            return payload

        except Exception as exc:
            logger.error("queue_service.dequeue_failed", error=str(exc))
            return None

    async def remove_from_queue(self, job_id: str, redis: Redis) -> bool:
        """
        Remove a job from whichever queue it resides in.
        Used when a job is cancelled by the user.
        Returns True if found and removed.
        """
        removed = False
        try:
            # Priority ZSET
            priority_removed = await redis.zrem(PRIORITY_QUEUE_KEY, job_id)
            if priority_removed:
                removed = True

            # Standard LIST — rebuild without the target job
            if not removed:
                items = await redis.lrange(QUEUE_KEY, 0, -1)
                for raw in items:
                    try:
                        payload = json.loads(raw)
                        if str(payload.get("id")) == job_id:
                            await redis.lrem(QUEUE_KEY, 1, raw)
                            removed = True
                            break
                    except (json.JSONDecodeError, AttributeError):
                        continue

            if removed:
                await redis.hdel(POSITION_TRACKER_KEY, job_id)
                data_key = f"{JOB_DATA_KEY_PREFIX}{job_id}"
                await redis.delete(data_key)
                logger.info("queue_service.removed", job_id=job_id)

        except Exception as exc:
            logger.error(
                "queue_service.remove_failed", job_id=job_id, error=str(exc)
            )

        return removed

    async def get_queue_stats(self, redis: Redis) -> QueueStats:
        """Return current queue depth statistics."""
        try:
            priority_jobs = await redis.zcard(PRIORITY_QUEUE_KEY)
            standard_jobs = await redis.llen(QUEUE_KEY)

            # Find oldest job by lowest timestamp in position tracker
            oldest_age: float | None = None
            all_positions = await redis.hgetall(POSITION_TRACKER_KEY)
            if all_positions:
                oldest_ts = min(float(v) for v in all_positions.values())
                oldest_age = time.time() - oldest_ts

            return QueueStats(
                total_jobs=priority_jobs + standard_jobs,
                priority_jobs=priority_jobs,
                standard_jobs=standard_jobs,
                oldest_job_age_seconds=oldest_age,
            )
        except Exception as exc:
            logger.error("queue_service.stats_failed", error=str(exc))
            return QueueStats(
                total_jobs=0,
                priority_jobs=0,
                standard_jobs=0,
                oldest_job_age_seconds=None,
            )

    @staticmethod
    def _serialize_job(job: "Job") -> dict[str, Any]:
        """Convert Job ORM object to a JSON-serializable dict for Redis storage."""
        return {
            "id": str(job.id),
            "user_id": str(job.user_id),
            "title": job.title,
            "subject": job.subject,
            "curriculum": job.curriculum,
            "difficulty_level": job.difficulty_level,
            "language": job.language,
            "input_text": job.input_text or "",
            "input_image_url": job.input_image_url or "",
            "created_at": job.created_at.isoformat(),
        }


queue_service = QueueService()

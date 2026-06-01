# products/edu_video/backend/workers/renderer_worker.py
"""
RendererWorker: partial regeneration worker.
Consumes "edu_video:partial_regen_queue" and re-runs Layers 4+5
for specific scene indices only — triggered by user feedback or reviewer decisions.

Run as: python -m workers.renderer_worker
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

__all__ = ["RendererWorker", "renderer_worker"]

logger = structlog.get_logger(__name__)
settings = get_settings()

WORKER_ID: str = f"renderer_worker_{generate_uuid()[:8]}"
REGEN_QUEUE_KEY: str = "edu_video:partial_regen_queue"
HEARTBEAT_KEY: str = f"edu_video:worker:heartbeat:{WORKER_ID}"
PROCESSING_SET_KEY: str = "edu_video:regen:processing"


class RendererWorkerStats(BaseModel):
    worker_id: str
    regens_processed: int = 0
    regens_failed: int = 0
    regens_succeeded: int = 0
    started_at: datetime
    last_job_at: datetime | None = None
    current_jobs: list[str] = []


class RendererWorker:
    """
    Partial regeneration worker.
    Consumes regen requests from Redis LIST (BRPOP), runs PartialRegenService,
    and updates DB scene records on success.
    """

    def __init__(self) -> None:
        self.worker_id = WORKER_ID
        self.settings = get_settings()
        self.log = structlog.get_logger(__name__).bind(worker_id=self.worker_id)
        self.stats = RendererWorkerStats(
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
        self.log.info("renderer_worker_started", queue=REGEN_QUEUE_KEY)

        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        try:
            while self._running:
                request = await self._dequeue_next()
                if request is None:
                    await asyncio.sleep(self.settings.WORKER_POLL_INTERVAL_SECONDS)
                    continue
                asyncio.create_task(self._process_with_semaphore(request))
        except asyncio.CancelledError:
            self.log.info("renderer_worker_cancelled")
        finally:
            self._running = False
            heartbeat_task.cancel()
            await self._cleanup()
            self.log.info("renderer_worker_stopped", stats=self.stats.model_dump())

    async def _process_with_semaphore(self, request: dict) -> None:
        async with self._semaphore:
            await self._process_regen(request)

    async def _dequeue_next(self) -> dict | None:
        """BRPOP from partial regen queue with poll interval timeout."""
        redis = await _get_redis()
        result = await redis.brpop(
            REGEN_QUEUE_KEY,
            timeout=int(self.settings.WORKER_POLL_INTERVAL_SECONDS),
        )
        if not result:
            return None
        _, raw = result
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            self.log.error("invalid_regen_payload", raw=str(raw)[:100])
            return None

    async def _process_regen(self, request: dict) -> None:
        """
        Execute partial regeneration for specified scene indices.
        Request format: {job_id, scene_indices, reason, triggered_at, retry_count?}
        """
        job_id = str(request.get("job_id", "unknown"))
        scene_indices = list(request.get("scene_indices", []))
        reason = str(request.get("reason", "unknown"))
        retry_count = int(request.get("retry_count", 0))

        log = self.log.bind(
            job_id=job_id,
            scene_indices=scene_indices,
            reason=reason,
        )
        log.info("regen_started")

        redis = await _get_redis()
        await redis.sadd(PROCESSING_SET_KEY, job_id)
        self.stats.current_jobs.append(job_id)
        start = time.perf_counter()

        try:
            from layer6_delivery.partial_regen import (  # noqa
                PartialRegenService,
                PartialRegenRequest,
            )

            regen_service = PartialRegenService()
            regen_request = PartialRegenRequest(
                job_id=job_id,
                scene_indices=scene_indices,
                reason=reason,
                retry_count=retry_count,
            )

            result = await asyncio.wait_for(
                regen_service.regenerate(regen_request),
                timeout=self.settings.WORKER_JOB_TIMEOUT_SECONDS,
            )

            elapsed = time.perf_counter() - start
            self.stats.regens_succeeded += 1

            log.info(
                "regen_completed",
                succeeded=len(result.scene_indices_succeeded),
                failed=len(result.scene_indices_failed),
                cost_usd=result.total_cost_usd,
                duration_seconds=round(elapsed, 2),
            )

            # If some scenes failed and we have retries left, re-enqueue just those
            if result.scene_indices_failed and retry_count < self.settings.WORKER_MAX_JOB_RETRIES:
                retry_payload = json.dumps({
                    "job_id": job_id,
                    "scene_indices": result.scene_indices_failed,
                    "reason": f"{reason}:retry",
                    "triggered_at": utcnow().isoformat(),
                    "retry_count": retry_count + 1,
                })
                delay = 60 * (retry_count + 1)
                await asyncio.sleep(delay)
                await redis.lpush(REGEN_QUEUE_KEY, retry_payload)
                log.warning(
                    "regen_partial_retry_queued",
                    failed_scenes=result.scene_indices_failed,
                    retry_count=retry_count + 1,
                )

        except asyncio.TimeoutError:
            elapsed = time.perf_counter() - start
            self.stats.regens_failed += 1
            log.error(
                "regen_timeout",
                timeout=self.settings.WORKER_JOB_TIMEOUT_SECONDS,
                duration_seconds=round(elapsed, 2),
            )
            await self._handle_regen_failure(
                job_id, scene_indices, reason, retry_count,
                "Regen timed out."
            )

        except Exception as exc:
            elapsed = time.perf_counter() - start
            self.stats.regens_failed += 1
            log.error(
                "regen_failed",
                error=str(exc),
                duration_seconds=round(elapsed, 2),
            )
            await self._handle_regen_failure(
                job_id, scene_indices, reason, retry_count, str(exc)
            )

        finally:
            await redis.srem(PROCESSING_SET_KEY, job_id)
            if job_id in self.stats.current_jobs:
                self.stats.current_jobs.remove(job_id)
            self.stats.regens_processed += 1
            self.stats.last_job_at = utcnow()

    async def _handle_regen_failure(
        self,
        job_id: str,
        scene_indices: list[int],
        reason: str,
        retry_count: int,
        error: str,
    ) -> None:
        """Re-enqueue with back-off if retries remain, otherwise log permanent failure."""
        if retry_count < self.settings.WORKER_MAX_JOB_RETRIES:
            delay = 60 * (retry_count + 1)
            retry_payload = json.dumps({
                "job_id": job_id,
                "scene_indices": scene_indices,
                "reason": f"{reason}:error_retry",
                "triggered_at": utcnow().isoformat(),
                "retry_count": retry_count + 1,
            })
            await asyncio.sleep(min(delay, 300))  # cap at 5 min
            redis = await _get_redis()
            await redis.lpush(REGEN_QUEUE_KEY, retry_payload)
            self.log.warning(
                "regen_error_retry_queued",
                job_id=job_id,
                retry_count=retry_count + 1,
                error=error,
            )
        else:
            self.log.error(
                "regen_permanently_failed",
                job_id=job_id,
                scene_indices=scene_indices,
                error=error,
            )

    async def _heartbeat_loop(self) -> None:
        redis = await _get_redis()
        while self._running:
            try:
                await redis.hset(
                    HEARTBEAT_KEY,
                    mapping={
                        "worker_id": self.worker_id,
                        "worker_type": "renderer",
                        "timestamp": utcnow().isoformat(),
                        "regens_processed": self.stats.regens_processed,
                        "current_jobs": json.dumps(self.stats.current_jobs),
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


renderer_worker = RendererWorker()


async def _get_redis():
    from core.database import _redis_client  # noqa
    if _redis_client is None:
        return await _create_redis_client()
    return _redis_client


def _handle_signal(signum, frame) -> None:
    logger.info("shutdown_signal_received", signal=signum)
    renderer_worker._running = False


async def _main() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    await renderer_worker.run()


if __name__ == "__main__":
    asyncio.run(_main())

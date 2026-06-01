# products/edu_video/backend/workers/video_worker.py
"""
VideoWorker: main pipeline worker.
Dequeues jobs from Redis (priority ZSET first, then standard FIFO LIST),
runs the full Layer 2 → 3 → 4 → 5 → 6 pipeline, handles retries.

Run as: python -m workers.video_worker
"""

import asyncio
import json
import signal
import time
from datetime import datetime
from pathlib import Path

import structlog
from pydantic import BaseModel
from sqlalchemy import select

from core.config import get_settings
from core.database import AsyncSessionLocal, _redis_client, _create_redis_client
from core.utils import generate_uuid, utcnow
from models.job import Job
from models.scene import Scene

__all__ = ["VideoWorker", "video_worker"]

logger = structlog.get_logger(__name__)
settings = get_settings()

WORKER_ID: str = f"video_worker_{generate_uuid()[:8]}"
QUEUE_KEY: str = "edu_video:job_queue"
PRIORITY_QUEUE_KEY: str = "edu_video:job_queue:priority"
PROCESSING_SET_KEY: str = "edu_video:processing"
RETRY_QUEUE_KEY: str = "edu_video:retry_queue"
HEARTBEAT_KEY: str = f"edu_video:worker:heartbeat:{WORKER_ID}"


# --------------------------------------------------------------------------- #
# Stats model                                                                  #
# --------------------------------------------------------------------------- #

class WorkerStats(BaseModel):
    worker_id: str
    jobs_processed: int = 0
    jobs_failed: int = 0
    jobs_succeeded: int = 0
    avg_processing_time_seconds: float = 0.0
    started_at: datetime
    last_job_at: datetime | None = None
    current_jobs: list[str] = []


# --------------------------------------------------------------------------- #
# VideoWorker                                                                  #
# --------------------------------------------------------------------------- #

class VideoWorker:
    """
    Main pipeline worker.
    Pulls jobs from Redis, executes Layers 2-6 with a hard timeout,
    retries on failure with exponential back-off, and writes heartbeats.
    """

    def __init__(self) -> None:
        self.worker_id = WORKER_ID
        self.settings = get_settings()
        self.log = structlog.get_logger(__name__).bind(worker_id=self.worker_id)
        self.stats = WorkerStats(
            worker_id=self.worker_id,
            started_at=utcnow(),
        )
        self._running = False
        self._semaphore = asyncio.Semaphore(settings.WORKER_CONCURRENCY)

    # ------------------------------------------------------------------ #
    # Main loop                                                            #
    # ------------------------------------------------------------------ #

    async def run(self) -> None:
        """
        Entry point. Runs until SIGTERM/SIGINT.
        Heartbeat and retry-queue draining run as background tasks.
        """
        self._running = True
        self.log.info(
            "worker_started",
            concurrency=self.settings.WORKER_CONCURRENCY,
            queue=QUEUE_KEY,
            priority_queue=PRIORITY_QUEUE_KEY,
        )

        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        retry_task = asyncio.create_task(self._retry_queue_loop())

        try:
            while self._running:
                job_payload = await self._dequeue_next()

                if job_payload is None:
                    await asyncio.sleep(self.settings.WORKER_POLL_INTERVAL_SECONDS)
                    continue

                # Launch as background task — keeps the poll loop responsive
                asyncio.create_task(self._process_with_semaphore(job_payload))

        except asyncio.CancelledError:
            self.log.info("worker_cancelled")
        finally:
            self._running = False
            heartbeat_task.cancel()
            retry_task.cancel()
            await self._cleanup()
            self.log.info("worker_stopped", stats=self.stats.model_dump())

    async def _process_with_semaphore(self, job_payload: dict) -> None:
        async with self._semaphore:
            await self._process_job(job_payload)

    # ------------------------------------------------------------------ #
    # Dequeue                                                              #
    # ------------------------------------------------------------------ #

    async def _dequeue_next(self) -> dict | None:
        """
        Check priority ZSET first (premium users), then standard FIFO LIST.
        Returns parsed job_payload dict or None.
        """
        redis = await _get_redis()

        # Priority queue (ZSET — lowest score = earliest enqueue)
        priority_items = await redis.zpopmin(PRIORITY_QUEUE_KEY, count=1)
        if priority_items:
            raw = priority_items[0][0]  # (member, score)
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                self.log.error("invalid_priority_payload", raw=str(raw)[:100])
                return None

        # Standard FIFO queue (BRPOP blocks for up to poll_interval seconds)
        result = await redis.brpop(
            QUEUE_KEY,
            timeout=int(self.settings.WORKER_POLL_INTERVAL_SECONDS),
        )
        if result:
            _, raw = result
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                self.log.error("invalid_queue_payload", raw=str(raw)[:100])
                return None

        return None

    # ------------------------------------------------------------------ #
    # Job processing                                                        #
    # ------------------------------------------------------------------ #

    async def _process_job(self, job_payload: dict) -> None:
        job_id = str(job_payload.get("job_id", "unknown"))
        log = self.log.bind(job_id=job_id)
        start_time = time.perf_counter()

        redis = await _get_redis()
        await redis.sadd(PROCESSING_SET_KEY, job_id)
        self.stats.current_jobs.append(job_id)

        try:
            log.info("job_started", payload_keys=list(job_payload.keys()))

            await asyncio.wait_for(
                self._run_pipeline(job_payload, log, start_time),
                timeout=self.settings.WORKER_JOB_TIMEOUT_SECONDS,
            )

            elapsed = time.perf_counter() - start_time
            self.stats.jobs_succeeded += 1
            self._update_avg_time(elapsed)
            log.info("job_completed", duration_seconds=round(elapsed, 2))

        except asyncio.TimeoutError:
            elapsed = time.perf_counter() - start_time
            log.error(
                "job_timeout",
                timeout=self.settings.WORKER_JOB_TIMEOUT_SECONDS,
                duration_seconds=round(elapsed, 2),
            )
            await self._handle_job_failure(
                job_id,
                f"Job exceeded {self.settings.WORKER_JOB_TIMEOUT_SECONDS}s timeout.",
                job_payload,
            )

        except Exception as exc:
            elapsed = time.perf_counter() - start_time
            log.error(
                "job_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                duration_seconds=round(elapsed, 2),
            )
            await self._handle_job_failure(job_id, str(exc), job_payload)

        finally:
            await redis.srem(PROCESSING_SET_KEY, job_id)
            if job_id in self.stats.current_jobs:
                self.stats.current_jobs.remove(job_id)
            self.stats.jobs_processed += 1
            self.stats.last_job_at = utcnow()

    # ------------------------------------------------------------------ #
    # Full pipeline                                                         #
    # ------------------------------------------------------------------ #

    async def _run_pipeline(
        self, job_payload: dict, log, pipeline_start: float
    ) -> None:
        """Execute Layers 2 → 6 in sequence."""
        job_id = str(job_payload["job_id"])

        # ---- LAYER 2: Orchestration ---------------------------------- #
        log.info("pipeline_stage", stage="layer2_orchestration")
        from layer2_orchestrator.orchestrator import video_orchestrator  # noqa

        orchestrator_result = await video_orchestrator.run(job_payload)
        if not orchestrator_result.success:
            raise RuntimeError(f"Orchestration failed: {orchestrator_result.error}")

        scenes = await self._load_scenes_from_db(job_id)
        if not scenes:
            raise RuntimeError("No scenes persisted after orchestration.")

        from layer4_script_visual.schemas import SceneInput, JobContext  # noqa
        from layer1_input.schemas import SubjectEnum, CurriculumEnum, DifficultyEnum  # noqa

        scene_inputs = [
            SceneInput(
                scene_index=s.scene_index,
                title=s.title or f"Scene {s.scene_index + 1}",
                narration_text=s.narration_text,
                visual_description=s.visual_description or "",
                renderer_type=s.renderer_type or "lottie",
                duration_seconds=float(s.duration_seconds or 30.0),
                render_metadata=dict(s.render_metadata or {}),
                fact_checked=bool(s.fact_checked),
                llm_cost_usd=float(s.llm_cost_usd or 0.0),
            )
            for s in sorted(scenes, key=lambda x: x.scene_index)
        ]

        job_context = await self._build_job_context(
            job_payload, job_id, len(scene_inputs)
        )

        # ---- LAYER 4: Script & Visual -------------------------------- #
        log.info("pipeline_stage", stage="layer4_script_visual")
        from layer4_script_visual.difficulty_adapter import difficulty_adapter  # noqa
        from layer4_script_visual.language_localizer import language_localizer  # noqa
        from layer4_script_visual.script_generator import script_generator  # noqa
        from layer4_script_visual.visual_asset_generator import visual_asset_generator  # noqa

        difficulty = DifficultyEnum(job_payload.get("difficulty_level", "intermediate"))
        subject = SubjectEnum(job_payload.get("subject", "mathematics"))
        language = job_payload.get("language", "en")

        adapted = await difficulty_adapter.adapt(scene_inputs, difficulty, subject, job_id)
        localized = await language_localizer.localize(adapted, language, subject, job_id)
        refined_scripts = await script_generator.generate(localized, job_context)
        layer4_result = await visual_asset_generator.generate(refined_scripts, job_context)

        packages = layer4_result.scene_packages
        if not packages:
            raise RuntimeError("Layer 4 produced no scene packages.")

        log.info("layer4_complete", scene_count=len(packages))

        # ---- LAYER 5: Rendering ------------------------------------- #
        log.info("pipeline_stage", stage="layer5_rendering")
        from layer5_rendering.tts_service import tts_service  # noqa
        from layer5_rendering.animation_router import animation_router  # noqa
        from layer5_rendering.timing_sync import timing_sync  # noqa
        from layer5_rendering.subtitle_generator import subtitle_generator  # noqa
        from layer5_rendering.compositor import compositor  # noqa

        await self._update_job_status(job_id, "rendering")

        tts_results = await tts_service.synthesize_all(packages, job_id)
        log.info("tts_complete", scenes=len(tts_results))

        renderer_results = await animation_router.render_all(packages, job_id)
        log.info(
            "rendering_complete",
            scenes=len(renderer_results),
            failed=sum(1 for r in renderer_results if not r.success),
        )

        synced_scenes = await timing_sync.sync_all(tts_results, renderer_results, job_id)
        subtitle_result = await subtitle_generator.generate(packages, synced_scenes, job_id)

        rendering_result = await compositor.compose(
            packages=packages,
            synced_scenes=synced_scenes,
            tts_results=tts_results,
            renderer_results=renderer_results,
            subtitle_result=subtitle_result,
            job_id=job_id,
        )
        log.info(
            "compositor_complete",
            duration=rendering_result.total_duration_seconds,
            video_url=rendering_result.final_video_url,
        )

        # ---- LAYER 5: Quality Check --------------------------------- #
        log.info("pipeline_stage", stage="layer5_quality_check")
        from layer5_rendering.quality_check import quality_check_orchestrator  # noqa

        quality_report = await quality_check_orchestrator.run(
            rendering_result=rendering_result,
            synced_scenes=synced_scenes,
            tts_results=tts_results,
            packages=packages,
            job_id=job_id,
        )

        # Temp cleanup AFTER quality check (quality check needs local files)
        import shutil  # noqa
        temp_dir = Path(f"{self.settings.RENDER_TEMP_DIR}/{job_id}")
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: shutil.rmtree(str(temp_dir), ignore_errors=True)
        )

        rendering_result.quality_passed = quality_report.passed
        log.info(
            "quality_check_complete",
            passed=quality_report.passed,
            score=quality_report.overall_score,
            issues=len(quality_report.issues),
        )

        # ---- LAYER 6: Delivery -------------------------------------- #
        log.info("pipeline_stage", stage="layer6_delivery")
        from layer6_delivery.cdn_service import cdn_service  # noqa
        from layer6_delivery.analytics import analytics_service  # noqa
        from layer6_delivery.review.review_queue import review_queue_service  # noqa
        from layer6_delivery.review.approval_service import approval_service  # noqa

        pipeline_elapsed = time.perf_counter() - pipeline_start

        delivery_result = await cdn_service.finalize_delivery(
            rendering_result, quality_report, packages, job_id
        )

        await analytics_service.track_job_completion(
            job_id=job_id,
            user_id=str(job_payload.get("user_id", "")),
            rendering_result=rendering_result,
            quality_report=quality_report,
            packages=packages,
            processing_time_seconds=pipeline_elapsed,
        )

        if delivery_result.review_required:
            # Try auto-approval first
            auto_result = await approval_service.auto_approve(
                job_id=job_id,
                confidence_score=quality_report.overall_score,
            )
            if auto_result.decision == "approved":
                log.info("job_auto_approved", score=quality_report.overall_score)
            else:
                await review_queue_service.enqueue_for_review(
                    job_id=job_id,
                    trigger_reason="low_confidence",
                    priority="normal",
                    confidence_score=quality_report.overall_score,
                )
                log.info("job_sent_to_review", score=quality_report.overall_score)
        else:
            log.info(
                "job_delivered",
                video_url=delivery_result.public_video_url,
                duration=rendering_result.total_duration_seconds,
            )

        # Mirror final status to Redis job hash
        redis = await _get_redis()
        await redis.hset(
            f"edu_video:job:{job_id}",
            mapping={
                "status": "done" if not delivery_result.review_required else "review",
                "video_url": delivery_result.public_video_url or "",
                "updated_at": utcnow().isoformat(),
            },
        )

    # ------------------------------------------------------------------ #
    # Failure handling                                                      #
    # ------------------------------------------------------------------ #

    async def _handle_job_failure(
        self,
        job_id: str,
        error_message: str,
        job_payload: dict,
    ) -> None:
        """
        Re-enqueue with exponential back-off if retries remain.
        Mark as permanently failed in DB when retries are exhausted.
        """
        retries_left = int(
            job_payload.get("retries_left", self.settings.WORKER_MAX_JOB_RETRIES)
        )
        self.stats.jobs_failed += 1

        if retries_left > 0:
            retry_num = self.settings.WORKER_MAX_JOB_RETRIES - retries_left + 1
            retry_delay = 60 * retry_num  # 60s, 120s, 180s, ...
            updated_payload = {
                **job_payload,
                "retries_left": retries_left - 1,
                "last_error": error_message[:500],
                "retry_at": utcnow().isoformat(),
            }
            retry_score = time.time() + retry_delay
            redis = await _get_redis()
            await redis.zadd(
                RETRY_QUEUE_KEY,
                {json.dumps(updated_payload): retry_score},
            )
            self.log.warning(
                "job_requeued_for_retry",
                job_id=job_id,
                retries_left=retries_left - 1,
                retry_in_seconds=retry_delay,
            )
        else:
            await self._update_job_status(job_id, "failed", error_message)
            self.log.error("job_permanently_failed", job_id=job_id, error=error_message)

    # ------------------------------------------------------------------ #
    # Retry queue                                                           #
    # ------------------------------------------------------------------ #

    async def _retry_queue_loop(self) -> None:
        """
        Periodically drain the retry queue of jobs whose back-off delay has elapsed.
        Score = earliest eligible timestamp. Jobs with score ≤ now() are ready.
        """
        while self._running:
            try:
                redis = await _get_redis()
                now = time.time()
                ready = await redis.zrangebyscore(
                    RETRY_QUEUE_KEY, min=0, max=now, start=0, num=10
                )
                for raw in ready:
                    await redis.zrem(RETRY_QUEUE_KEY, raw)
                    try:
                        payload = json.loads(raw)
                        # Re-enqueue to standard queue
                        await redis.lpush(QUEUE_KEY, raw)
                        self.log.info(
                            "retry_job_requeued",
                            job_id=payload.get("job_id"),
                            retries_left=payload.get("retries_left"),
                        )
                    except json.JSONDecodeError:
                        self.log.warning("retry_queue_invalid_payload")
            except Exception as exc:
                self.log.warning("retry_queue_loop_error", error=str(exc))

            await asyncio.sleep(15)  # check every 15 seconds

 # ------------------------------------------------------------------ #
    # Helpers                                                               #
    # ------------------------------------------------------------------ #

    async def _update_job_status(
        self,
        job_id: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Update Job status in DB and Redis."""
        try:
            async with AsyncSessionLocal() as session:
                job = await session.get(Job, job_id)
                if job:
                    job.status = status
                    if error_message:
                        job.error_message = error_message[:1000]
                    if status in ("failed", "done"):
                        job.completed_at = utcnow()
                    job.updated_at = utcnow()
                    await session.commit()
        except Exception as exc:
            self.log.error("db_status_update_failed", job_id=job_id, error=str(exc))

        try:
            redis = await _get_redis()
            update: dict = {"status": status, "updated_at": utcnow().isoformat()}
            if error_message:
                update["error"] = error_message[:200]
            await redis.hset(f"edu_video:job:{job_id}", mapping=update)
        except Exception as exc:
            self.log.warning("redis_status_update_failed", job_id=job_id, error=str(exc))

    async def _load_scenes_from_db(self, job_id: str) -> list:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Scene)
                .where(Scene.job_id == job_id)
                .order_by(Scene.scene_index)
            )
            return result.scalars().all()

    async def _build_job_context(
        self,
        job_payload: dict,
        job_id: str,
        scene_count: int,
    ):
        from layer4_script_visual.schemas import JobContext  # noqa
        from layer1_input.schemas import SubjectEnum, CurriculumEnum, DifficultyEnum  # noqa

        redis = await _get_redis()
        job_data = await redis.hgetall(f"edu_video:job:{job_id}")

        def _decode(key: str, default: str = "[]") -> list:
            raw = job_data.get(key) or job_data.get(key.encode(), default)
            if isinstance(raw, bytes):
                raw = raw.decode()
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return []

        return JobContext(
            job_id=job_id,
            user_id=str(job_payload.get("user_id", "")),
            title=str(job_payload.get("title", "")),
            subject=SubjectEnum(job_payload.get("subject", "mathematics")),
            curriculum=CurriculumEnum(job_payload.get("curriculum", "general")),
            difficulty_level=DifficultyEnum(
                job_payload.get("difficulty_level", "intermediate")
            ),
            language=str(job_payload.get("language", "en")),
            curriculum_standards=_decode("curriculum_standards"),
            learning_objectives=_decode("learning_objectives"),
            total_scenes=scene_count,
        )

    async def _heartbeat_loop(self) -> None:
        redis = await _get_redis()
        while self._running:
            try:
                await redis.hset(
                    HEARTBEAT_KEY,
                    mapping={
                        "worker_id": self.worker_id,
                        "timestamp": utcnow().isoformat(),
                        "jobs_processed": self.stats.jobs_processed,
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
            await redis.srem(PROCESSING_SET_KEY, *self.stats.current_jobs or ["__noop__"])
        except Exception:
            pass

    def _update_avg_time(self, elapsed: float) -> None:
        n = self.stats.jobs_succeeded
        old_avg = self.stats.avg_processing_time_seconds
        self.stats.avg_processing_time_seconds = (
            (old_avg * (n - 1) + elapsed) / n if n > 0 else elapsed
        )


# --------------------------------------------------------------------------- #
# Signal handling + entrypoint                                                 #
# --------------------------------------------------------------------------- #

video_worker = VideoWorker()


def _handle_signal(signum, frame) -> None:
    logger.info("shutdown_signal_received", signal=signum)
    video_worker._running = False


async def _main() -> None:
    import structlog  # noqa

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )

    # Initialise Redis on startup
    global _redis_client  # noqa: PLW0603
    from core.database import _create_redis_client  # noqa
    _redis_client_local = await _create_redis_client()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    await video_worker.run()


async def _get_redis():
    from core.database import _redis_client  # noqa
    if _redis_client is None:
        return await _create_redis_client()
    return _redis_client


if __name__ == "__main__":
    asyncio.run(_main()) 

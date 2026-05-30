# products/edu_video/backend/layer6_delivery/analytics.py
"""
AnalyticsService: tracks per-job metrics, quality scores, cost breakdown,
and usage statistics. Stores in Redis for fast reads; references DB for
long-term lookups.
"""

import json
from collections import Counter
from datetime import datetime

import structlog
from pydantic import BaseModel

from core.config import get_settings
from core.database import AsyncSessionLocal, _redis_client
from core.utils import utcnow
from layer4_script_visual.schemas import FinalScenePackage
from layer5_rendering.compositor import RenderingResult
from layer5_rendering.quality_check import QualityReport
from models.job import Job

__all__ = [
    "AnalyticsService",
    "JobAnalyticsEvent",
    "UsageSummary",
    "analytics_service",
]

logger = structlog.get_logger(__name__)
settings = get_settings()


class JobAnalyticsEvent(BaseModel):
    event_type: str
    job_id: str
    user_id: str
    subject: str
    curriculum: str
    difficulty_level: str
    language: str
    scene_count: int
    total_duration_seconds: float
    total_cost_usd: float
    quality_score: float
    renderer_distribution: dict[str, int]
    tts_cost_usd: float
    render_cost_usd: float
    llm_cost_usd: float
    processing_time_seconds: float
    error_count: int
    timestamp: datetime


class UsageSummary(BaseModel):
    user_id: str
    period_start: datetime
    period_end: datetime
    jobs_created: int
    jobs_completed: int
    jobs_failed: int
    total_videos_seconds: float
    total_cost_usd: float
    avg_quality_score: float
    subjects_used: list[str]
    most_used_renderer: str


class AnalyticsService:
    """
    Records job-level analytics to Redis on completion.
    Provides aggregation methods for admin dashboard and usage reports.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(__name__)

    async def track_job_completion(
        self,
        job_id: str,
        user_id: str,
        rendering_result: RenderingResult,
        quality_report: QualityReport,
        packages: list[FinalScenePackage],
        processing_time_seconds: float,
    ) -> None:
        """Record a complete job analytics event to Redis."""
        log = self.log.bind(job_id=job_id, user_id=user_id)

        renderer_distribution = dict(
            Counter(pkg.renderer_type for pkg in packages)
        )

        # Sum costs from scene-level results
        tts_cost = sum(
            getattr(sr, "tts_cost_usd", 0.0)
            for sr in rendering_result.scene_render_results
        )
        render_cost = sum(
            getattr(sr, "render_cost_usd", 0.0)
            for sr in rendering_result.scene_render_results
        )
        llm_cost = await self._get_job_llm_cost(job_id)

        subject = packages[0].subject if packages else "unknown"
        curriculum = packages[0].curriculum if packages else "unknown"
        difficulty = packages[0].difficulty_level if packages else "unknown"
        language = packages[0].language if packages else "en"
        error_count = sum(
            1 for sr in rendering_result.scene_render_results
            if not sr.render_success
        )

        event = JobAnalyticsEvent(
            event_type="job_completed",
            job_id=job_id,
            user_id=user_id,
            subject=subject,
            curriculum=curriculum,
            difficulty_level=difficulty,
            language=language,
            scene_count=len(packages),
            total_duration_seconds=rendering_result.total_duration_seconds,
            total_cost_usd=rendering_result.total_cost_usd,
            quality_score=quality_report.overall_score,
            renderer_distribution=renderer_distribution,
            tts_cost_usd=tts_cost,
            render_cost_usd=render_cost,
            llm_cost_usd=llm_cost,
            processing_time_seconds=processing_time_seconds,
            error_count=error_count,
            timestamp=utcnow(),
        )

        await self._store_event(event, user_id)

        log.info(
            "analytics.job_completion_tracked",
            quality_score=event.quality_score,
            total_cost_usd=event.total_cost_usd,
            renderer_distribution=renderer_distribution,
            error_count=error_count,
        )

    async def track_event(
        self,
        event_type: str,
        job_id: str,
        user_id: str,
        metadata: dict | None = None,
    ) -> None:
        """Lightweight event tracker for non-completion events."""
        payload = {
            "event_type": event_type,
            "job_id": job_id,
            "user_id": user_id,
            "timestamp": utcnow().isoformat(),
            **(metadata or {}),
        }
        try:
            redis = await _get_redis()
            key = f"analytics:events:{event_type}"
            await redis.lpush(key, json.dumps(payload))
            await redis.ltrim(key, 0, 999)  # keep last 1000 per event type
        except Exception as exc:
            self.log.warning("analytics.event_track_failed", error=str(exc))

    async def get_user_summary(
        self,
        user_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> UsageSummary:
        """Return aggregated usage summary for a user over a time period."""
        try:
            redis = await _get_redis()
            raw_ids = await redis.lrange(
                f"analytics:user:{user_id}:events", 0, -1
            )

            events: list[JobAnalyticsEvent] = []
            for raw_id in raw_ids:
                job_id = raw_id if isinstance(raw_id, str) else raw_id.decode()
                raw = await redis.get(f"analytics:event:{job_id}")
                if raw:
                    try:
                        event = JobAnalyticsEvent.model_validate_json(raw)
                        if period_start <= event.timestamp <= period_end:
                            events.append(event)
                    except Exception:
                        continue

        except Exception as exc:
            self.log.error("analytics.get_user_summary_failed", error=str(exc))
            events = []

        if not events:
            return UsageSummary(
                user_id=user_id,
                period_start=period_start,
                period_end=period_end,
                jobs_created=0,
                jobs_completed=0,
                jobs_failed=0,
                total_videos_seconds=0.0,
                total_cost_usd=0.0,
                avg_quality_score=0.0,
                subjects_used=[],
                most_used_renderer="none",
            )

        all_renderers: Counter = Counter()
        for e in events:
            all_renderers.update(e.renderer_distribution)

        completed = sum(1 for e in events if e.event_type == "job_completed")
        failed = sum(1 for e in events if e.error_count > max(len(e.renderer_distribution) // 2, 1))

        return UsageSummary(
            user_id=user_id,
            period_start=period_start,
            period_end=period_end,
            jobs_created=len(events),
            jobs_completed=completed,
            jobs_failed=failed,
            total_videos_seconds=sum(e.total_duration_seconds for e in events),
            total_cost_usd=sum(e.total_cost_usd for e in events),
            avg_quality_score=sum(e.quality_score for e in events) / len(events),
            subjects_used=list({e.subject for e in events}),
            most_used_renderer=(
                all_renderers.most_common(1)[0][0] if all_renderers else "none"
            ),
        )

    async def get_global_stats(self) -> dict:
        """Return platform-wide aggregated stats from Redis counters."""
        try:
            redis = await _get_redis()
            jobs_raw = await redis.get("analytics:global:jobs_completed")
            cost_raw = await redis.get("analytics:global:total_cost_usd")
            return {
                "total_jobs_completed": int(jobs_raw or 0),
                "total_cost_usd": float(cost_raw or 0.0),
                "timestamp": utcnow().isoformat(),
            }
        except Exception as exc:
            self.log.error("analytics.global_stats_failed", error=str(exc))
            return {"total_jobs_completed": 0, "total_cost_usd": 0.0, "timestamp": utcnow().isoformat()}

    async def _store_event(self, event: JobAnalyticsEvent, user_id: str) -> None:
        """Write event to Redis with TTL."""
        ttl = settings.ANALYTICS_REDIS_TTL_DAYS * 86400
        try:
            redis = await _get_redis()
            await redis.setex(
                f"analytics:event:{event.job_id}",
                ttl,
                event.model_dump_json(),
            )
            await redis.lpush(
                f"analytics:user:{user_id}:events", event.job_id
            )
            await redis.expire(f"analytics:user:{user_id}:events", ttl)
            await redis.incr("analytics:global:jobs_completed")
            await redis.incrbyfloat(
                "analytics:global:total_cost_usd", event.total_cost_usd
            )
        except Exception as exc:
            self.log.error("analytics.store_event_failed", error=str(exc))

    async def _get_job_llm_cost(self, job_id: str) -> float:
        """Estimate LLM cost as ~60% of total job cost (rough heuristic)."""
        try:
            async with AsyncSessionLocal() as session:
                job = await session.get(Job, job_id)
                if job and job.total_cost_usd:
                    return float(job.total_cost_usd) * 0.6
        except Exception:
            pass
        return 0.0


async def _get_redis():
    """Return the shared Redis client."""
    from core.database import _redis_client  # noqa: PLC0415
    if _redis_client is None:
        from core.database import _create_redis_client  # noqa: PLC0415
        return await _create_redis_client()
    return _redis_client


analytics_service = AnalyticsService()

# products/edu_video/backend/layer6_delivery/review/correction_log.py
"""
CorrectionLogService: records factual errors and quality issues that slipped
through the pipeline. Logs are used to:
  1. Feed back into RAG (ingesting corrections as authoritative knowledge)
  2. Track error patterns for pipeline improvement
  3. Alert admin when systematic errors are detected
"""

import json
from datetime import datetime

import structlog
from pydantic import BaseModel
from sqlalchemy import select

from core.database import AsyncSessionLocal, _redis_client
from core.utils import generate_uuid, utcnow
from models.job import Job

__all__ = [
    "CorrectionLogService",
    "CorrectionEntry",
    "correction_log_service",
]

logger = structlog.get_logger(__name__)

_CORRECTIONS_REDIS_KEY = "edu_video:correction_log"
_MAX_LOG_SIZE = 5000   # keep last 5000 corrections in Redis
_SYSTEMATIC_ERROR_THRESHOLD = 3  # same error code N times → alert


class CorrectionEntry(BaseModel):
    correction_id: str
    job_id: str
    scene_index: int | None
    subject: str
    curriculum: str
    error_type: str
    reported_error: str
    corrected_content: str | None = None
    ingested_to_rag: bool = False
    logged_at: datetime
    source: str    # "user_feedback" | "reviewer" | "auto_validator"


class CorrectionLogService:
    """
    Central log for pipeline errors that reached the delivery stage.
    Stores in Redis (fast access) and optionally feeds corrections to RAG.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(__name__)

    async def log_correction(
        self,
        job_id: str,
        scene_index: int | None,
        reported_error: str,
        error_type: str,
        corrected_content: str | None = None,
        source: str = "user_feedback",
    ) -> CorrectionEntry:
        """
        Record a correction entry and optionally ingest it into the RAG knowledge base.
        """
        log = self.log.bind(job_id=job_id, error_type=error_type)

        # Load job metadata for context
        subject, curriculum = await self._get_job_metadata(job_id)

        entry = CorrectionEntry(
            correction_id=generate_uuid(),
            job_id=job_id,
            scene_index=scene_index,
            subject=subject,
            curriculum=curriculum,
            error_type=error_type,
            reported_error=reported_error[:2000],
            corrected_content=corrected_content,
            ingested_to_rag=False,
            logged_at=utcnow(),
            source=source,
        )

        # ---- Persist to Redis ------------------------------------------- #
        try:
            redis = _redis_client
            if redis:
                await redis.lpush(
                    _CORRECTIONS_REDIS_KEY,
                    entry.model_dump_json(),
                )
                await redis.ltrim(_CORRECTIONS_REDIS_KEY, 0, _MAX_LOG_SIZE - 1)
                await redis.incr(f"corrections:by_type:{error_type}")
                log.info(
                    "correction_log.entry_stored",
                    correction_id=entry.correction_id,
                    source=source,
                )
        except Exception as exc:
            log.error("correction_log.redis_failed", error=str(exc))

        # ---- Check for systematic errors -------------------------------- #
        await self._check_systematic_pattern(error_type, log)

        # ---- Ingest factual corrections to RAG -------------------------- #
        if corrected_content and error_type in (
            "user_reported_factual_error", "reviewer_correction", "factual_error"
        ):
            await self._ingest_correction_to_rag(entry, log)

        return entry

    async def get_recent_corrections(
        self, limit: int = 50
    ) -> list[CorrectionEntry]:
        """Return the most recent correction entries from Redis."""
        try:
            redis = _redis_client
            if not redis:
                return []
            raw_entries = await redis.lrange(_CORRECTIONS_REDIS_KEY, 0, limit - 1)
            entries = []
            for raw in raw_entries:
                try:
                    entries.append(CorrectionEntry.model_validate_json(raw))
                except Exception:
                    continue
            return entries
        except Exception as exc:
            self.log.error("correction_log.get_failed", error=str(exc))
            return []

    async def get_error_type_counts(self) -> dict[str, int]:
        """Return counts per error type for admin monitoring."""
        try:
            redis = _redis_client
            if not redis:
                return {}
            known_types = [
                "user_reported_factual_error", "reviewer_correction",
                "factual_error", "curriculum_mismatch", "poor_quality",
                "inappropriate_content", "other",
            ]
            counts = {}
            for error_type in known_types:
                raw = await redis.get(f"corrections:by_type:{error_type}")
                counts[error_type] = int(raw or 0)
            return counts
        except Exception as exc:
            self.log.error("correction_log.counts_failed", error=str(exc))
            return {}

    async def _check_systematic_pattern(
        self, error_type: str, log
    ) -> None:
        """
        Alert if the same error type exceeds the systematic threshold.
        In production this would trigger a Slack/email notification.
        """
        try:
            redis = _redis_client
            if not redis:
                return
            count_raw = await redis.get(f"corrections:by_type:{error_type}")
            count = int(count_raw or 0)
            if count > 0 and count % _SYSTEMATIC_ERROR_THRESHOLD == 0:
                log.warning(
                    "correction_log.systematic_error_detected",
                    error_type=error_type,
                    count=count,
                    alert="Systematic error pattern — review pipeline configuration.",
                )
        except Exception:
            pass

    async def _ingest_correction_to_rag(
        self, entry: CorrectionEntry, log
    ) -> None:
        """
        Ingest the correction as a new document into Qdrant via the ingestion pipeline.
        This closes the feedback loop: corrections become authoritative knowledge.
        """
        try:
            from layer3_rag.ingestion.pipeline import (  # noqa: PLC0415
                IngestionPipeline,
                IngestionSource,
            )
            from layer1_input.schemas import (  # noqa: PLC0415
                SubjectEnum,
                CurriculumEnum,
                DifficultyEnum,
            )

            content = (
                f"CORRECTION — {entry.error_type}\n"
                f"Original error: {entry.reported_error}\n"
                f"Corrected content: {entry.corrected_content}"
            )

            try:
                subject = SubjectEnum(entry.subject)
            except ValueError:
                subject = SubjectEnum.mathematics
            try:
                curriculum = CurriculumEnum(entry.curriculum)
            except ValueError:
                curriculum = CurriculumEnum.general

            source = IngestionSource(
                source_type="text",
                content=content,
                subject=subject,
                curriculum=curriculum,
                difficulty_level=DifficultyEnum.intermediate,
                source_name=f"correction_{entry.correction_id}",
                metadata={
                    "correction_id": entry.correction_id,
                    "job_id": entry.job_id,
                    "error_type": entry.error_type,
                    "is_correction": True,
                },
            )
            pipeline = IngestionPipeline()
            result = await pipeline.ingest(source)
            if result.success:
                log.info(
                    "correction_log.ingested_to_rag",
                    correction_id=entry.correction_id,
                    chunks=result.chunks_created,
                )
        except Exception as exc:
            log.warning("correction_log.rag_ingest_failed", error=str(exc))

    async def _get_job_metadata(self, job_id: str) -> tuple[str, str]:
        """Return (subject, curriculum) from job DB record."""
        try:
            async with AsyncSessionLocal() as session:
                job = await session.get(Job, job_id)
                if job:
                    return str(job.subject), str(job.curriculum)
        except Exception:
            pass
        return "unknown", "general"


correction_log_service = CorrectionLogService()

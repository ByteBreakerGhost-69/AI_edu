# products/edu_video/backend/layer6_delivery/cdn_service.py
"""
CDNService: finalizes GCS blob metadata, generates CDN-optimized and signed URLs,
and updates Job + Scene DB records with final delivery URLs.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from google.cloud import storage
from pydantic import BaseModel
from sqlalchemy import select

from core.config import get_settings
from core.database import AsyncSessionLocal
from core.utils import utcnow
from layer4_script_visual.schemas import FinalScenePackage
from layer5_rendering.compositor import RenderingResult
from layer5_rendering.quality_check import QualityIssueSeverity, QualityReport
from models.job import Job
from models.scene import Scene

__all__ = ["CDNService", "DeliveryResult", "cdn_service"]

logger = structlog.get_logger(__name__)
settings = get_settings()


class DeliveryResult(BaseModel):
    job_id: str
    public_video_url: str
    public_thumbnail_url: str
    subtitle_srt_url: str
    subtitle_vtt_url: str
    signed_video_url: str
    signed_expiry: datetime
    cdn_headers: dict
    delivery_status: str      # "delivered" | "review_required" | "failed"
    review_required: bool
    delivered_at: datetime


class CDNService:
    """
    Wraps GCS operations for delivery finalisation.
    All GCS calls are synchronous — wrapped in executor throughout.
    """

    def __init__(self) -> None:
        self._gcs_client: storage.Client | None = None
        self.log = structlog.get_logger(__name__)

    def _client(self) -> storage.Client:
        if self._gcs_client is None:
            self._gcs_client = storage.Client()
        return self._gcs_client

    async def finalize_delivery(
        self,
        rendering_result: RenderingResult,
        quality_report: QualityReport,
        packages: list[FinalScenePackage],
        job_id: str,
    ) -> DeliveryResult:
        """
        Determine delivery status, set blob metadata, generate URLs,
        update DB records, and return a DeliveryResult.
        """
        log = self.log.bind(job_id=job_id)
        log.info("cdn_service.finalize_started")

        # ---- Step 1: Determine delivery status -------------------------- #
        has_critical = any(
            i.severity == QualityIssueSeverity.CRITICAL
            for i in quality_report.issues
        )

        if has_critical:
            delivery_status = "review_required"
            review_required = True
        elif not quality_report.passed:
            # Warnings only — deliverable with flag
            delivery_status = "delivered"
            review_required = False
        elif quality_report.overall_score < settings.REVIEW_AUTO_APPROVE_THRESHOLD:
            delivery_status = "review_required"
            review_required = True
        else:
            delivery_status = "delivered"
            review_required = False

        log.info(
            "cdn_service.delivery_status",
            status=delivery_status,
            score=quality_report.overall_score,
        )

        # ---- Step 2: Set GCS blob cache headers ------------------------- #
        cdn_headers = {
            "Cache-Control": "public, max-age=86400",
            "Content-Disposition": f"inline; filename={job_id}_video.mp4",
        }

        gcs_urls = [
            rendering_result.final_video_url,
            rendering_result.thumbnail_url,
        ]
        for url in gcs_urls:
            if url:
                try:
                    await self._set_blob_metadata(url, cdn_headers)
                except Exception as exc:
                    log.warning(
                        "cdn_service.metadata_set_failed",
                        url=url,
                        error=str(exc),
                    )

        # ---- Step 3: Generate CDN URLs ---------------------------------- #
        public_video_url = self._gcs_to_cdn(rendering_result.final_video_url)
        public_thumbnail_url = self._gcs_to_cdn(rendering_result.thumbnail_url)
        srt_url = self._gcs_to_cdn(rendering_result.subtitle_srt_url)
        vtt_url = self._gcs_to_cdn(rendering_result.subtitle_vtt_url)

        # ---- Step 4: Generate signed URL -------------------------------- #
        try:
            signed_url = await self._generate_signed_url(
                rendering_result.final_video_url,
                expiry_hours=settings.GCS_SIGNED_URL_EXPIRY_HOURS,
            )
        except Exception as exc:
            log.warning("cdn_service.signed_url_failed", error=str(exc))
            signed_url = public_video_url

        signed_expiry = utcnow() + timedelta(hours=settings.GCS_SIGNED_URL_EXPIRY_HOURS)

        # ---- Step 5: Update DB records ---------------------------------- #
        await self._update_db_records(
            job_id=job_id,
            rendering_result=rendering_result,
            packages=packages,
            public_video_url=public_video_url,
            public_thumbnail_url=public_thumbnail_url,
            review_required=review_required,
        )

        # ---- Step 6: Return --------------------------------------------- #
        result = DeliveryResult(
            job_id=job_id,
            public_video_url=public_video_url,
            public_thumbnail_url=public_thumbnail_url,
            subtitle_srt_url=srt_url,
            subtitle_vtt_url=vtt_url,
            signed_video_url=signed_url,
            signed_expiry=signed_expiry,
            cdn_headers=cdn_headers,
            delivery_status=delivery_status,
            review_required=review_required,
            delivered_at=utcnow(),
        )

        log.info(
            "cdn_service.finalize_done",
            delivery_status=delivery_status,
            public_url=public_video_url,
        )
        return result

    def _gcs_to_cdn(self, gcs_url: str | None) -> str:
        """Replace GCS storage URL prefix with CDN base URL if configured."""
        if not gcs_url:
            return ""
        if not settings.CDN_BASE_URL:
            return gcs_url
        bucket_prefix = (
            f"https://storage.googleapis.com/{settings.GCS_BUCKET_NAME}/"
        )
        if gcs_url.startswith(bucket_prefix):
            path = gcs_url[len(bucket_prefix):]
            return f"{settings.CDN_BASE_URL.rstrip('/')}/{path}"
        return gcs_url

    async def _set_blob_metadata(self, gcs_url: str, metadata: dict) -> None:
        """Set GCS blob metadata headers in executor."""
        bucket_prefix = (
            f"https://storage.googleapis.com/{settings.GCS_BUCKET_NAME}/"
        )
        blob_path = gcs_url.replace(bucket_prefix, "")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._set_blob_metadata_sync(blob_path, metadata),
        )

    def _set_blob_metadata_sync(self, blob_path: str, metadata: dict) -> None:
        bucket = self._client().bucket(settings.GCS_BUCKET_NAME)
        blob = bucket.blob(blob_path)
        blob.metadata = metadata
        blob.patch()

    async def _generate_signed_url(self, gcs_url: str, expiry_hours: int) -> str:
        """Generate a V4 signed URL for time-limited private access."""
        bucket_prefix = (
            f"https://storage.googleapis.com/{settings.GCS_BUCKET_NAME}/"
        )
        blob_path = gcs_url.replace(bucket_prefix, "")
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._generate_signed_url_sync(blob_path, expiry_hours),
        )

    def _generate_signed_url_sync(self, blob_path: str, expiry_hours: int) -> str:
        bucket = self._client().bucket(settings.GCS_BUCKET_NAME)
        blob = bucket.blob(blob_path)
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(hours=expiry_hours),
            method="GET",
        )

    async def _update_db_records(
        self,
        job_id: str,
        rendering_result: RenderingResult,
        packages: list[FinalScenePackage],
        public_video_url: str,
        public_thumbnail_url: str,
        review_required: bool,
    ) -> None:
        """Update Job and Scene records with final delivery URLs."""
        log = self.log.bind(job_id=job_id)
        try:
            async with AsyncSessionLocal() as session:
                # Update Job
                job = await session.get(Job, job_id)
                if job:
                    job.video_url = public_video_url
                    job.thumbnail_url = public_thumbnail_url
                    job.status = "review" if review_required else "done"
                    job.completed_at = None if review_required else utcnow()
                    job.duration_seconds = int(
                        rendering_result.total_duration_seconds
                    )
                    job.total_cost_usd = rendering_result.total_cost_usd  # type: ignore
                    await session.flush()

                # Update Scenes
                for pkg in packages:
                    result = await session.execute(
                        select(Scene)
                        .where(Scene.job_id == job_id)
                        .where(Scene.scene_index == pkg.scene_index)
                    )
                    scene = result.scalar_one_or_none()
                    if scene:
                        scene.animation_url = public_video_url
                        scene.subtitle_srt = rendering_result.subtitle_srt_url
                        scene.status = "done"
                        await session.flush()

                await session.commit()
                log.info("cdn_service.db_updated")

        except Exception as exc:
            log.error("cdn_service.db_update_failed", error=str(exc))


cdn_service = CDNService()

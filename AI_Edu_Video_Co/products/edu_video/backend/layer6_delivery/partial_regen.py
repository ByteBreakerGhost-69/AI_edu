# products/edu_video/backend/layer6_delivery/partial_regen.py
"""
PartialRegenService: re-renders specific failed or user-flagged scenes
by re-running them through Layers 4 and 5, then updating GCS + DB records.

Called by:
  - feedback_service (poor_animation, audio_issue)
  - review worker (after reviewer marks scenes for correction)
  - video_worker (on partial failure during initial render)
"""

import asyncio
import time

import structlog
from pydantic import BaseModel
from sqlalchemy import select

from core.config import get_settings
from core.database import AsyncSessionLocal
from core.utils import utcnow
from layer4_script_visual.schemas import FinalScenePackage, JobContext
from layer5_rendering.animation_router import AnimationRouter
from layer5_rendering.tts_service import TTSService
from layer5_rendering.timing_sync import TimingSync
from models.job import Job
from models.scene import Scene

__all__ = [
    "PartialRegenService",
    "PartialRegenRequest",
    "PartialRegenResult",
    "partial_regen_service",
]

logger = structlog.get_logger(__name__)
settings = get_settings()


class PartialRegenRequest(BaseModel):
    job_id: str
    scene_indices: list[int]
    reason: str
    retry_count: int = 0


class PartialRegenResult(BaseModel):
    job_id: str
    scene_indices_attempted: list[int]
    scene_indices_succeeded: list[int]
    scene_indices_failed: list[int]
    total_cost_usd: float
    processing_time_seconds: float
    errors: list[str]


class PartialRegenService:
    """
    Selectively re-renders scenes without reprocessing the entire job.
    Reuses existing orchestrator output (GraphState is not re-run).
    Only Layers 4 + 5 are re-executed per scene.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(__name__)
        self._animation_router = AnimationRouter()
        self._tts_service = TTSService()
        self._timing_sync = TimingSync()

    async def regenerate(self, request: PartialRegenRequest) -> PartialRegenResult:
        """
        Re-run Layers 4 + 5 for the specified scene indices.
        Updates DB scene records and GCS on success.
        """
        log = self.log.bind(
            job_id=request.job_id,
            scene_indices=request.scene_indices,
            reason=request.reason,
        )
        log.info("partial_regen.started")
        t0 = time.perf_counter()

        if request.retry_count >= settings.PARTIAL_REGEN_MAX_RETRIES:
            log.warning(
                "partial_regen.max_retries_exceeded",
                retry_count=request.retry_count,
            )
            return PartialRegenResult(
                job_id=request.job_id,
                scene_indices_attempted=request.scene_indices,
                scene_indices_succeeded=[],
                scene_indices_failed=request.scene_indices,
                total_cost_usd=0.0,
                processing_time_seconds=0.0,
                errors=["max_retries_exceeded"],
            )

        # ---- Load existing job + scene packages from DB ----------------- #
        packages, job_context = await self._load_packages_from_db(
            request.job_id, request.scene_indices, log
        )

        if not packages:
            return PartialRegenResult(
                job_id=request.job_id,
                scene_indices_attempted=request.scene_indices,
                scene_indices_succeeded=[],
                scene_indices_failed=request.scene_indices,
                total_cost_usd=0.0,
                processing_time_seconds=0.0,
                errors=["no_packages_loaded_from_db"],
            )

        # ---- Layer 4: re-run script + visual generation ----------------- #
        try:
            from layer4_script_visual.difficulty_adapter import difficulty_adapter  # noqa
            from layer4_script_visual.language_localizer import language_localizer  # noqa
            from layer4_script_visual.script_generator import script_generator  # noqa
            from layer4_script_visual.visual_asset_generator import visual_asset_generator  # noqa
            from layer4_script_visual.schemas import SceneInput  # noqa
            from layer1_input.schemas import DifficultyEnum, SubjectEnum  # noqa

            # Convert DB scenes to SceneInput
            scene_inputs = [
                _package_to_scene_input(pkg) for pkg in packages
            ]

            difficulty = DifficultyEnum(job_context.difficulty_level)
            subject = SubjectEnum(job_context.subject)

            adapted = await difficulty_adapter.adapt(
                scene_inputs, difficulty, subject, request.job_id
            )
            localized = await language_localizer.localize(
                adapted, job_context.language, subject, request.job_id
            )
            refined_scripts = await script_generator.generate(localized, job_context)
            layer4_result = await visual_asset_generator.generate(
                refined_scripts, job_context
            )
            regen_packages = layer4_result.scene_packages

        except Exception as exc:
            log.error("partial_regen.layer4_failed", error=str(exc))
            return PartialRegenResult(
                job_id=request.job_id,
                scene_indices_attempted=request.scene_indices,
                scene_indices_succeeded=[],
                scene_indices_failed=request.scene_indices,
                total_cost_usd=0.0,
                processing_time_seconds=time.perf_counter() - t0,
                errors=[f"layer4_failed: {exc}"],
            )

        # ---- Layer 5: re-render and re-TTS ------------------------------ #
        succeeded: list[int] = []
        failed: list[int] = []
        all_errors: list[str] = []
        total_cost = layer4_result.total_cost_usd

        tts_results = await self._tts_service.synthesize_all(
            regen_packages, request.job_id
        )
        renderer_results = await self._animation_router.render_all(
            regen_packages, request.job_id
        )
        synced_scenes = await self._timing_sync.sync_all(
            tts_results, renderer_results, request.job_id
        )

        tts_map = {r.scene_index: r for r in tts_results}
        render_map = {r.scene_index: r for r in renderer_results}
        sync_map = {s.scene_index: s for s in synced_scenes}

        for pkg in regen_packages:
            idx = pkg.scene_index
            render = render_map.get(idx)
            synced = sync_map.get(idx)

            if render and render.success:
                # Upload re-rendered scene to GCS
                new_video_url = await self._upload_scene_video(
                    render.video_file_path,
                    request.job_id,
                    idx,
                )
                total_cost += render.cost_usd

                # Update DB Scene record
                await self._update_scene_record(
                    job_id=request.job_id,
                    scene_index=idx,
                    video_url=new_video_url,
                    audio_url=tts_map.get(idx, {}).audio_file_path if tts_map.get(idx) else None,
                    duration=synced.final_duration_seconds if synced else pkg.estimated_duration_seconds,
                    log=log,
                )
                succeeded.append(idx)
                log.info("partial_regen.scene_succeeded", scene_index=idx)
            else:
                err = render.error if render else "render_result_missing"
                failed.append(idx)
                all_errors.append(f"scene_{idx}: {err}")
                log.error("partial_regen.scene_failed", scene_index=idx, error=err)

        duration = round(time.perf_counter() - t0, 2)
        log.info(
            "partial_regen.completed",
            succeeded=len(succeeded),
            failed=len(failed),
            duration_seconds=duration,
        )

        return PartialRegenResult(
            job_id=request.job_id,
            scene_indices_attempted=request.scene_indices,
            scene_indices_succeeded=succeeded,
            scene_indices_failed=failed,
            total_cost_usd=round(total_cost, 6),
            processing_time_seconds=duration,
            errors=all_errors,
        )

    async def _load_packages_from_db(
        self,
        job_id: str,
        scene_indices: list[int],
        log,
    ) -> tuple[list[FinalScenePackage], "JobContext"]:
        """Reconstruct FinalScenePackages from DB scene records."""
        from layer4_script_visual.schemas import (  # noqa: PLC0415
            JobContext, RefinedScript, VisualSpec, TTSInstructions,
        )
        from layer1_input.schemas import (  # noqa: PLC0415
            SubjectEnum, CurriculumEnum, DifficultyEnum,
        )

        packages: list[FinalScenePackage] = []
        job_context: JobContext | None = None

        try:
            async with AsyncSessionLocal() as session:
                job = await session.get(Job, job_id)
                if not job:
                    log.error("partial_regen.job_not_found")
                    return [], _empty_job_context(job_id)

                job_context = JobContext(
                    job_id=job_id,
                    user_id=str(job.user_id),
                    title=job.title,
                    subject=SubjectEnum(job.subject),
                    curriculum=CurriculumEnum(job.curriculum),
                    difficulty_level=DifficultyEnum(job.difficulty_level),
                    language=job.language or "en",
                    curriculum_standards=[],
                    learning_objectives=[],
                    total_scenes=len(scene_indices),
                )

                result = await session.execute(
                    select(Scene)
                    .where(Scene.job_id == job_id)
                    .where(Scene.scene_index.in_(scene_indices))
                )
                db_scenes = result.scalars().all()

                for scene in db_scenes:
                    tts_instr = TTSInstructions(language_code="en-US")
                    refined = RefinedScript(
                        scene_index=scene.scene_index,
                        title=scene.title or f"Scene {scene.scene_index}",
                        narration_text=scene.narration_text,
                        narration_ssml=f"<speak>{scene.narration_text}</speak>",
                        hook_sentence=scene.narration_text[:100],
                        key_terms=[],
                        estimated_word_count=len(scene.narration_text.split()),
                        estimated_duration_seconds=scene.duration_seconds or 30.0,
                        tts_instructions=tts_instr,
                    )
                    meta = scene.render_metadata or {}
                    visual = VisualSpec(
                        renderer_type=scene.renderer_type or "lottie",
                        primary_content=str(meta.get("primary_content", "")),
                        secondary_content=meta.get("secondary_content"),
                        color_palette=meta.get("color_hints", []),
                        dimensions={"width": 1920, "height": 1080},
                        animation_config=meta,
                        asset_references=[],
                        generation_prompt=meta.get("generation_prompt"),
                    )
                    pkg = FinalScenePackage(
                        scene_index=scene.scene_index,
                        title=refined.title,
                        refined_script=refined,
                        visual_spec=visual,
                        renderer_type=scene.renderer_type or "lottie",
                        estimated_duration_seconds=scene.duration_seconds or 30.0,
                        subject=job.subject,
                        curriculum=job.curriculum,
                        difficulty_level=job.difficulty_level,
                        language=job.language or "en",
                        metadata={
                            "job_id": job_id,
                            "user_id": str(job.user_id),
                        },
                    )
                    packages.append(pkg)

        except Exception as exc:
            log.error("partial_regen.load_packages_failed", error=str(exc))

        return packages, job_context or _empty_job_context(job_id)

    async def _upload_scene_video(
        self, local_path: str, job_id: str, scene_index: int
    ) -> str:
        """Upload a re-rendered scene MP4 to GCS and return the URL."""
        from google.cloud import storage  # noqa: PLC0415

        gcs_path = (
            f"{settings.GCS_OUTPUT_PREFIX}{job_id}"
            f"/scenes/scene_{scene_index:02d}_regen.mp4"
        )

        def _upload() -> str:
            client = storage.Client()
            bucket = client.bucket(settings.GCS_BUCKET_NAME)
            blob = bucket.blob(gcs_path)
            blob.upload_from_filename(local_path, content_type="video/mp4")
            return (
                f"https://storage.googleapis.com/{settings.GCS_BUCKET_NAME}/{gcs_path}"
            )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _upload)

    async def _update_scene_record(
        self,
        job_id: str,
        scene_index: int,
        video_url: str,
        audio_url: str | None,
        duration: float,
        log,
    ) -> None:
        """Update the Scene DB record with re-rendered URLs."""
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Scene)
                    .where(Scene.job_id == job_id)
                    .where(Scene.scene_index == scene_index)
                )
                scene = result.scalar_one_or_none()
                if scene:
                    scene.animation_url = video_url
                    if audio_url:
                        scene.audio_url = audio_url
                    scene.duration_seconds = duration
                    scene.status = "done"
                    scene.updated_at = utcnow()
                    await session.commit()
        except Exception as exc:
            log.error(
                "partial_regen.db_update_failed",
                scene_index=scene_index,
                error=str(exc),
            )


def _package_to_scene_input(pkg: FinalScenePackage):
    """Convert a FinalScenePackage back to a SceneInput for Layer 4 re-run."""
    from layer4_script_visual.schemas import SceneInput  # noqa: PLC0415

    return SceneInput(
        scene_index=pkg.scene_index,
        title=pkg.title,
        narration_text=pkg.refined_script.narration_text,
        visual_description=pkg.visual_spec.primary_content or "",
        renderer_type=pkg.renderer_type,
        duration_seconds=pkg.estimated_duration_seconds,
        render_metadata=pkg.visual_spec.animation_config,
        fact_checked=True,
        llm_cost_usd=0.0,
    )


def _empty_job_context(job_id: str):
    """Minimal fallback JobContext when DB load fails."""
    from layer4_script_visual.schemas import JobContext  # noqa: PLC0415
    from layer1_input.schemas import SubjectEnum, CurriculumEnum, DifficultyEnum  # noqa: PLC0415

    return JobContext(
        job_id=job_id,
        user_id="unknown",
        title="Regenerated Job",
        subject=SubjectEnum.mathematics,
        curriculum=CurriculumEnum.general,
        difficulty_level=DifficultyEnum.intermediate,
        language="en",
        curriculum_standards=[],
        learning_objectives=[],
        total_scenes=0,
    )


partial_regen_service = PartialRegenService()

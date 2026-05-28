# products/edu_video/backend/layer5_rendering/compositor.py
"""
Compositor: merges per-scene audio + video → scene MP4s, then concatenates
all scenes into a final MP4. Uploads to GCS and returns URLs for Layer 6.

Pipeline per scene:
  synced_scene.video_file_path + synced_scene.audio_file_path
    → FFmpeg mux → /tmp/{job_id}/composed/scene_NN.mp4

Final composition:
  scene_00.mp4 + scene_01.mp4 + ... → FFmpeg concat → final_{job_id}.mp4
  → GCS upload → return GCS URL

Thumbnail:
  First frame of scene_00.mp4 → thumbnail_{job_id}.jpg → GCS
"""

import asyncio
import shutil
import time
from pathlib import Path

import structlog
from pydantic import BaseModel

from core.config import get_settings
from core.utils import generate_uuid, utcnow
from layer4_script_visual.schemas import FinalScenePackage
from layer5_rendering.animation_router import RendererResult
from layer5_rendering.subtitle_generator import SubtitleResult
from layer5_rendering.timing_sync import SyncedScene
from layer5_rendering.tts_service import TTSResult

__all__ = ["Compositor", "RenderingResult", "SceneRenderResult", "compositor"]

logger = structlog.get_logger(__name__)
settings = get_settings()

_MAX_COMPOSE_CONCURRENCY = 4  # per-scene mux concurrency


# --------------------------------------------------------------------------- #
# Pydantic models                                                              #
# --------------------------------------------------------------------------- #

class SceneRenderResult(BaseModel):
    """Per-scene rendering outcome summary."""
    scene_index: int
    composed_file_path: str
    duration_seconds: float
    renderer_used: str
    tts_success: bool
    render_success: bool
    sync_method: str


class RenderingResult(BaseModel):
    """Primary output of Layer 5 — consumed by Layer 6 Delivery."""
    job_id: str
    final_video_url: str          # GCS URL of composited MP4
    thumbnail_url: str            # GCS URL of JPEG thumbnail
    subtitle_srt_url: str         # GCS URL of SRT file
    subtitle_vtt_url: str         # GCS URL of VTT file
    total_duration_seconds: float
    scene_render_results: list[SceneRenderResult]
    quality_passed: bool = False  # set by quality_check layer
    total_cost_usd: float
    processing_time_seconds: float


# --------------------------------------------------------------------------- #
# Compositor                                                                   #
# --------------------------------------------------------------------------- #

class Compositor:
    """
    FFmpeg-based compositor.
    Muxes audio+video per scene concurrently, then concatenates to final MP4.
    Uploads final assets to GCS and cleans up temp files.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(__name__)

    async def compose(
        self,
        packages: list[FinalScenePackage],
        synced_scenes: list[SyncedScene],
        tts_results: list[TTSResult],
        renderer_results: list[RendererResult],
        subtitle_result: SubtitleResult,
        job_id: str,
    ) -> RenderingResult:
        """
        Full composition pipeline:
          1. Mux audio+video per scene (concurrent)
          2. Concatenate all scenes to final MP4
          3. Extract thumbnail from scene 0
          4. Upload final MP4 + thumbnail + subtitles to GCS
          5. Clean up temp dir
          6. Return RenderingResult
        """
        t0 = time.perf_counter()
        log = self.log.bind(job_id=job_id, scene_count=len(packages))
        log.info("compositor.started")

        composed_dir = Path(settings.RENDER_TEMP_DIR) / job_id / "composed"
        composed_dir.mkdir(parents=True, exist_ok=True)

        # Build lookup maps
        synced_map = {s.scene_index: s for s in synced_scenes}
        tts_map = {r.scene_index: r for r in tts_results}
        render_map = {r.scene_index: r for r in renderer_results}

        # ---- Step 1: Mux per scene (concurrent) ------------------------- #
        semaphore = asyncio.Semaphore(_MAX_COMPOSE_CONCURRENCY)

        async def _mux_one(pkg: FinalScenePackage) -> SceneRenderResult:
            async with semaphore:
                return await self._mux_scene(
                    pkg=pkg,
                    synced=synced_map.get(pkg.scene_index),
                    tts=tts_map.get(pkg.scene_index),
                    render=render_map.get(pkg.scene_index),
                    composed_dir=composed_dir,
                    job_id=job_id,
                )

        mux_outcomes = await asyncio.gather(
            *[_mux_one(pkg) for pkg in sorted(packages, key=lambda p: p.scene_index)],
            return_exceptions=True,
        )

        scene_results: list[SceneRenderResult] = []
        for pkg, outcome in zip(
            sorted(packages, key=lambda p: p.scene_index), mux_outcomes
        ):
            if isinstance(outcome, Exception):
                log.error(
                    "compositor.mux_failed",
                    scene_index=pkg.scene_index,
                    error=str(outcome),
                )
                # Attempt silent fallback — black screen for this scene
                fallback_path = await self._compose_fallback_scene(
                    pkg, composed_dir
                )
                scene_results.append(SceneRenderResult(
                    scene_index=pkg.scene_index,
                    composed_file_path=fallback_path,
                    duration_seconds=pkg.estimated_duration_seconds,
                    renderer_used="fallback",
                    tts_success=False,
                    render_success=False,
                    sync_method="no_change",
                ))
            else:
                scene_results.append(outcome)

        scene_results.sort(key=lambda r: r.scene_index)

        # ---- Step 2: Concatenate to final MP4 --------------------------- #
        final_mp4_path = (
            Path(settings.RENDER_TEMP_DIR) / job_id / f"final_{job_id}.mp4"
        )
        composed_paths = [r.composed_file_path for r in scene_results]

        await self._concatenate_scenes(composed_paths, str(final_mp4_path), job_id)

        total_duration = sum(r.duration_seconds for r in scene_results)

        # Hard cap check
        if total_duration > settings.MAX_VIDEO_DURATION_SECONDS:
            log.warning(
                "compositor.duration_exceeded_cap",
                total=total_duration,
                cap=settings.MAX_VIDEO_DURATION_SECONDS,
            )

        # ---- Step 3: Extract thumbnail ---------------------------------- #
        thumbnail_path = (
            Path(settings.RENDER_TEMP_DIR) / job_id / f"thumbnail_{job_id}.jpg"
        )
        if composed_paths:
            await self._extract_thumbnail(composed_paths[0], str(thumbnail_path))
        else:
            await self._generate_blank_thumbnail(str(thumbnail_path))

        # ---- Step 4: Upload to GCS -------------------------------------- #
        final_video_url = await self._upload_to_gcs(
            str(final_mp4_path),
            f"{settings.GCS_OUTPUT_PREFIX}{job_id}/final.mp4",
            "video/mp4",
        )
        thumbnail_url = await self._upload_to_gcs(
            str(thumbnail_path),
            f"{settings.GCS_OUTPUT_PREFIX}{job_id}/thumbnail.jpg",
            "image/jpeg",
        )
        srt_url = await self._upload_to_gcs(
            subtitle_result.srt_file_path,
            f"{settings.GCS_OUTPUT_PREFIX}{job_id}/subtitles.srt",
            "text/plain",
        )
        vtt_url = await self._upload_to_gcs(
            subtitle_result.vtt_file_path,
            f"{settings.GCS_OUTPUT_PREFIX}{job_id}/subtitles.vtt",
            "text/vtt",
        )

        # ---- Step 5: Cleanup -------------------------------------------- #
        await self._cleanup_temp(job_id)

        duration = round(time.perf_counter() - t0, 2)
        total_cost = sum(
            r.cost_usd
            for r in renderer_results
        )

        log.info(
            "compositor.completed",
            final_url=final_video_url,
            total_duration=total_duration,
            processing_seconds=duration,
        )

        return RenderingResult(
            job_id=job_id,
            final_video_url=final_video_url,
            thumbnail_url=thumbnail_url,
            subtitle_srt_url=srt_url,
            subtitle_vtt_url=vtt_url,
            total_duration_seconds=round(total_duration, 2),
            scene_render_results=scene_results,
            quality_passed=False,  # set by quality_check layer
            total_cost_usd=round(total_cost, 6),
            processing_time_seconds=duration,
        )

    async def _mux_scene(
        self,
        pkg: FinalScenePackage,
        synced: SyncedScene | None,
        tts: TTSResult | None,
        render: RendererResult | None,
        composed_dir: Path,
        job_id: str,
    ) -> SceneRenderResult:
        """
        Mux video + audio for one scene.
        Falls back to video-only or audio-only if either is missing.
        """
        log = self.log.bind(job_id=job_id, scene_index=pkg.scene_index)

        video_path = synced.video_file_path if synced else (
            render.video_file_path if render else None
        )
        audio_path = synced.audio_file_path if synced else (
            tts.audio_file_path if tts else None
        )
        duration = synced.final_duration_seconds if synced else pkg.estimated_duration_seconds

        output_path = str(composed_dir / f"scene_{pkg.scene_index:02d}.mp4")

        if video_path and audio_path:
            await _mux_video_audio(video_path, audio_path, output_path, duration)
        elif video_path:
            log.warning("compositor.no_audio_for_scene")
            await _copy_video(video_path, output_path)
        elif audio_path:
            log.warning("compositor.no_video_for_scene")
            await _audio_to_black_video(audio_path, output_path, duration)
        else:
            log.error("compositor.no_audio_or_video")
            await _generate_black_video(output_path, duration)

        return SceneRenderResult(
            scene_index=pkg.scene_index,
            composed_file_path=output_path,
            duration_seconds=duration,
            renderer_used=render.renderer_used if render else "none",
            tts_success=bool(tts and tts.success),
            render_success=bool(render and render.success),
            sync_method=synced.sync_method if synced else "none",
        )

    async def _concatenate_scenes(
        self,
        scene_paths: list[str],
        output_path: str,
        job_id: str,
    ) -> None:
        """
        Concatenate scene MP4s using FFmpeg concat demuxer.
        Writes a temporary file list consumed by FFmpeg.
        """
        import ffmpeg  # noqa: PLC0415

        concat_list_path = Path(settings.RENDER_TEMP_DIR) / job_id / "concat_list.txt"
        list_content = "\n".join(f"file '{p}'" for p in scene_paths)
        concat_list_path.write_text(list_content, encoding="utf-8")

        def _run() -> None:
            (
                ffmpeg
                .input(str(concat_list_path), format="concat", safe=0)
                .output(
                    output_path,
                    vcodec="libx264",
                    acodec="aac",
                    pix_fmt="yuv420p",
                    movflags="faststart",
                    threads=settings.FFMPEG_THREADS,
                )
                .overwrite_output()
                .run(quiet=True)
            )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _run)
        self.log.info("compositor.concatenated", scenes=len(scene_paths))

    async def _extract_thumbnail(self, video_path: str, output_path: str) -> None:
        """Extract first frame at 0.5s as JPEG thumbnail."""
        import ffmpeg  # noqa: PLC0415

        def _run() -> None:
            (
                ffmpeg
                .input(video_path, ss=0.5)
                .output(output_path, vframes=1, format="image2", vcodec="mjpeg")
                .overwrite_output()
                .run(quiet=True)
            )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _run)

    async def _generate_blank_thumbnail(self, output_path: str) -> None:
        """Generate a plain black JPEG when no video is available."""
        import ffmpeg  # noqa: PLC0415

        def _run() -> None:
            (
                ffmpeg
                .input("color=c=black:size=1920x1080", f="lavfi", vframes=1)
                .output(output_path, vcodec="mjpeg")
                .overwrite_output()
                .run(quiet=True)
            )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _run)

    async def _compose_fallback_scene(
        self, pkg: FinalScenePackage, composed_dir: Path
    ) -> str:
        """Black video fallback for a completely failed scene mux."""
        output = str(composed_dir / f"scene_{pkg.scene_index:02d}_fallback.mp4")
        await _generate_black_video(output, pkg.estimated_duration_seconds)
        return output

    async def _upload_to_gcs(
        self, local_path: str, gcs_path: str, content_type: str
    ) -> str:
        """
        Upload a file to GCS and return the public GCS URL.
        Wraps sync GCS client in executor.
        """
        from google.cloud import storage  # noqa: PLC0415

        def _upload() -> str:
            client = storage.Client()
            bucket = client.bucket(settings.GCS_BUCKET_NAME)
            blob = bucket.blob(gcs_path)
            blob.upload_from_filename(local_path, content_type=content_type)
            return f"https://storage.googleapis.com/{settings.GCS_BUCKET_NAME}/{gcs_path}"

        loop = asyncio.get_event_loop()
        url = await loop.run_in_executor(None, _upload)
        self.log.info("compositor.gcs_uploaded", gcs_path=gcs_path)
        return url

    async def _cleanup_temp(self, job_id: str) -> None:
        """
        Remove temp directory for this job after successful upload.
        Non-fatal — log warning if cleanup fails.
        """
        temp_path = Path(settings.RENDER_TEMP_DIR) / job_id

        def _rm() -> None:
            shutil.rmtree(str(temp_path), ignore_errors=True)

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, _rm)
            self.log.info("compositor.temp_cleaned", job_id=job_id)
        except Exception as exc:
            self.log.warning("compositor.cleanup_failed", error=str(exc))


# --------------------------------------------------------------------------- #
# FFmpeg operation helpers                                                     #
# --------------------------------------------------------------------------- #

async def _mux_video_audio(
    video_path: str, audio_path: str, output_path: str, duration: float
) -> None:
    """Mux separate video and audio streams into one MP4."""
    import ffmpeg  # noqa: PLC0415

    def _run() -> None:
        v = ffmpeg.input(video_path)
        a = ffmpeg.input(audio_path)
        (
            ffmpeg
            .output(
                v.video, a.audio,
                output_path,
                vcodec="copy",
                acodec="aac",
                t=duration,
                shortest=None,
            )
            .overwrite_output()
            .run(quiet=True)
        )

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run)


async def _copy_video(input_path: str, output_path: str) -> None:
    """Stream-copy video without re-encoding."""
    import ffmpeg  # noqa: PLC0415

    def _run() -> None:
        ffmpeg.input(input_path).output(output_path, vcodec="copy").overwrite_output().run(quiet=True)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run)


async def _audio_to_black_video(
    audio_path: str, output_path: str, duration: float
) -> None:
    """Combine audio with a black video background."""
    import ffmpeg  # noqa: PLC0415

    def _run() -> None:
        v = ffmpeg.input("color=c=black:size=1920x1080:rate=30", f="lavfi", t=duration)
        a = ffmpeg.input(audio_path)
        ffmpeg.output(v, a, output_path, vcodec="libx264", acodec="aac", pix_fmt="yuv420p").overwrite_output().run(quiet=True)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run)


async def _generate_black_video(output_path: str, duration: float) -> None:
    """Generate a black MP4 with no audio — absolute last resort."""
    import ffmpeg  # noqa: PLC0415

    def _run() -> None:
        (
            ffmpeg
            .input("color=c=black:size=1920x1080:rate=30", f="lavfi", t=max(duration, 1.0))
            .output(output_path, vcodec="libx264", pix_fmt="yuv420p")
            .overwrite_output()
            .run(quiet=True)
        )

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run)


compositor = Compositor()

# products/edu_video/backend/layer5_rendering/quality_check/content_completeness.py
"""
ContentCompletenessChecker: verifies all scenes rendered successfully,
the final MP4 is a valid video file, subtitle files exist, and no scenes
are silently missing from the output.
Uses ffprobe for video integrity — no external API calls.
"""

import asyncio
from pathlib import Path

import ffmpeg
import structlog
from pydantic import BaseModel

from core.config import get_settings
from core.utils import utcnow
from layer4_script_visual.schemas import FinalScenePackage
from layer5_rendering.compositor import RenderingResult, SceneRenderResult

__all__ = ["ContentCompletenessChecker", "CompletenessReport"]

logger = structlog.get_logger(__name__)
settings = get_settings()

# --------------------------------------------------------------------------- #
# Thresholds                                                                   #
# --------------------------------------------------------------------------- #

MIN_FINAL_VIDEO_SIZE_BYTES: int = 100_000      # 100 KB — anything smaller is corrupt
MIN_VIDEO_DURATION_SECONDS: float = 10.0       # final video must be at least 10s
MAX_PROBE_TIMEOUT_SECONDS: int = 15            # ffprobe timeout per file


# --------------------------------------------------------------------------- #
# Pydantic model                                                               #
# --------------------------------------------------------------------------- #

class CompletenessReport(BaseModel):
    passed: bool
    expected_scene_count: int
    actual_scene_count: int
    missing_scene_indices: list[int]
    failed_scene_indices: list[int]    # rendered but with success=False
    issues: list                       # list[QualityIssue]
    final_video_valid: bool
    subtitle_files_present: bool
    final_video_duration_seconds: float


# --------------------------------------------------------------------------- #
# ContentCompletenessChecker                                                   #
# --------------------------------------------------------------------------- #

class ContentCompletenessChecker:
    """
    Structural completeness checks — verifies nothing is silently missing
    or corrupt before the video is delivered to students.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(__name__)

    async def validate(
        self,
        rendering_result: RenderingResult,
        packages: list[FinalScenePackage],
        job_id: str,
    ) -> CompletenessReport:
        """
        Run all completeness checks:
          1. Scene count vs expected
          2. Failed renderer results
          3. Final video file integrity (ffprobe)
          4. Final video duration sanity
          5. Subtitle file presence
        """
        from layer5_rendering.quality_check import QualityIssue, QualityIssueSeverity  # noqa

        log = self.log.bind(job_id=job_id)
        log.info("completeness_checker.started")

        all_issues: list = []
        expected_count = len(packages)
        expected_indices = {p.scene_index for p in packages}
        rendered_indices = {r.scene_index for r in rendering_result.scene_render_results}

        # ---- Check 1: Missing scenes ------------------------------------ #
        missing_indices = sorted(expected_indices - rendered_indices)
        for idx in missing_indices:
            all_issues.append(QualityIssue(
                severity=QualityIssueSeverity.CRITICAL,
                validator="completeness",
                scene_index=idx,
                code="scene_missing",
                message=f"Scene {idx} was expected but not found in rendering output.",
            ))

        # ---- Check 2: Failed scene renders ------------------------------ #
        failed_indices = [
            r.scene_index
            for r in rendering_result.scene_render_results
            if not r.render_success
        ]
        for idx in failed_indices:
            all_issues.append(QualityIssue(
                severity=QualityIssueSeverity.WARNING,
                validator="completeness",
                scene_index=idx,
                code="scene_render_failed",
                message=(
                    f"Scene {idx} used fallback renderer — "
                    "visual quality may be degraded."
                ),
            ))

        # ---- Check 3 + 4: Final video integrity and duration ------------ #
        final_video_valid = False
        final_video_duration = 0.0

        final_video_path = await self._resolve_local_path(
            rendering_result.final_video_url, job_id
        )

        if final_video_path and Path(final_video_path).exists():
            file_size = Path(final_video_path).stat().st_size
            if file_size < MIN_FINAL_VIDEO_SIZE_BYTES:
                all_issues.append(QualityIssue(
                    severity=QualityIssueSeverity.CRITICAL,
                    validator="completeness",
                    scene_index=None,
                    code="final_video_too_small",
                    message=(
                        f"Final video file is only {file_size:,} bytes — "
                        f"minimum is {MIN_FINAL_VIDEO_SIZE_BYTES:,} bytes."
                    ),
                    metric_value=float(file_size),
                    threshold_value=float(MIN_FINAL_VIDEO_SIZE_BYTES),
                ))
            else:
                probe_result = await self._probe_video(final_video_path)
                if probe_result is None:
                    all_issues.append(QualityIssue(
                        severity=QualityIssueSeverity.CRITICAL,
                        validator="completeness",
                        scene_index=None,
                        code="final_video_corrupt",
                        message="Final video failed ffprobe — file may be corrupt.",
                    ))
                else:
                    final_video_valid = True
                    final_video_duration = probe_result.get("duration", 0.0)

                    if final_video_duration < MIN_VIDEO_DURATION_SECONDS:
                        all_issues.append(QualityIssue(
                            severity=QualityIssueSeverity.CRITICAL,
                            validator="completeness",
                            scene_index=None,
                            code="final_video_too_short",
                            message=(
                                f"Final video is only {final_video_duration:.1f}s — "
                                f"minimum is {MIN_VIDEO_DURATION_SECONDS}s."
                            ),
                            metric_value=final_video_duration,
                            threshold_value=MIN_VIDEO_DURATION_SECONDS,
                        ))

                    # Verify both video and audio streams present
                    has_video = probe_result.get("has_video", False)
                    has_audio = probe_result.get("has_audio", False)

                    if not has_video:
                        all_issues.append(QualityIssue(
                            severity=QualityIssueSeverity.CRITICAL,
                            validator="completeness",
                            scene_index=None,
                            code="no_video_stream",
                            message="Final MP4 contains no video stream.",
                        ))
                    if not has_audio:
                        all_issues.append(QualityIssue(
                            severity=QualityIssueSeverity.WARNING,
                            validator="completeness",
                            scene_index=None,
                            code="no_audio_stream",
                            message="Final MP4 contains no audio stream.",
                        ))
        else:
            all_issues.append(QualityIssue(
                severity=QualityIssueSeverity.CRITICAL,
                validator="completeness",
                scene_index=None,
                code="final_video_not_found",
                message=(
                    f"Final video file not accessible locally: "
                    f"{rendering_result.final_video_url}"
                ),
            ))

        # ---- Check 5: Subtitle files ------------------------------------ #
        subtitle_present = await self._check_subtitle_files(
            rendering_result, job_id
        )
        if not subtitle_present:
            all_issues.append(QualityIssue(
                severity=QualityIssueSeverity.WARNING,
                validator="completeness",
                scene_index=None,
                code="subtitle_files_missing",
                message="SRT or VTT subtitle files are missing or inaccessible.",
            ))

        # ---- Summary ---------------------------------------------------- #
        passed = not any(
            i.severity == QualityIssueSeverity.CRITICAL
            for i in all_issues
        )
        actual_count = len(rendering_result.scene_render_results)

        log.info(
            "completeness_checker.completed",
            passed=passed,
            expected=expected_count,
            actual=actual_count,
            missing=len(missing_indices),
            failed=len(failed_indices),
            final_valid=final_video_valid,
        )

        return CompletenessReport(
            passed=passed,
            expected_scene_count=expected_count,
            actual_scene_count=actual_count,
            missing_scene_indices=missing_indices,
            failed_scene_indices=failed_indices,
            issues=all_issues,
            final_video_valid=final_video_valid,
            subtitle_files_present=subtitle_present,
            final_video_duration_seconds=round(final_video_duration, 2),
        )

    async def _probe_video(self, path: str) -> dict | None:
        """
        Run ffprobe on the final video file.
        Returns dict with {duration, has_video, has_audio} or None on failure.
        Runs in executor — ffprobe is a blocking subprocess call.
        """
        loop = asyncio.get_event_loop()

        def _run() -> dict | None:
            try:
                probe = ffmpeg.probe(path)
                streams = probe.get("streams", [])
                duration = float(probe.get("format", {}).get("duration", 0.0))
                has_video = any(s["codec_type"] == "video" for s in streams)
                has_audio = any(s["codec_type"] == "audio" for s in streams)
                return {
                    "duration": duration,
                    "has_video": has_video,
                    "has_audio": has_audio,
                }
            except Exception as exc:
                logger.warning("completeness.ffprobe_failed", path=path, error=str(exc))
                return None

        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _run),
                timeout=MAX_PROBE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("completeness.ffprobe_timeout", path=path)
            return None

    async def _resolve_local_path(
        self, gcs_url: str, job_id: str
    ) -> str | None:
        """
        Resolve the local /tmp path for the final video.
        The final MP4 is written to RENDER_TEMP_DIR before GCS upload.
        After cleanup, it no longer exists — quality check runs before cleanup.
        """
        # Reconstruct the expected local path from the GCS URL
        # Pattern: .../{job_id}/final.mp4 → /tmp/edu_video/{job_id}/final_{job_id}.mp4
        expected = Path(settings.RENDER_TEMP_DIR) / job_id / f"final_{job_id}.mp4"
        if expected.exists():
            return str(expected)

        # Fallback: search the job temp dir for any .mp4 at root level
        job_dir = Path(settings.RENDER_TEMP_DIR) / job_id
        if job_dir.exists():
            mp4s = list(job_dir.glob("final_*.mp4"))
            if mp4s:
                return str(mp4s[0])

        self.log.warning(
            "completeness.local_path_not_found",
            job_id=job_id,
            gcs_url=gcs_url,
        )
        return None

    async def _check_subtitle_files(
        self, rendering_result: RenderingResult, job_id: str
    ) -> bool:
        """
        Check that both SRT and VTT subtitle files exist locally.
        Returns True if both are present and non-empty.
        """
        job_dir = Path(settings.RENDER_TEMP_DIR) / job_id / "subtitles"
        srt = job_dir / f"{job_id}.srt"
        vtt = job_dir / f"{job_id}.vtt"

        srt_ok = srt.exists() and srt.stat().st_size > 0
        vtt_ok = vtt.exists() and vtt.stat().st_size > 0

        if not srt_ok:
            self.log.warning("completeness.srt_missing", path=str(srt))
        if not vtt_ok:
            self.log.warning("completeness.vtt_missing", path=str(vtt))

        return srt_ok and vtt_ok

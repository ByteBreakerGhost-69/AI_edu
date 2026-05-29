# products/edu_video/backend/layer5_rendering/quality_check/timing_validator.py
"""
TimingValidator: validates timing alignment between TTS audio duration and
visual animation duration, and checks total video duration bounds.
Pure arithmetic — no ffprobe needed, uses SyncedScene metadata directly.
"""

from collections import defaultdict

import structlog
from pydantic import BaseModel

from core.config import get_settings
from layer4_script_visual.schemas import FinalScenePackage
from layer5_rendering.timing_sync import SyncedScene

__all__ = ["TimingValidator", "TimingValidationReport"]

logger = structlog.get_logger(__name__)
settings = get_settings()

# --------------------------------------------------------------------------- #
# Thresholds                                                                   #
# --------------------------------------------------------------------------- #

MAX_SCENE_DURATION_DRIFT_SECONDS: float = 3.0
MAX_TOTAL_DURATION_DRIFT_SECONDS: float = 10.0
MIN_SCENE_DURATION_SECONDS: float = 8.0
MAX_SCENE_DURATION_SECONDS: float = 120.0
MAX_SYNC_DRIFT_RATIO: float = 0.25


# --------------------------------------------------------------------------- #
# Pydantic model                                                               #
# --------------------------------------------------------------------------- #

class TimingValidationReport(BaseModel):
    passed: bool
    scenes_checked: int
    issues: list           # list[QualityIssue]
    total_duration_seconds: float
    expected_duration_seconds: float
    duration_drift_seconds: float
    max_scene_drift_seconds: float
    sync_method_counts: dict[str, int]


# --------------------------------------------------------------------------- #
# TimingValidator                                                              #
# --------------------------------------------------------------------------- #

class TimingValidator:
    """
    Validates per-scene and total-video timing.
    Synchronous math on SyncedScene metadata — no blocking I/O.
    Wrapped in async interface for consistency with other validators.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(__name__)

    async def validate(
        self,
        synced_scenes: list[SyncedScene],
        packages: list[FinalScenePackage],
        job_id: str,
    ) -> TimingValidationReport:
        """
        Run all timing checks and return a TimingValidationReport.
        All computation is synchronous — no executor needed.
        """
        from layer5_rendering.quality_check import QualityIssue, QualityIssueSeverity  # noqa

        log = self.log.bind(job_id=job_id)
        log.info("timing_validator.started", scene_count=len(synced_scenes))

        all_issues: list = []
        sync_method_counts: dict[str, int] = defaultdict(int)
        scene_drifts: list[float] = []

        pkg_map = {p.scene_index: p for p in packages}

        for scene in sorted(synced_scenes, key=lambda s: s.scene_index):
            pkg = pkg_map.get(scene.scene_index)
            if pkg is None:
                log.warning(
                    "timing_validator.no_package_for_scene",
                    scene_index=scene.scene_index,
                )
                continue

            sync_method_counts[scene.sync_method] += 1
            expected_dur = pkg.estimated_duration_seconds
            actual_dur = scene.final_duration_seconds
            drift = abs(actual_dur - expected_dur)
            scene_drifts.append(drift)

            # ---- Check 1: Per-scene duration drift ---------------------- #
            if drift > MAX_SCENE_DURATION_DRIFT_SECONDS:
                severity = (
                    QualityIssueSeverity.CRITICAL
                    if drift > MAX_SCENE_DURATION_DRIFT_SECONDS * 2
                    else QualityIssueSeverity.WARNING
                )
                all_issues.append(QualityIssue(
                    severity=severity,
                    validator="timing",
                    scene_index=scene.scene_index,
                    code="scene_duration_drift",
                    message=(
                        f"Scene {scene.scene_index}: actual {actual_dur:.1f}s vs "
                        f"expected {expected_dur:.1f}s (drift={drift:.1f}s)."
                    ),
                    metric_value=drift,
                    threshold_value=MAX_SCENE_DURATION_DRIFT_SECONDS,
                ))

            # ---- Check 2: Scene too short ------------------------------- #
            if actual_dur < MIN_SCENE_DURATION_SECONDS:
                all_issues.append(QualityIssue(
                    severity=QualityIssueSeverity.CRITICAL,
                    validator="timing",
                    scene_index=scene.scene_index,
                    code="scene_too_short",
                    message=(
                        f"Scene {scene.scene_index}: {actual_dur:.1f}s is below "
                        f"minimum {MIN_SCENE_DURATION_SECONDS}s."
                    ),
                    metric_value=actual_dur,
                    threshold_value=MIN_SCENE_DURATION_SECONDS,
                ))

            # ---- Check 3: Scene too long -------------------------------- #
            if actual_dur > MAX_SCENE_DURATION_SECONDS:
                all_issues.append(QualityIssue(
                    severity=QualityIssueSeverity.WARNING,
                    validator="timing",
                    scene_index=scene.scene_index,
                    code="scene_too_long",
                    message=(
                        f"Scene {scene.scene_index}: {actual_dur:.1f}s exceeds "
                        f"maximum {MAX_SCENE_DURATION_SECONDS}s."
                    ),
                    metric_value=actual_dur,
                    threshold_value=MAX_SCENE_DURATION_SECONDS,
                ))

            # ---- Check 4: Aggressive speed adjustment ------------------- #
            if scene.sync_method == "speed_video":
                video_dur = scene.original_video_duration
                audio_dur = scene.original_audio_duration
                if video_dur > 0:
                    speed_ratio = abs(video_dur - audio_dur) / video_dur
                    if speed_ratio > MAX_SYNC_DRIFT_RATIO:
                        all_issues.append(QualityIssue(
                            severity=QualityIssueSeverity.WARNING,
                            validator="timing",
                            scene_index=scene.scene_index,
                            code="aggressive_speed_adjustment",
                            message=(
                                f"Scene {scene.scene_index}: speed adjusted by "
                                f"{speed_ratio * 100:.0f}% — may appear unnatural."
                            ),
                            metric_value=speed_ratio,
                            threshold_value=MAX_SYNC_DRIFT_RATIO,
                        ))

            # ---- Check 5: Audio was trimmed (narration cut off) --------- #
            if scene.sync_method == "trim_audio":
                trimmed_secs = scene.original_audio_duration - scene.original_video_duration
                all_issues.append(QualityIssue(
                    severity=QualityIssueSeverity.WARNING,
                    validator="timing",
                    scene_index=scene.scene_index,
                    code="audio_trimmed",
                    message=(
                        f"Scene {scene.scene_index}: narration trimmed by "
                        f"{trimmed_secs:.1f}s to fit visual duration."
                    ),
                    metric_value=trimmed_secs,
                    threshold_value=0.0,
                ))

        # ---- Job-level: total duration drift ---------------------------- #
        total_actual = sum(s.final_duration_seconds for s in synced_scenes)
        total_expected = sum(p.estimated_duration_seconds for p in packages)
        total_drift = abs(total_actual - total_expected)

        if total_drift > MAX_TOTAL_DURATION_DRIFT_SECONDS:
            all_issues.append(QualityIssue(
                severity=QualityIssueSeverity.WARNING,
                validator="timing",
                scene_index=None,
                code="total_duration_drift",
                message=(
                    f"Total video {total_actual:.1f}s vs expected "
                    f"{total_expected:.1f}s (drift={total_drift:.1f}s)."
                ),
                metric_value=total_drift,
                threshold_value=MAX_TOTAL_DURATION_DRIFT_SECONDS,
            ))

        # ---- Job-level: hard duration cap ------------------------------- #
        if total_actual > settings.MAX_VIDEO_DURATION_SECONDS:
            all_issues.append(QualityIssue(
                severity=QualityIssueSeverity.CRITICAL,
                validator="timing",
                scene_index=None,
                code="exceeds_max_duration",
                message=(
                    f"Video {total_actual:.0f}s exceeds hard cap "
                    f"{settings.MAX_VIDEO_DURATION_SECONDS}s."
                ),
                metric_value=total_actual,
                threshold_value=float(settings.MAX_VIDEO_DURATION_SECONDS),
            ))

        passed = not any(
            i.severity == QualityIssueSeverity.CRITICAL
            for i in all_issues
        )

        log.info(
            "timing_validator.completed",
            passed=passed,
            total_actual=round(total_actual, 2),
            total_expected=round(total_expected, 2),
            issues=len(all_issues),
        )

        return TimingValidationReport(
            passed=passed,
            scenes_checked=len(synced_scenes),
            issues=all_issues,
            total_duration_seconds=round(total_actual, 2),
            expected_duration_seconds=round(total_expected, 2),
            duration_drift_seconds=round(total_actual - total_expected, 2),
            max_scene_drift_seconds=round(max(scene_drifts), 2) if scene_drifts else 0.0,
            sync_method_counts=dict(sync_method_counts),
          )

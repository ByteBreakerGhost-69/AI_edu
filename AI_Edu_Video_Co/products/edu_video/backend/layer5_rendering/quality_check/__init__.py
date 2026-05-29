# products/edu_video/backend/layer5_rendering/quality_check/__init__.py
"""
Quality Check subsystem for Layer 5 rendering.

QualityCheckOrchestrator runs all three validators concurrently and
aggregates results into a single QualityReport.

Shared models (QualityIssue, QualityReport, etc.) are defined here so
all three validators can import them without circular dependencies.

Import order:
  This __init__.py defines shared models FIRST.
  Validators are imported AFTER — they import from this module.
"""

import asyncio
import time
from datetime import datetime
from enum import StrEnum
from typing import Optional

import structlog
from pydantic import BaseModel

from core.utils import utcnow
from layer4_script_visual.schemas import FinalScenePackage
from layer5_rendering.compositor import RenderingResult
from layer5_rendering.timing_sync import SyncedScene
from layer5_rendering.tts_service import TTSResult

__all__ = [
    # Shared models
    "QualityIssueSeverity",
    "QualityIssue",
    "QualityReport",
    # Per-validator reports
    "AudioValidationReport",
    "TimingValidationReport",
    "CompletenessReport",
    # Orchestrator
    "QualityCheckOrchestrator",
    "quality_check_orchestrator",
]

logger = structlog.get_logger(__name__)


# --------------------------------------------------------------------------- #
# Shared models — defined FIRST so validators can import them                 #
# --------------------------------------------------------------------------- #

class QualityIssueSeverity(StrEnum):
    CRITICAL = "critical"    # must fix — blocks delivery
    WARNING  = "warning"     # should fix — deliver with flag for human review
    INFO     = "info"        # log only — no action required


class QualityIssue(BaseModel):
    severity: QualityIssueSeverity
    validator: str                      # "audio" | "timing" | "completeness"
    scene_index: Optional[int] = None   # None = job-level issue
    code: str                           # e.g. "audio_cutoff", "scene_missing"
    message: str
    metric_value: Optional[float] = None
    threshold_value: Optional[float] = None


class QualityReport(BaseModel):
    """Aggregated quality report — primary output of this subsystem."""
    job_id: str
    passed: bool
    overall_score: float                # 0.0–1.0 weighted average
    audio_report: "AudioValidationReport"
    timing_report: "TimingValidationReport"
    completeness_report: "CompletenessReport"
    issues: list[QualityIssue]          # all issues flattened across validators
    recommendations: list[str]
    checked_at: datetime
    check_duration_seconds: float


# --------------------------------------------------------------------------- #
# Import validators AFTER shared models are defined                            #
# --------------------------------------------------------------------------- #

from layer5_rendering.quality_check.audio_validator import (  # noqa: E402
    AudioValidationReport,
    AudioValidator,
)
from layer5_rendering.quality_check.timing_validator import (  # noqa: E402
    TimingValidationReport,
    TimingValidator,
)
from layer5_rendering.quality_check.content_completeness import (  # noqa: E402
    CompletenessReport,
    ContentCompletenessChecker,
)

# Update forward refs now that all models are defined
QualityReport.model_rebuild()


# --------------------------------------------------------------------------- #
# Scoring configuration                                                        #
# --------------------------------------------------------------------------- #

_VALIDATOR_WEIGHTS: dict[str, float] = {
    "audio":        0.35,
    "timing":       0.35,
    "completeness": 0.30,
}

_ISSUE_SCORE_DEDUCTIONS: dict[QualityIssueSeverity, float] = {
    QualityIssueSeverity.CRITICAL: 0.30,
    QualityIssueSeverity.WARNING:  0.10,
    QualityIssueSeverity.INFO:     0.02,
}


# --------------------------------------------------------------------------- #
# QualityCheckOrchestrator                                                     #
# --------------------------------------------------------------------------- #

class QualityCheckOrchestrator:
    """
    Runs all three quality validators concurrently and produces a
    single QualityReport with a pass/fail verdict and overall score.

    Passed = all three validators pass (no CRITICAL issues in any).
    Score = weighted average across validators, deducting for each issue.
    """

    def __init__(self) -> None:
        self.audio_validator = AudioValidator()
        self.timing_validator = TimingValidator()
        self.completeness_checker = ContentCompletenessChecker()
        self.log = structlog.get_logger(__name__)

    async def run(
        self,
        rendering_result: RenderingResult,
        synced_scenes: list[SyncedScene],
        tts_results: list[TTSResult],
        packages: list[FinalScenePackage],
        job_id: str,
    ) -> QualityReport:
        """
        Run all validators concurrently.
        Returns QualityReport with overall pass/fail and recommendations.
        """
        log = self.log.bind(job_id=job_id)
        log.info("quality_check.started")
        t0 = time.perf_counter()

        # Run all three validators concurrently
        audio_task = self.audio_validator.validate(tts_results, packages, job_id)
        timing_task = self.timing_validator.validate(synced_scenes, packages, job_id)
        completeness_task = self.completeness_checker.validate(
            rendering_result, packages, job_id
        )

        audio_report, timing_report, completeness_report = await asyncio.gather(
            audio_task,
            timing_task,
            completeness_task,
            return_exceptions=False,
        )

        # Flatten all issues
        all_issues: list[QualityIssue] = (
            list(audio_report.issues)
            + list(timing_report.issues)
            + list(completeness_report.issues)
        )

        # Overall pass = all validators pass
        passed = (
            audio_report.passed
            and timing_report.passed
            and completeness_report.passed
        )

        # Compute weighted overall score
        overall_score = _compute_overall_score(
            audio_report=audio_report,
            timing_report=timing_report,
            completeness_report=completeness_report,
            all_issues=all_issues,
        )

        # Generate actionable recommendations
        recommendations = _build_recommendations(all_issues)

        duration = round(time.perf_counter() - t0, 2)

        log.info(
            "quality_check.completed",
            passed=passed,
            overall_score=round(overall_score, 3),
            critical_count=sum(
                1 for i in all_issues
                if i.severity == QualityIssueSeverity.CRITICAL
            ),
            warning_count=sum(
                1 for i in all_issues
                if i.severity == QualityIssueSeverity.WARNING
            ),
            duration_seconds=duration,
        )

        return QualityReport(
            job_id=job_id,
            passed=passed,
            overall_score=round(overall_score, 4),
            audio_report=audio_report,
            timing_report=timing_report,
            completeness_report=completeness_report,
            issues=all_issues,
            recommendations=recommendations,
            checked_at=utcnow(),
            check_duration_seconds=duration,
        )


# --------------------------------------------------------------------------- #
# Score computation                                                            #
# --------------------------------------------------------------------------- #

def _compute_overall_score(
    audio_report: AudioValidationReport,
    timing_report: TimingValidationReport,
    completeness_report: CompletenessReport,
    all_issues: list[QualityIssue],
) -> float:
    """
    Compute a 0.0–1.0 quality score.
    Starts at 1.0, deducts for each issue weighted by severity and validator weight.
    Never returns negative.
    """
    score = 1.0

    for issue in all_issues:
        validator_weight = _VALIDATOR_WEIGHTS.get(issue.validator, 0.33)
        deduction = _ISSUE_SCORE_DEDUCTIONS.get(issue.severity, 0.05)
        score -= deduction * validator_weight

    return max(0.0, min(score, 1.0))


# --------------------------------------------------------------------------- #
# Recommendation builder                                                       #
# --------------------------------------------------------------------------- #

_RECOMMENDATION_MAP: dict[str, str] = {
    # Audio
    "audio_file_missing":      "Re-run TTS synthesis for missing audio scenes.",
    "audio_too_short":         "Check TTS SSML — narration may have been truncated.",
    "speech_too_slow":         "Review TTS speaking rate — audio may have been cut off during synthesis.",
    "speech_too_fast":         "Review TTS speaking rate — content may be excessively condensed.",
    "abnormal_volume":         "Apply audio normalization (loudnorm filter) before delivery.",
    "silence_gap":             "Investigate SSML break tags — excessive pauses detected.",
    "no_audio_stream":         "Re-synthesize TTS for affected scene.",
    # Timing
    "scene_duration_drift":    "Check timing_sync output — scene duration mismatches detected.",
    "scene_too_short":         "Scene is too short for educational content — expand narration.",
    "scene_too_long":          "Consider splitting this scene into two shorter segments.",
    "aggressive_speed_adjustment": "Reduce mismatch between TTS duration and render duration.",
    "audio_trimmed":           "Narration was cut off — shorten narration or extend visual.",
    "total_duration_drift":    "Review overall video pacing — total duration deviates from estimate.",
    "exceeds_max_duration":    "Video exceeds maximum duration — reduce scene count or narration length.",
    # Completeness
    "scene_missing":           "Re-run rendering pipeline for missing scenes.",
    "scene_render_failed":     "Check renderer logs for failed scenes and retry.",
    "final_video_corrupt":     "Re-run compositor — final MP4 failed integrity check.",
    "final_video_too_short":   "Final video is suspiciously short — check compositor output.",
    "final_video_too_small":   "Final video file is too small — compositor may have failed silently.",
    "no_video_stream":         "Final MP4 has no video — check FFmpeg compositor command.",
    "no_audio_stream":         "Final MP4 has no audio — verify mux step in compositor.",
    "subtitle_files_missing":  "Re-run subtitle_generator for missing SRT/VTT files.",
}


def _build_recommendations(issues: list[QualityIssue]) -> list[str]:
    """
    Build a deduplicated list of actionable recommendation strings.
    Prioritises CRITICAL issues first, then WARNINGs.
    """
    seen: set[str] = set()
    recommendations: list[str] = []

    # CRITICAL first
    for severity in (QualityIssueSeverity.CRITICAL, QualityIssueSeverity.WARNING):
        for issue in issues:
            if issue.severity != severity:
                continue
            rec = _RECOMMENDATION_MAP.get(issue.code)
            if rec and rec not in seen:
                seen.add(rec)
                recommendations.append(rec)

    return recommendations


quality_check_orchestrator = QualityCheckOrchestrator()

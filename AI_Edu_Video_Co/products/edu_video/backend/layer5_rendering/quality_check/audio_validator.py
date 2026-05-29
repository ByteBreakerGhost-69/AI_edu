# products/edu_video/backend/layer5_rendering/quality_check/audio_validator.py
"""
AudioValidator: validates per-scene TTS audio for cutoffs, silence gaps,
volume normalization, and speech rate plausibility.
All checks use ffprobe/ffmpeg — no LLM, no external API calls.
"""

import asyncio
import json
import re
from pathlib import Path

import ffmpeg
import structlog
from pydantic import BaseModel

from core.config import get_settings
from core.utils import utcnow
from layer4_script_visual.schemas import FinalScenePackage
from layer5_rendering.tts_service import TTSResult

__all__ = ["AudioValidator", "AudioValidationReport"]

logger = structlog.get_logger(__name__)
settings = get_settings()

# --------------------------------------------------------------------------- #
# Thresholds                                                                   #
# --------------------------------------------------------------------------- #

MIN_AUDIO_DURATION_SECONDS: float = 5.0
MAX_SILENCE_GAP_SECONDS: float = 2.5
TARGET_LOUDNESS_LUFS: float = -16.0
LOUDNESS_TOLERANCE_LUFS: float = 6.0
MIN_WORDS_PER_SECOND: float = 0.8
MAX_WORDS_PER_SECOND: float = 4.0

_FFPROBE_CONCURRENCY = 4


# --------------------------------------------------------------------------- #
# Pydantic model                                                               #
# --------------------------------------------------------------------------- #

class AudioValidationReport(BaseModel):
    passed: bool
    scenes_checked: int
    issues: list          # list[QualityIssue] — imported at runtime to avoid circular
    avg_volume_lufs: float
    silence_gap_count: int
    cutoff_scene_indices: list[int]


# --------------------------------------------------------------------------- #
# AudioValidator                                                               #
# --------------------------------------------------------------------------- #

class AudioValidator:
    """
    Validates audio quality for every scene.
    Runs ffprobe-based checks concurrently — I/O bound, safe to parallelize.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(__name__)

    async def validate(
        self,
        tts_results: list[TTSResult],
        packages: list[FinalScenePackage],
        job_id: str,
    ) -> AudioValidationReport:
        """
        Run all audio checks for all scenes concurrently.
        Returns AudioValidationReport with aggregated metrics and issue list.
        """
        from layer5_rendering.quality_check import QualityIssue, QualityIssueSeverity  # noqa

        log = self.log.bind(job_id=job_id)
        log.info("audio_validator.started", scene_count=len(tts_results))

        semaphore = asyncio.Semaphore(_FFPROBE_CONCURRENCY)
        pairs = self._pair_tts_packages(tts_results, packages)

        scene_reports = await asyncio.gather(
            *[
                self._validate_scene_audio(tts, pkg, semaphore, job_id)
                for tts, pkg in pairs
            ],
            return_exceptions=True,
        )

        all_issues: list = []
        all_lufs: list[float] = []
        silence_gap_count = 0
        cutoff_indices: list[int] = []

        for (tts, _), outcome in zip(pairs, scene_reports):
            if isinstance(outcome, Exception):
                log.error(
                    "audio_validator.scene_check_failed",
                    scene_index=tts.scene_index,
                    error=str(outcome),
                )
                all_issues.append(QualityIssue(
                    severity=QualityIssueSeverity.WARNING,
                    validator="audio",
                    scene_index=tts.scene_index,
                    code="validation_error",
                    message=f"Audio validation failed: {outcome}",
                ))
                continue

            all_issues.extend(outcome["issues"])
            if outcome.get("lufs") is not None:
                all_lufs.append(outcome["lufs"])
            silence_gap_count += outcome.get("silence_gaps", 0)
            if outcome.get("cutoff"):
                cutoff_indices.append(outcome["scene_index"])

        avg_lufs = sum(all_lufs) / len(all_lufs) if all_lufs else TARGET_LOUDNESS_LUFS
        passed = not any(
            i.severity == QualityIssueSeverity.CRITICAL
            for i in all_issues
        )

        log.info(
            "audio_validator.completed",
            passed=passed,
            issues=len(all_issues),
            cutoffs=len(cutoff_indices),
            silence_gaps=silence_gap_count,
            avg_lufs=round(avg_lufs, 2),
        )

        return AudioValidationReport(
            passed=passed,
            scenes_checked=len(tts_results),
            issues=all_issues,
            avg_volume_lufs=round(avg_lufs, 2),
            silence_gap_count=silence_gap_count,
            cutoff_scene_indices=cutoff_indices,
        )

    async def _validate_scene_audio(
        self,
        tts: TTSResult,
        pkg: FinalScenePackage,
        semaphore: asyncio.Semaphore,
        job_id: str,
    ) -> dict:
        """Run all checks for a single scene's audio file."""
        from layer5_rendering.quality_check import QualityIssue, QualityIssueSeverity  # noqa

        async with semaphore:
            log = self.log.bind(job_id=job_id, scene_index=tts.scene_index)
            issues: list = []
            result: dict = {
                "scene_index": tts.scene_index,
                "issues": issues,
                "cutoff": False,
                "silence_gaps": 0,
                "lufs": None,
            }

            audio_path = tts.audio_file_path

            # ---- Guard: file existence ---------------------------------- #
            if not Path(audio_path).exists():
                issues.append(QualityIssue(
                    severity=QualityIssueSeverity.CRITICAL,
                    validator="audio",
                    scene_index=tts.scene_index,
                    code="audio_file_missing",
                    message=f"Audio file not found: {audio_path}",
                ))
                return result

            # ---- Probe audio stream ------------------------------------- #
            try:
                probe = await self._ffprobe_async(audio_path)
            except Exception as exc:
                issues.append(QualityIssue(
                    severity=QualityIssueSeverity.CRITICAL,
                    validator="audio",
                    scene_index=tts.scene_index,
                    code="ffprobe_failed",
                    message=f"ffprobe error: {exc}",
                ))
                return result

            audio_stream = next(
                (s for s in probe.get("streams", []) if s["codec_type"] == "audio"),
                None,
            )
            if audio_stream is None:
                issues.append(QualityIssue(
                    severity=QualityIssueSeverity.CRITICAL,
                    validator="audio",
                    scene_index=tts.scene_index,
                    code="no_audio_stream",
                    message="Audio file contains no audio stream.",
                ))
                return result

            actual_duration = float(probe.get("format", {}).get("duration", 0.0))

            # ---- Check 1: Minimum duration ------------------------------ #
            if actual_duration < MIN_AUDIO_DURATION_SECONDS:
                issues.append(QualityIssue(
                    severity=QualityIssueSeverity.CRITICAL,
                    validator="audio",
                    scene_index=tts.scene_index,
                    code="audio_too_short",
                    message=(
                        f"Audio duration {actual_duration:.1f}s is below "
                        f"minimum {MIN_AUDIO_DURATION_SECONDS}s."
                    ),
                    metric_value=actual_duration,
                    threshold_value=MIN_AUDIO_DURATION_SECONDS,
                ))

            # ---- Check 2: Speech rate plausibility ---------------------- #
            narration = pkg.refined_script.narration_text
            word_count = len(narration.split())
            if actual_duration > 0:
                wps = word_count / actual_duration
                if wps < MIN_WORDS_PER_SECOND:
                    issues.append(QualityIssue(
                        severity=QualityIssueSeverity.WARNING,
                        validator="audio",
                        scene_index=tts.scene_index,
                        code="speech_too_slow",
                        message=(
                            f"Speech rate {wps:.2f} words/sec is below "
                            f"minimum {MIN_WORDS_PER_SECOND} — possible cutoff."
                        ),
                        metric_value=wps,
                        threshold_value=MIN_WORDS_PER_SECOND,
                    ))
                    result["cutoff"] = True
                elif wps > MAX_WORDS_PER_SECOND:
                    issues.append(QualityIssue(
                        severity=QualityIssueSeverity.WARNING,
                        validator="audio",
                        scene_index=tts.scene_index,
                        code="speech_too_fast",
                        message=(
                            f"Speech rate {wps:.2f} words/sec exceeds "
                            f"maximum {MAX_WORDS_PER_SECOND} — possible TTS error."
                        ),
                        metric_value=wps,
                        threshold_value=MAX_WORDS_PER_SECOND,
                    ))

            # ---- Check 3: Loudness measurement -------------------------- #
            lufs = await self._measure_loudness(audio_path)
            if lufs is not None:
                result["lufs"] = lufs
                deviation = abs(lufs - TARGET_LOUDNESS_LUFS)
                if deviation > LOUDNESS_TOLERANCE_LUFS:
                    severity = (
                        QualityIssueSeverity.CRITICAL
                        if deviation > LOUDNESS_TOLERANCE_LUFS * 2
                        else QualityIssueSeverity.WARNING
                    )
                    issues.append(QualityIssue(
                        severity=severity,
                        validator="audio",
                        scene_index=tts.scene_index,
                        code="abnormal_volume",
                        message=(
                            f"Loudness {lufs:.1f} LUFS — expected "
                            f"{TARGET_LOUDNESS_LUFS}±{LOUDNESS_TOLERANCE_LUFS} LUFS."
                        ),
                        metric_value=lufs,
                        threshold_value=TARGET_LOUDNESS_LUFS,
                    ))

            # ---- Check 4: Silence gap detection ------------------------- #
            gaps = await self._detect_silence_gaps(audio_path)
            for gap_start, gap_duration in gaps:
                if gap_duration > MAX_SILENCE_GAP_SECONDS:
                    result["silence_gaps"] += 1
                    issues.append(QualityIssue(
                        severity=QualityIssueSeverity.WARNING,
                        validator="audio",
                        scene_index=tts.scene_index,
                        code="silence_gap",
                        message=(
                            f"Silence gap of {gap_duration:.1f}s at "
                            f"{gap_start:.1f}s into audio."
                        ),
                        metric_value=gap_duration,
                        threshold_value=MAX_SILENCE_GAP_SECONDS,
                    ))

            log.debug(
                "audio_validator.scene_done",
                duration=actual_duration,
                issues=len(issues),
            )
            return result

    async def _ffprobe_async(self, path: str) -> dict:
        """Run ffprobe in thread executor — blocking call."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: ffmpeg.probe(path))

    async def _measure_loudness(self, audio_path: str) -> float | None:
        """
        Measure integrated loudness (LUFS) using ffmpeg loudnorm filter
        in analysis mode. Parses JSON from stderr.
        Returns None on any failure — loudness check is non-blocking.
        """
        try:
            loop = asyncio.get_event_loop()

            def _run():
                return (
                    ffmpeg
                    .input(audio_path)
                    .audio
                    .filter(
                        "loudnorm",
                        I=-16,
                        TP=-1.5,
                        LRA=11,
                        print_format="json",
                    )
                    .output("-", format="null")
                    .run(capture_stderr=True, quiet=True)
                )

            _, stderr = await loop.run_in_executor(None, _run)
            stderr_str = stderr.decode("utf-8", errors="ignore")

            # loudnorm outputs JSON block to stderr — extract it
            json_match = re.search(
                r'\{\s*"input_i"\s*:.*?\}', stderr_str, re.DOTALL
            )
            if json_match:
                data = json.loads(json_match.group())
                raw_i = data.get("input_i", str(TARGET_LOUDNESS_LUFS))
                # Google TTS silence may yield "-inf" — treat as -70
                if str(raw_i).strip().lower() in ("-inf", "inf", "nan"):
                    return -70.0
                return float(raw_i)

        except Exception as exc:
            self.log.warning("audio_validator.loudness_failed", error=str(exc))

        return None

    async def _detect_silence_gaps(
        self, audio_path: str
    ) -> list[tuple[float, float]]:
        """
        Use ffmpeg silencedetect to find gaps longer than 0.5s at -40dB.
        Returns list of (start_seconds, duration_seconds).
        """
        try:
            loop = asyncio.get_event_loop()

            def _run():
                return (
                    ffmpeg
                    .input(audio_path)
                    .audio
                    .filter("silencedetect", noise="-40dB", duration=0.5)
                    .output("-", format="null")
                    .run(capture_stderr=True, quiet=True)
                )

            _, stderr = await loop.run_in_executor(None, _run)
            stderr_str = stderr.decode("utf-8", errors="ignore")

            starts = re.findall(r"silence_start:\s*([\d.]+)", stderr_str)
            ends_durs = re.findall(
                r"silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)",
                stderr_str,
            )

            gaps: list[tuple[float, float]] = []
            for i, start_str in enumerate(starts):
                if i < len(ends_durs):
                    _, dur_str = ends_durs[i]
                    gaps.append((float(start_str), float(dur_str)))

            return gaps

        except Exception as exc:
            self.log.warning("audio_validator.silence_detect_failed", error=str(exc))
            return []

    def _pair_tts_packages(
        self,
        tts_results: list[TTSResult],
        packages: list[FinalScenePackage],
    ) -> list[tuple[TTSResult, FinalScenePackage]]:
        """Match TTS results with FinalScenePackage by scene_index."""
        pkg_map = {p.scene_index: p for p in packages}
        return [
            (t, pkg_map[t.scene_index])
            for t in tts_results
            if t.scene_index in pkg_map
]

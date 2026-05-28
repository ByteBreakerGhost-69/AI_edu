# products/edu_video/backend/layer5_rendering/subtitle_generator.py
"""
SubtitleGenerator: generates SRT and WebVTT subtitle files from scene narration
and timing data. Uses word-level timing estimation since Google TTS does not
return word timestamps in the standard synthesis response.

Timing model: proportional word distribution within each scene's audio duration.
This is accurate enough for educational subtitles without requiring word-level
TTS (which costs significantly more).
"""

import re
from pathlib import Path

import structlog
from pydantic import BaseModel

from core.config import get_settings
from core.utils import generate_uuid
from layer4_script_visual.schemas import FinalScenePackage
from layer5_rendering.timing_sync import SyncedScene

__all__ = ["SubtitleGenerator", "SubtitleEntry", "SubtitleResult", "subtitle_generator"]

logger = structlog.get_logger(__name__)
settings = get_settings()

_MAX_CHARS_PER_LINE = 42       # subtitle line length for 1080p legibility
_MAX_WORDS_PER_CUE = 10        # words per subtitle cue segment
_WORDS_PER_MINUTE = 130.0      # match TTS speaking rate assumption
_LEADING_PAUSE_SECONDS = 0.3   # gap before first word in each scene


# --------------------------------------------------------------------------- #
# Pydantic models                                                              #
# --------------------------------------------------------------------------- #

class SubtitleEntry(BaseModel):
    """One subtitle cue."""
    index: int
    start_seconds: float
    end_seconds: float
    text: str


class SubtitleResult(BaseModel):
    """Subtitle files for the complete video."""
    job_id: str
    srt_file_path: str
    vtt_file_path: str
    total_cues: int
    total_duration_seconds: float


# --------------------------------------------------------------------------- #
# SubtitleGenerator                                                            #
# --------------------------------------------------------------------------- #

class SubtitleGenerator:
    """
    Generates SRT and VTT subtitle tracks from narration text + timing data.
    Word timing is estimated proportionally — no additional API calls needed.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(__name__)

    async def generate(
        self,
        packages: list[FinalScenePackage],
        synced_scenes: list[SyncedScene],
        job_id: str,
    ) -> SubtitleResult:
        """
        Build complete subtitle files for all scenes.
        Scenes are aligned by scene_index.
        """
        log = self.log.bind(job_id=job_id)
        log.info("subtitle_generator.started", scene_count=len(packages))

        subtitle_dir = Path(settings.RENDER_TEMP_DIR) / job_id / "subtitles"
        subtitle_dir.mkdir(parents=True, exist_ok=True)

        # Build scene timing map from synced_scenes
        timing_map: dict[int, SyncedScene] = {
            s.scene_index: s for s in synced_scenes
        }

        # Calculate cumulative start time per scene
        scene_start_times: dict[int, float] = {}
        cumulative = 0.0
        for pkg in sorted(packages, key=lambda p: p.scene_index):
            scene_start_times[pkg.scene_index] = cumulative
            synced = timing_map.get(pkg.scene_index)
            duration = (
                synced.final_duration_seconds
                if synced
                else pkg.estimated_duration_seconds
            )
            cumulative += duration

        # Build all cues across all scenes
        all_cues: list[SubtitleEntry] = []
        cue_index = 1

        for pkg in sorted(packages, key=lambda p: p.scene_index):
            synced = timing_map.get(pkg.scene_index)
            scene_duration = (
                synced.final_duration_seconds
                if synced
                else pkg.estimated_duration_seconds
            )
            scene_start = scene_start_times[pkg.scene_index]

            narration = _clean_narration(
                pkg.refined_script.narration_text
            )
            scene_cues = _build_scene_cues(
                text=narration,
                scene_start=scene_start,
                scene_duration=scene_duration,
                start_index=cue_index,
            )
            all_cues.extend(scene_cues)
            cue_index += len(scene_cues)

        # Write SRT
        srt_path = subtitle_dir / f"{job_id}.srt"
        srt_path.write_text(_render_srt(all_cues), encoding="utf-8")

        # Write VTT
        vtt_path = subtitle_dir / f"{job_id}.vtt"
        vtt_path.write_text(_render_vtt(all_cues), encoding="utf-8")

        total_dur = cumulative
        log.info(
            "subtitle_generator.completed",
            total_cues=len(all_cues),
            total_duration=round(total_dur, 2),
        )

        return SubtitleResult(
            job_id=job_id,
            srt_file_path=str(srt_path),
            vtt_file_path=str(vtt_path),
            total_cues=len(all_cues),
            total_duration_seconds=total_dur,
        )


# --------------------------------------------------------------------------- #
# Cue building                                                                 #
# --------------------------------------------------------------------------- #

def _build_scene_cues(
    text: str,
    scene_start: float,
    scene_duration: float,
    start_index: int,
) -> list[SubtitleEntry]:
    """
    Distribute words across the scene duration proportionally.
    Groups words into cues of max _MAX_WORDS_PER_CUE words.
    Ensures cues never exceed scene_duration.
    """
    words = text.split()
    if not words:
        return []

    # Usable scene time (leave leading pause)
    usable_duration = max(scene_duration - _LEADING_PAUSE_SECONDS, 1.0)

    # Group into cues
    cue_groups: list[list[str]] = []
    i = 0
    while i < len(words):
        group = words[i: i + _MAX_WORDS_PER_CUE]
        cue_groups.append(group)
        i += _MAX_WORDS_PER_CUE

    total_words = len(words)
    cues: list[SubtitleEntry] = []
    cue_index = start_index
    words_placed = 0

    for group in cue_groups:
        group_word_count = len(group)

        # Proportional timing within the scene
        cue_start_offset = (words_placed / total_words) * usable_duration
        cue_end_offset = ((words_placed + group_word_count) / total_words) * usable_duration

        # Add leading pause to all offsets
        cue_start = scene_start + _LEADING_PAUSE_SECONDS + cue_start_offset
        cue_end = scene_start + _LEADING_PAUSE_SECONDS + cue_end_offset

        # Hard cap to scene boundary
        cue_end = min(cue_end, scene_start + scene_duration - 0.05)
        cue_start = min(cue_start, cue_end - 0.1)

        cues.append(SubtitleEntry(
            index=cue_index,
            start_seconds=round(cue_start, 3),
            end_seconds=round(cue_end, 3),
            text=_wrap_text(" ".join(group)),
        ))
        words_placed += group_word_count
        cue_index += 1

    return cues


# --------------------------------------------------------------------------- #
# Format renderers                                                             #
# --------------------------------------------------------------------------- #

def _render_srt(cues: list[SubtitleEntry]) -> str:
    """Render SubtitleEntry list to SRT format string."""
    lines: list[str] = []
    for cue in cues:
        lines.append(str(cue.index))
        lines.append(
            f"{_format_srt_time(cue.start_seconds)} --> {_format_srt_time(cue.end_seconds)}"
        )
        lines.append(cue.text)
        lines.append("")
    return "\n".join(lines)


def _render_vtt(cues: list[SubtitleEntry]) -> str:
    """Render SubtitleEntry list to WebVTT format string."""
    lines: list[str] = ["WEBVTT", ""]
    for cue in cues:
        lines.append(
            f"{_format_vtt_time(cue.start_seconds)} --> {_format_vtt_time(cue.end_seconds)}"
        )
        lines.append(cue.text)
        lines.append("")
    return "\n".join(lines)


def _format_srt_time(seconds: float) -> str:
    """Format seconds to SRT timestamp: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_vtt_time(seconds: float) -> str:
    """Format seconds to VTT timestamp: HH:MM:SS.mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


# --------------------------------------------------------------------------- #
# Text helpers                                                                 #
# --------------------------------------------------------------------------- #

def _clean_narration(text: str) -> str:
    """Remove SSML tags, markdown, and normalize whitespace for subtitle display."""
    text = re.sub(r"<[^>]+>", "", text)    # strip XML/SSML tags
    text = re.sub(r"[*_#`]", "", text)     # strip markdown
    text = re.sub(r"\s+", " ", text)       # collapse whitespace
    return text.strip()


def _wrap_text(text: str, max_chars: int = _MAX_CHARS_PER_LINE) -> str:
    """
    Wrap subtitle text at max_chars per line.
    Breaks at word boundary — never mid-word.
    """
    if len(text) <= max_chars:
        return text

    words = text.split()
    lines: list[str] = []
    current: list[str] = []

    for word in words:
        if sum(len(w) for w in current) + len(current) + len(word) > max_chars:
            if current:
                lines.append(" ".join(current))
                current = []
        current.append(word)

    if current:
        lines.append(" ".join(current))

    return "\n".join(lines[:2])  # max 2 lines per cue for readability


subtitle_generator = SubtitleGenerator()

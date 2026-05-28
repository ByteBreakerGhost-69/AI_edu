# products/edu_video/backend/layer5_rendering/timing_sync.py
"""
TimingSync: aligns visual video duration with TTS audio duration per scene.
Strategy hierarchy (applied in order):
  1. No-change: within ±0.5s tolerance
  2. Speed-adjust video: factor within [0.8, 1.3]
  3. Pad video: freeze last frame to fill remaining time
  4. Trim audio: cut audio to match video (last resort — loses narration)
"""

import asyncio
from pathlib import Path

import structlog
from pydantic import BaseModel

from core.config import get_settings
from layer5_rendering.tts_service import TTSResult
from layer5_rendering.animation_router import RendererResult

__all__ = ["TimingSync", "SyncedScene", "timing_sync"]

logger = structlog.get_logger(__name__)
settings = get_settings()

_SYNC_TOLERANCE = 0.5      # seconds — acceptable drift without adjustment
_MAX_SPEED_FACTOR = 1.30   # max speedup (30% faster)
_MIN_SPEED_FACTOR = 0.80   # max slowdown (20% slower)


# --------------------------------------------------------------------------- #
# Pydantic model                                                               #
# --------------------------------------------------------------------------- #

class SyncedScene(BaseModel):
    scene_index: int
    video_file_path: str
    audio_file_path: str
    final_duration_seconds: float
    sync_method: str      # "no_change"|"speed_video"|"pad_video"|"trim_audio"
    original_video_duration: float
    original_audio_duration: float


# --------------------------------------------------------------------------- #
# TimingSync                                                                   #
# --------------------------------------------------------------------------- #

class TimingSync:
    """
    Matches video duration to audio duration per scene using the least
    destructive method available. Never drops scenes — always produces output.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(__name__)

    async def sync_all(
        self,
        tts_results: list[TTSResult],
        renderer_results: list[RendererResult],
        job_id: str,
    ) -> list[SyncedScene]:
        """
        Pair TTS and render results by scene_index, sync durations concurrently.
        Scenes missing from either list are logged and skipped.
        """
        log = self.log.bind(job_id=job_id)
        log.info("timing_sync.started", scene_count=len(tts_results))

        sync_dir = Path(settings.RENDER_TEMP_DIR) / job_id / "synced"
        sync_dir.mkdir(parents=True, exist_ok=True)

        paired = self._pair_by_scene_index(tts_results, renderer_results, log)

        tasks = [
            self._sync_scene(tts, render, sync_dir, job_id)
            for tts, render in paired
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        synced: list[SyncedScene] = []
        for (tts, _), outcome in zip(paired, results):
            if isinstance(outcome, Exception):
                log.error(
                    "timing_sync.scene_failed",
                    scene_index=tts.scene_index,
                    error=str(outcome),
                )
                # Passthrough without sync as last resort
                synced.append(SyncedScene(
                    scene_index=tts.scene_index,
                    video_file_path=_get_render_path(renderer_results, tts.scene_index),
                    audio_file_path=tts.audio_file_path,
                    final_duration_seconds=tts.duration_seconds,
                    sync_method="no_change",
                    original_video_duration=tts.duration_seconds,
                    original_audio_duration=tts.duration_seconds,
                ))
            else:
                synced.append(outcome)

        synced.sort(key=lambda s: s.scene_index)
        log.info(
            "timing_sync.completed",
            methods=_count_sync_methods(synced),
        )
        return synced

    async def _sync_scene(
        self,
        tts: TTSResult,
        render: RendererResult,
        sync_dir: Path,
        job_id: str,
    ) -> SyncedScene:
        """
        Apply the least-destructive sync strategy for one scene.
        All FFmpeg operations run in executor to avoid blocking.
        """
        log = self.log.bind(job_id=job_id, scene_index=tts.scene_index)

        audio_dur = tts.duration_seconds
        video_dur = render.duration_seconds
        diff = audio_dur - video_dur  # positive = video is shorter than audio

        # ---- Strategy 1: No change ------------------------------------- #
        if abs(diff) <= _SYNC_TOLERANCE:
            log.debug("timing_sync.no_change", diff=diff)
            return SyncedScene(
                scene_index=tts.scene_index,
                video_file_path=render.video_file_path,
                audio_file_path=tts.audio_file_path,
                final_duration_seconds=audio_dur,
                sync_method="no_change",
                original_video_duration=video_dur,
                original_audio_duration=audio_dur,
            )

        # ---- Strategy 2: Speed-adjust video ----------------------------- #
        if diff > 0:
            # Video shorter than audio → need to slow video down
            speed_factor = video_dur / audio_dur  # < 1.0 = slow
            if speed_factor >= _MIN_SPEED_FACTOR:
                output = sync_dir / f"scene_{tts.scene_index:02d}_speed.mp4"
                await _speed_video(render.video_file_path, str(output), speed_factor)
                log.info("timing_sync.speed_video", factor=round(speed_factor, 3))
                return SyncedScene(
                    scene_index=tts.scene_index,
                    video_file_path=str(output),
                    audio_file_path=tts.audio_file_path,
                    final_duration_seconds=audio_dur,
                    sync_method="speed_video",
                    original_video_duration=video_dur,
                    original_audio_duration=audio_dur,
                )

            # Speed factor too low — pad with freeze frame instead
            output = sync_dir / f"scene_{tts.scene_index:02d}_padded.mp4"
            await _pad_video_freeze(render.video_file_path, str(output), audio_dur)
            log.info("timing_sync.pad_video", pad_seconds=round(diff, 2))
            return SyncedScene(
                scene_index=tts.scene_index,
                video_file_path=str(output),
                audio_file_path=tts.audio_file_path,
                final_duration_seconds=audio_dur,
                sync_method="pad_video",
                original_video_duration=video_dur,
                original_audio_duration=audio_dur,
            )

        else:
            # ---- Strategy 3: Video longer than audio -------------------- #
            speed_factor = video_dur / audio_dur  # > 1.0 = speed up
            if speed_factor <= _MAX_SPEED_FACTOR:
                output = sync_dir / f"scene_{tts.scene_index:02d}_speed.mp4"
                await _speed_video(render.video_file_path, str(output), speed_factor)
                log.info("timing_sync.speed_video", factor=round(speed_factor, 3))
                return SyncedScene(
                    scene_index=tts.scene_index,
                    video_file_path=str(output),
                    audio_file_path=tts.audio_file_path,
                    final_duration_seconds=audio_dur,
                    sync_method="speed_video",
                    original_video_duration=video_dur,
                    original_audio_duration=audio_dur,
                )

            # Speed factor too high — trim audio as last resort
            output_audio = sync_dir / f"scene_{tts.scene_index:02d}_trimmed.mp3"
            await _trim_audio(tts.audio_file_path, str(output_audio), video_dur)
            log.warning(
                "timing_sync.trim_audio",
                trimmed_seconds=round(audio_dur - video_dur, 2),
            )
            return SyncedScene(
                scene_index=tts.scene_index,
                video_file_path=render.video_file_path,
                audio_file_path=str(output_audio),
                final_duration_seconds=video_dur,
                sync_method="trim_audio",
                original_video_duration=video_dur,
                original_audio_duration=audio_dur,
            )

    def _pair_by_scene_index(
        self,
        tts_results: list[TTSResult],
        renderer_results: list[RendererResult],
        log,
    ) -> list[tuple[TTSResult, RendererResult]]:
        """Match TTS and render results by scene_index. Log unmatched scenes."""
        render_map = {r.scene_index: r for r in renderer_results}
        pairs = []
        for tts in tts_results:
            render = render_map.get(tts.scene_index)
            if render is None:
                log.warning(
                    "timing_sync.no_render_for_scene",
                    scene_index=tts.scene_index,
                )
                continue
            pairs.append((tts, render))
        return pairs


# --------------------------------------------------------------------------- #
# FFmpeg helpers (all run in executor)                                         #
# --------------------------------------------------------------------------- #

async def _speed_video(input_path: str, output_path: str, speed: float) -> None:
    """
    Adjust video playback speed using FFmpeg setpts + atempo filters.
    setpts factor = 1/speed (speed > 1 → faster, speed < 1 → slower).
    atempo only supports [0.5, 2.0] — chain for extreme values.
    """
    import ffmpeg  # noqa: PLC0415

    pts_factor = round(1.0 / speed, 6)
    atempo = _build_atempo_chain(speed)

    def _run() -> None:
        stream = ffmpeg.input(input_path)
        video = stream.video.filter("setpts", f"{pts_factor}*PTS")
        audio = stream.audio.filter_multi_output(atempo)
        (
            ffmpeg
            .output(video, audio, output_path, vcodec="libx264", acodec="aac", pix_fmt="yuv420p")
            .overwrite_output()
            .run(quiet=True)
        )

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run)


async def _pad_video_freeze(input_path: str, output_path: str, target_dur: float) -> None:
    """
    Freeze the last frame of the video to extend it to target_dur seconds.
    Uses FFmpeg tpad filter.
    """
    import ffmpeg  # noqa: PLC0415

    def _run() -> None:
        probe = ffmpeg.probe(input_path)
        v_stream = next(s for s in probe["streams"] if s["codec_type"] == "video")
        video_dur = float(v_stream.get("duration", target_dur))
        pad_secs = max(target_dur - video_dur, 0.0)

        stream = ffmpeg.input(input_path)
        video = stream.video.filter("tpad", stop_mode="clone", stop_duration=pad_secs)
        (
            ffmpeg
            .output(video, stream.audio, output_path, vcodec="libx264", acodec="aac")
            .overwrite_output()
            .run(quiet=True)
        )

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run)


async def _trim_audio(input_path: str, output_path: str, duration: float) -> None:
    """Trim audio to duration seconds."""
    import ffmpeg  # noqa: PLC0415

    def _run() -> None:
        (
            ffmpeg
            .input(input_path, t=duration)
            .output(output_path, acodec="libmp3lame", q=4)
            .overwrite_output()
            .run(quiet=True)
        )

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run)


def _build_atempo_chain(speed: float) -> str:
    """
    Build FFmpeg atempo filter string for speed adjustment.
    atempo is restricted to [0.5, 2.0] — chain multiple filters for extremes.
    """
    # atempo adjusts audio speed — chain: "atempo=1.5,atempo=1.2" etc.
    filters = []
    remaining = speed
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.4f}")
    return ",".join(filters)


# --------------------------------------------------------------------------- #
# Utility helpers                                                              #
# --------------------------------------------------------------------------- #

def _get_render_path(renderer_results: list[RendererResult], scene_index: int) -> str:
    for r in renderer_results:
        if r.scene_index == scene_index:
            return r.video_file_path
    return ""


def _count_sync_methods(scenes: list[SyncedScene]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in scenes:
        counts[s.sync_method] = counts.get(s.sync_method, 0) + 1
    return counts


timing_sync = TimingSync()

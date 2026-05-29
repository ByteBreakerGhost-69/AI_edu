# products/edu_video/backend/layer5_rendering/renderers/base_renderer.py
"""
Abstract base class for all scene renderers.
Provides shared FFmpeg utilities, temp dir management, and output validation.
Every renderer must produce: 1920×1080, 30fps, h264, yuv420p, NO audio.
"""

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path

import ffmpeg
import structlog

from core.config import get_settings
from layer4_script_visual.schemas import FinalScenePackage

__all__ = ["BaseRenderer", "RendererError"]


class RendererError(Exception):
    """Raised by any renderer on unrecoverable failure."""

    def __init__(
        self,
        message: str,
        renderer: str,
        scene_index: int,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.renderer = renderer
        self.scene_index = scene_index
        self.cause = cause


class BaseRenderer(ABC):
    """
    Abstract base for all Layer 5 renderers.
    Subclasses implement render() and renderer_name.
    All shared I/O utilities live here.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.log = structlog.get_logger(self.__class__.__name__)

    @property
    @abstractmethod
    def renderer_name(self) -> str:
        """Unique renderer identifier for logging and temp file naming."""
        ...

    @abstractmethod
    async def render(self, package: FinalScenePackage, output_path: str) -> str:
        """
        Render scene to MP4.
        Returns output_path on success.
        Raises RendererError on any failure.
        Output spec: 1920×1080, 30fps, h264, yuv420p, NO audio track.
        """
        ...

    # ------------------------------------------------------------------ #
    # Temp directory                                                        #
    # ------------------------------------------------------------------ #

    def _get_temp_dir(self, package: FinalScenePackage) -> Path:
        """Return (and create) a renderer-specific temp dir for this scene."""
        job_id = package.metadata.get("job_id", "unknown")
        temp_dir = Path(
            f"{self.settings.RENDER_TEMP_DIR}/{job_id}/render"
            f"/{package.scene_index:02d}_{self.renderer_name}"
        )
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    # ------------------------------------------------------------------ #
    # FFmpeg utilities                                                      #
    # ------------------------------------------------------------------ #

    async def _run_ffmpeg(
        self, stream, description: str = ""
    ) -> None:
        """
        Run an ffmpeg-python stream in a thread executor.
        Raises RendererError on ffmpeg.Error.
        All renderers must use this — never call .run() directly in a coroutine.
        """
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: stream.overwrite_output().run(
                    quiet=True, capture_stderr=True
                ),
            )
        except ffmpeg.Error as exc:
            stderr = exc.stderr.decode("utf-8", errors="ignore")[:500]
            raise RendererError(
                f"FFmpeg failed{' during ' + description if description else ''}: {stderr}",
                renderer=self.renderer_name,
                scene_index=0,
                cause=exc,
            ) from exc

    async def _image_to_video(
        self,
        image_path: str,
        output_path: str,
        duration: float,
        zoom_effect: bool = True,
    ) -> str:
        """
        Convert a static image to a video clip.
        zoom_effect=True: Ken Burns slow zoom in (1.0 → 1.05 over duration).
        zoom_effect=False: letterbox/pillarbox to 1920×1080.
        Output: h264, yuv420p, 30fps, no audio.
        """
        fps = self.settings.RENDER_FPS
        total_frames = int(duration * fps)

        if zoom_effect:
            stream = (
                ffmpeg
                .input(image_path, loop=1, t=duration)
                .filter("scale", 8000, -1)
                .filter(
                    "zoompan",
                    z="min(zoom+0.0005,1.05)",
                    x="iw/2-(iw/zoom/2)",
                    y="ih/2-(ih/zoom/2)",
                    d=total_frames,
                    s="1920x1080",
                    fps=fps,
                )
                .output(
                    output_path,
                    vcodec="libx264",
                    pix_fmt="yuv420p",
                    r=fps,
                    t=duration,
                )
            )
        else:
            stream = (
                ffmpeg
                .input(image_path, loop=1, t=duration)
                .filter(
                    "scale", 1920, 1080,
                    force_original_aspect_ratio="decrease",
                )
                .filter(
                    "pad", 1920, 1080,
                    "(ow-iw)/2", "(oh-ih)/2",
                    color="black",
                )
                .output(
                    output_path,
                    vcodec="libx264",
                    pix_fmt="yuv420p",
                    r=fps,
                )
            )

        await self._run_ffmpeg(stream, "image_to_video")
        return output_path

    async def _frames_to_video(
        self,
        frames_dir: str,
        output_path: str,
        duration: float,
        fps: int = 30,
        pattern: str = "frame_%04d.png",
    ) -> str:
        """Convert a directory of sequentially numbered PNG frames to MP4."""
        stream = (
            ffmpeg
            .input(f"{frames_dir}/{pattern}", framerate=fps)
            .filter(
                "scale", 1920, 1080,
                force_original_aspect_ratio="decrease",
            )
            .filter("pad", 1920, 1080, "(ow-iw)/2", "(oh-ih)/2", color="black")
            .output(
                output_path,
                vcodec="libx264",
                pix_fmt="yuv420p",
                r=fps,
                t=duration,
            )
        )
        await self._run_ffmpeg(stream, "frames_to_video")
        return output_path

    async def _matplotlib_fig_to_video(
        self,
        fig,
        output_path: str,
        duration: float,
        temp_dir: Path,
        scene_index: int,
    ) -> str:
        """
        Save a Matplotlib figure as PNG then convert to video.
        Convenience wrapper used by timeline, graph, and code renderers.
        """
        import matplotlib.pyplot as plt  # noqa: PLC0415

        image_path = str(temp_dir / f"scene_{scene_index:02d}_plot.png")
        fig.savefig(image_path, dpi=100, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        return await self._image_to_video(image_path, output_path, duration, zoom_effect=False)

    # ------------------------------------------------------------------ #
    # Color helpers                                                         #
    # ------------------------------------------------------------------ #

    def _hex_to_rgb(self, hex_color: str) -> tuple[int, int, int]:
        """Convert '#RRGGBB' → (R, G, B) integers."""
        h = hex_color.lstrip("#")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    def _hex_to_rgb_float(self, hex_color: str) -> tuple[float, float, float]:
        """Convert '#RRGGBB' → (r, g, b) floats in [0.0, 1.0] for Matplotlib."""
        r, g, b = self._hex_to_rgb(hex_color)
        return r / 255.0, g / 255.0, b / 255.0

    def _safe_color(
        self, palette: list[str], index: int, fallback: str = "#1F2937"
    ) -> str:
        """Return palette[index] or fallback if index out of range."""
        if palette and index < len(palette):
            return palette[index]
        return fallback

    # ------------------------------------------------------------------ #
    # Output validation                                                    #
    # ------------------------------------------------------------------ #

    async def _validate_output(self, output_path: str, scene_index: int) -> None:
        """
        Confirm output file exists, is at least 1 KB, and has a video stream.
        Raises RendererError if any check fails.
        """
        path = Path(output_path)
        if not path.exists() or path.stat().st_size < 1024:
            raise RendererError(
                f"Output file missing or too small: {output_path}",
                renderer=self.renderer_name,
                scene_index=scene_index,
            )
        try:
            loop = asyncio.get_event_loop()
            probe = await loop.run_in_executor(
                None, lambda: ffmpeg.probe(output_path)
            )
            has_video = any(
                s["codec_type"] == "video" for s in probe.get("streams", [])
            )
            has_audio = any(
                s["codec_type"] == "audio" for s in probe.get("streams", [])
            )
            if not has_video:
                raise RendererError(
                    f"Output has no video stream: {output_path}",
                    renderer=self.renderer_name,
                    scene_index=scene_index,
                )
            if has_audio:
                self.log.warning(
                    "renderer.output_has_audio",
                    renderer=self.renderer_name,
                    scene_index=scene_index,
                    note="Audio will be stripped by compositor.",
                )
        except ffmpeg.Error as exc:
            raise RendererError(
                f"Output validation ffprobe failed: {exc}",
                renderer=self.renderer_name,
                scene_index=scene_index,
                cause=exc,
            ) from exc

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} renderer={self.renderer_name!r}>"

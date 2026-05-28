# products/edu_video/backend/layer5_rendering/animation_router.py
"""
AnimationRouter: routes each FinalScenePackage to the correct renderer.
Groups scenes by renderer type for batching, respects per-renderer concurrency
limits, and provides black-screen fallback on any failure.

Renderers are lazy-imported to avoid circular dependencies and slow startup.
"""

import asyncio
import time
from collections import defaultdict
from pathlib import Path

import structlog
from pydantic import BaseModel

from core.config import get_settings
from layer4_script_visual.schemas import FinalScenePackage

__all__ = ["AnimationRouter", "RendererResult", "animation_router"]

logger = structlog.get_logger(__name__)
settings = get_settings()

# --------------------------------------------------------------------------- #
# Configuration                                                                #
# --------------------------------------------------------------------------- #

RENDERER_TIMEOUT_SECONDS: dict[str, int] = {
    "manim":     120,
    "lottie":     30,
    "flux_sdxl":  60,
    "kling":      90,
    "timeline":   20,
    "diagram":    20,
    "graph":      20,
    "code":       15,
}

RENDERER_COST_PER_SCENE: dict[str, float] = {
    "manim":     0.002,
    "lottie":    0.001,
    "flux_sdxl": 0.040,
    "kling":     0.250,
    "timeline":  0.001,
    "diagram":   0.001,
    "graph":     0.001,
    "code":      0.001,
}

# Max parallel render jobs per renderer type
RENDERER_CONCURRENCY: dict[str, int] = {
    "manim":     1,   # CPU-bound
    "lottie":    3,
    "flux_sdxl": 2,   # API rate limit
    "kling":     1,   # expensive
    "timeline":  4,
    "diagram":   4,
    "graph":     4,
    "code":      4,
}


# --------------------------------------------------------------------------- #
# Pydantic model                                                               #
# --------------------------------------------------------------------------- #

class RendererResult(BaseModel):
    scene_index: int
    video_file_path: str
    duration_seconds: float
    renderer_used: str
    cost_usd: float
    render_time_seconds: float
    success: bool
    error: str | None = None


# --------------------------------------------------------------------------- #
# AnimationRouter                                                              #
# --------------------------------------------------------------------------- #

class AnimationRouter:
    """
    Routes scenes to renderers, groups by type for efficient batching,
    and handles timeouts and errors with a guaranteed fallback.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(__name__)

    async def render_all(
        self,
        packages: list[FinalScenePackage],
        job_id: str,
    ) -> list[RendererResult]:
        """
        Render all scenes. Different renderer types run concurrently;
        within each type, concurrency is capped by RENDERER_CONCURRENCY.
        Returns list sorted by scene_index.
        """
        log = self.log.bind(job_id=job_id, scene_count=len(packages))
        log.info("animation_router.started")

        video_dir = Path(settings.RENDER_TEMP_DIR) / job_id / "video"
        video_dir.mkdir(parents=True, exist_ok=True)

        # Group by renderer_type
        renderer_groups: dict[str, list[FinalScenePackage]] = defaultdict(list)
        for pkg in packages:
            renderer_groups[pkg.renderer_type].append(pkg)

        group_tasks = [
            self._render_group(renderer_type, group_pkgs, job_id, video_dir)
            for renderer_type, group_pkgs in renderer_groups.items()
        ]

        group_outcomes = await asyncio.gather(*group_tasks, return_exceptions=True)

        all_results: list[RendererResult] = []
        for renderer_type, outcome in zip(renderer_groups.keys(), group_outcomes):
            if isinstance(outcome, Exception):
                log.error(
                    "animation_router.group_failed",
                    renderer_type=renderer_type,
                    error=str(outcome),
                )
                # Build fallback results for the entire group
                for pkg in renderer_groups[renderer_type]:
                    fallback_path = await self._render_fallback(pkg, video_dir)
                    all_results.append(RendererResult(
                        scene_index=pkg.scene_index,
                        video_file_path=fallback_path,
                        duration_seconds=pkg.estimated_duration_seconds,
                        renderer_used="fallback",
                        cost_usd=0.001,
                        render_time_seconds=0.0,
                        success=False,
                        error=str(outcome),
                    ))
            else:
                all_results.extend(outcome)

        all_results.sort(key=lambda r: r.scene_index)
        failed = sum(1 for r in all_results if not r.success)
        log.info(
            "animation_router.completed",
            total=len(all_results),
            failed=failed,
            total_cost=sum(r.cost_usd for r in all_results),
        )
        return all_results

    async def _render_group(
        self,
        renderer_type: str,
        packages: list[FinalScenePackage],
        job_id: str,
        video_dir: Path,
    ) -> list[RendererResult]:
        """Render all scenes of one renderer type with type-specific concurrency."""
        concurrency = RENDERER_CONCURRENCY.get(renderer_type, 2)
        semaphore = asyncio.Semaphore(concurrency)

        tasks = [
            self._render_scene(pkg, job_id, video_dir, semaphore)
            for pkg in packages
        ]
        return await asyncio.gather(*tasks)

    async def _render_scene(
        self,
        pkg: FinalScenePackage,
        job_id: str,
        video_dir: Path,
        semaphore: asyncio.Semaphore,
    ) -> RendererResult:
        """Render one scene with timeout and full error recovery."""
        async with semaphore:
            log = self.log.bind(
                job_id=job_id,
                scene_index=pkg.scene_index,
                renderer=pkg.renderer_type,
            )
            renderer_type = pkg.renderer_type
            timeout = RENDERER_TIMEOUT_SECONDS.get(renderer_type, 60)
            start = time.perf_counter()

            output_path = str(
                video_dir / f"scene_{pkg.scene_index:02d}_{renderer_type}.mp4"
            )

            try:
                renderer = self._get_renderer(renderer_type)
                result_path = await asyncio.wait_for(
                    renderer.render(pkg, output_path),
                    timeout=timeout,
                )
                elapsed = time.perf_counter() - start
                cost = RENDERER_COST_PER_SCENE.get(renderer_type, 0.001)

                log.info("animation_router.scene_rendered", duration_ms=int(elapsed * 1000))

                return RendererResult(
                    scene_index=pkg.scene_index,
                    video_file_path=result_path,
                    duration_seconds=pkg.estimated_duration_seconds,
                    renderer_used=renderer_type,
                    cost_usd=cost,
                    render_time_seconds=round(elapsed, 2),
                    success=True,
                )

            except asyncio.TimeoutError:
                log.error("animation_router.timeout", timeout_seconds=timeout)
                fallback = await self._render_fallback(pkg, video_dir)
                return RendererResult(
                    scene_index=pkg.scene_index,
                    video_file_path=fallback,
                    duration_seconds=pkg.estimated_duration_seconds,
                    renderer_used="fallback",
                    cost_usd=0.001,
                    render_time_seconds=float(timeout),
                    success=False,
                    error=f"Renderer timeout after {timeout}s",
                )

            except Exception as exc:
                elapsed = time.perf_counter() - start
                log.error("animation_router.render_error", error=str(exc))
                fallback = await self._render_fallback(pkg, video_dir)
                return RendererResult(
                    scene_index=pkg.scene_index,
                    video_file_path=fallback,
                    duration_seconds=pkg.estimated_duration_seconds,
                    renderer_used="fallback",
                    cost_usd=0.001,
                    render_time_seconds=round(elapsed, 2),
                    success=False,
                    error=str(exc),
                )

    def _get_renderer(self, renderer_type: str):
        """Lazy-import the renderer class to avoid circular imports at startup."""
        match renderer_type:
            case "manim":
                from layer5_rendering.renderers.manim_renderer import ManimRenderer  # noqa
                return ManimRenderer()
            case "lottie":
                from layer5_rendering.renderers.lottie_renderer import LottieRenderer  # noqa
                return LottieRenderer()
            case "flux_sdxl":
                from layer5_rendering.renderers.flux_sdxl_renderer import FluxSDXLRenderer  # noqa
                return FluxSDXLRenderer()
            case "kling":
                from layer5_rendering.renderers.kling_renderer import KlingRenderer  # noqa
                return KlingRenderer()
            case "timeline":
                from layer5_rendering.renderers.timeline_renderer import TimelineRenderer  # noqa
                return TimelineRenderer()
            case "diagram":
                from layer5_rendering.renderers.diagram_renderer import DiagramRenderer  # noqa
                return DiagramRenderer()
            case "graph":
                from layer5_rendering.renderers.graph_renderer import GraphRenderer  # noqa
                return GraphRenderer()
            case "code":
                from layer5_rendering.renderers.code_renderer import CodeRenderer  # noqa
                return CodeRenderer()
            case _:
                from layer5_rendering.renderers.lottie_renderer import LottieRenderer  # noqa
                return LottieRenderer()

    async def _render_fallback(
        self, pkg: FinalScenePackage, video_dir: Path
    ) -> str:
        """
        Black screen with title text overlay — absolute last resort.
        Always available since it only needs FFmpeg.
        Runs in executor to avoid blocking the event loop.
        """
        import ffmpeg  # noqa: PLC0415

        output = str(video_dir / f"scene_{pkg.scene_index:02d}_fallback.mp4")
        safe_title = (
            pkg.title.replace("'", "\\'").replace(":", "\\:")[:50]
        )
        duration = max(pkg.estimated_duration_seconds, 1.0)

        def _run() -> None:
            (
                ffmpeg
                .input(
                    "color=c=black:size=1920x1080:rate=30",
                    f="lavfi",
                    t=duration,
                )
                .drawtext(
                    text=safe_title,
                    fontcolor="white",
                    fontsize=48,
                    x="(w-text_w)/2",
                    y="(h-text_h)/2",
                )
                .output(output, vcodec="libx264", pix_fmt="yuv420p")
                .overwrite_output()
                .run(quiet=True)
            )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _run)
        return output


animation_router = AnimationRouter()

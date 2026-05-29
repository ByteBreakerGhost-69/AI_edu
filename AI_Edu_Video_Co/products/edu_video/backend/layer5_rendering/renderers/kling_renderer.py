# products/edu_video/backend/layer5_rendering/renderers/kling_renderer.py
"""
KlingRenderer: generates short video clips via the Kling AI API,
then normalises and loops/pads them to the required duration.
"""

import asyncio
from pathlib import Path

import ffmpeg
import httpx
import structlog

from layer4_script_visual.schemas import FinalScenePackage
from layer5_rendering.renderers.base_renderer import BaseRenderer, RendererError

__all__ = ["KlingRenderer"]

_POLL_INTERVAL = 5.0
_MAX_POLL_ATTEMPTS = 24   # 2 minutes total


class KlingRenderer(BaseRenderer):
    """
    Calls the Kling AI text-to-video API, downloads the result,
    then normalises/loops it to match the required scene duration.
    """

    @property
    def renderer_name(self) -> str:
        return "kling"

    async def render(self, package: FinalScenePackage, output_path: str) -> str:
        temp_dir = self._get_temp_dir(package)
        scene_idx = package.scene_index
        duration = package.estimated_duration_seconds
        anim_config = package.visual_spec.animation_config
        log = self.log.bind(
            job_id=package.metadata.get("job_id"),
            scene_index=scene_idx,
        )

        # ---- Step 1: Generate video via Kling API ----------------------- #
        raw_video_path = await self._generate_kling_video(package, temp_dir, log)

        # ---- Step 2: Normalise to standard spec + pad/loop to duration -- #
        stream = (
            ffmpeg
            .input(str(raw_video_path), stream_loop=-1, t=duration)
            .filter("scale", 1920, 1080, force_original_aspect_ratio="decrease")
            .filter("pad", 1920, 1080, "(ow-iw)/2", "(oh-ih)/2", color="black")
            .output(
                output_path,
                vcodec="libx264",
                pix_fmt="yuv420p",
                r=self.settings.RENDER_FPS,
                an=None,
                t=duration,
            )
        )
        await self._run_ffmpeg(stream, "normalise_kling_output")

        # ---- Step 3: Validate + return ---------------------------------- #
        await self._validate_output(output_path, scene_idx)
        log.info("kling_renderer.done", output=output_path)
        return output_path

    async def _generate_kling_video(
        self,
        package: FinalScenePackage,
        temp_dir: Path,
        log,
    ) -> Path:
        """Submit generation task and poll until video URL is ready."""
        prompt = (
            package.visual_spec.generation_prompt
            or package.visual_spec.primary_content
            or package.title
        )
        anim_config = package.visual_spec.animation_config

        headers = {
            "Authorization": f"Bearer {self.settings.KLING_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "prompt": f"{prompt}, educational video, appropriate for students",
            "negative_prompt": "nsfw, violence, text overlays, watermark, blurry",
            "duration": min(int(package.estimated_duration_seconds), 10),
            "aspect_ratio": "16:9",
            "mode": "standard",
            "motion_strength": anim_config.get("motion_strength", 0.7),
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.settings.KLING_API_URL}/videos/text2video",
                headers=headers,
                json=payload,
            )
            if resp.status_code not in (200, 201, 202):
                raise RendererError(
                    f"Kling API submit failed: {resp.status_code} {resp.text[:300]}",
                    renderer=self.renderer_name,
                    scene_index=package.scene_index,
                )
            task_id = resp.json().get("data", {}).get("task_id") or resp.json().get("task_id")
            if not task_id:
                raise RendererError(
                    "Kling API returned no task_id.",
                    renderer=self.renderer_name,
                    scene_index=package.scene_index,
                )

            video_url = await self._poll_kling(client, task_id, headers, log)

        if not video_url:
            raise RendererError(
                "Kling video generation timed out or failed.",
                renderer=self.renderer_name,
                scene_index=package.scene_index,
            )

        # Download
        video_path = temp_dir / f"scene_{package.scene_index:02d}_kling_raw.mp4"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(video_url)
            resp.raise_for_status()
            video_path.write_bytes(resp.content)

        log.info("kling_renderer.video_downloaded", path=str(video_path))
        return video_path

    async def _poll_kling(
        self,
        client: httpx.AsyncClient,
        task_id: str,
        headers: dict,
        log,
    ) -> str | None:
        """Poll Kling task status until complete or timeout."""
        for attempt in range(_MAX_POLL_ATTEMPTS):
            await asyncio.sleep(_POLL_INTERVAL)
            resp = await client.get(
                f"{self.settings.KLING_API_URL}/videos/text2video/{task_id}",
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                status = data.get("task_status", "")
                if status == "succeed":
                    works = data.get("task_result", {}).get("videos", [])
                    if works:
                        return works[0].get("url")
                if status in ("failed", "error"):
                    log.error("kling_renderer.task_failed", task_id=task_id)
                    return None
            log.debug("kling_renderer.polling", attempt=attempt, task_id=task_id)
        return None

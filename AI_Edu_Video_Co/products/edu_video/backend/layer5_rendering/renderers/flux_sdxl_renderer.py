# products/edu_video/backend/layer5_rendering/renderers/flux_sdxl_renderer.py
"""
FluxSDXLRenderer: generates educational images via the Flux SDXL API,
then animates them with a Ken Burns zoom effect.
"""

import asyncio
from pathlib import Path

import httpx
import structlog

from layer4_script_visual.schemas import FinalScenePackage
from layer5_rendering.renderers.base_renderer import BaseRenderer, RendererError

__all__ = ["FluxSDXLRenderer"]

_POLL_INTERVAL = 3.0   # seconds between status polls
_MAX_POLL_ATTEMPTS = 20


class FluxSDXLRenderer(BaseRenderer):
    """
    Calls the Flux Pro 1.1 API to generate an educational image,
    downloads it, then converts it to video with a Ken Burns effect.
    """

    @property
    def renderer_name(self) -> str:
        return "flux_sdxl"

    async def render(self, package: FinalScenePackage, output_path: str) -> str:
        temp_dir = self._get_temp_dir(package)
        scene_idx = package.scene_index
        anim_config = package.visual_spec.animation_config
        log = self.log.bind(
            job_id=package.metadata.get("job_id"),
            scene_index=scene_idx,
        )

        # ---- Step 1: Check for reusable asset --------------------------- #
        existing_url = anim_config.get("existing_asset_url")
        if existing_url:
            image_path = temp_dir / "scene_image.jpg"
            await self._download_image(str(existing_url), str(image_path))
            log.info("flux_sdxl_renderer.reusing_asset", url=existing_url)
        else:
            image_path = await self._generate_image(package, temp_dir, log)

        # ---- Step 2: Image → video ------------------------------------- #
        await self._image_to_video(
            str(image_path),
            output_path,
            duration=package.estimated_duration_seconds,
            zoom_effect=True,
        )

        # ---- Step 3: Validate + return ---------------------------------- #
        await self._validate_output(output_path, scene_idx)
        log.info("flux_sdxl_renderer.done", output=output_path)
        return output_path

    async def _generate_image(
        self,
        package: FinalScenePackage,
        temp_dir: Path,
        log,
    ) -> Path:
        """Submit a Flux generation request, poll for result, download image."""
        prompt = (
            package.visual_spec.generation_prompt
            or package.visual_spec.primary_content
            or package.title
        )
        safe_prompt = (
            f"{prompt}, educational illustration, appropriate for students, "
            "high quality, detailed, professional, no text overlays"
        )
        negative = (
            package.visual_spec.secondary_content
            or "nsfw, violence, inappropriate, watermark, blurry, low quality, text"
        )

        headers = {
            "x-key": self.settings.FLUX_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "prompt": safe_prompt,
            "negative_prompt": negative,
            "width": 1920,
            "height": 1080,
            "num_inference_steps": 30,
            "guidance_scale": 7.5,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            # Submit
            resp = await client.post(
                f"{self.settings.FLUX_API_URL}/flux-pro-1.1",
                headers=headers,
                json=payload,
            )
            if resp.status_code not in (200, 201, 202):
                raise RendererError(
                    f"Flux API submit failed: {resp.status_code} {resp.text[:300]}",
                    renderer=self.renderer_name,
                    scene_index=package.scene_index,
                )

            resp_json = resp.json()
            request_id = resp_json.get("id") or resp_json.get("request_id")

            # If synchronous response with image_url
            image_url = resp_json.get("result", {}).get("sample") or resp_json.get("image_url")

            # Poll for async result
            if not image_url and request_id:
                image_url = await self._poll_result(client, request_id, headers, log)

            if not image_url:
                raise RendererError(
                    "Flux API returned no image URL.",
                    renderer=self.renderer_name,
                    scene_index=package.scene_index,
                )

        # Download image
        image_path = temp_dir / f"scene_{package.scene_index:02d}_flux.jpg"
        await self._download_image(image_url, str(image_path))
        log.info("flux_sdxl_renderer.image_generated", path=str(image_path))
        return image_path

    async def _poll_result(
        self,
        client: httpx.AsyncClient,
        request_id: str,
        headers: dict,
        log,
    ) -> str | None:
        """Poll Flux API for async generation result."""
        for attempt in range(_MAX_POLL_ATTEMPTS):
            await asyncio.sleep(_POLL_INTERVAL)
            resp = await client.get(
                f"{self.settings.FLUX_API_URL}/get_result",
                headers=headers,
                params={"id": request_id},
            )
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("status", "")
                if status == "Ready":
                    return (
                        data.get("result", {}).get("sample")
                        or data.get("image_url")
                    )
                if status in ("Error", "Failed"):
                    log.error("flux_sdxl_renderer.api_error", data=data)
                    return None
            log.debug("flux_sdxl_renderer.polling", attempt=attempt, request_id=request_id)
        return None

    async def _download_image(self, url: str, path: str) -> None:
        """Download an image from URL to local path."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            Path(path).write_bytes(resp.content)

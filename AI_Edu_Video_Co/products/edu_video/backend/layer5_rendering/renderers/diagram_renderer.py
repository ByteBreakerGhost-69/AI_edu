# products/edu_video/backend/layer5_rendering/renderers/diagram_renderer.py
"""
DiagramRenderer: renders Mermaid diagram syntax to PNG via the Mermaid CLI,
then converts to video.
"""

import asyncio
import json
from pathlib import Path

import structlog

from layer4_script_visual.schemas import FinalScenePackage
from layer5_rendering.renderers.base_renderer import BaseRenderer, RendererError

__all__ = ["DiagramRenderer"]

_MMDC_TIMEOUT = 30


class DiagramRenderer(BaseRenderer):
    """
    Converts Mermaid diagram syntax (flowchart, sequence, class, ER)
    to a PNG image via mmdc CLI, then animates with a subtle zoom.
    Falls back to a text-label image if mmdc is unavailable.
    """

    @property
    def renderer_name(self) -> str:
        return "diagram"

    async def render(self, package: FinalScenePackage, output_path: str) -> str:
        temp_dir = self._get_temp_dir(package)
        scene_idx = package.scene_index
        duration = package.estimated_duration_seconds
        colors = package.visual_spec.color_palette
        log = self.log.bind(
            job_id=package.metadata.get("job_id"),
            scene_index=scene_idx,
        )

        mermaid_src = (package.visual_spec.primary_content or "").strip()
        if not mermaid_src:
            mermaid_src = f"flowchart LR\n    A[\"{package.title[:50]}\"]"

        bg_color = self._safe_color(colors, 0, "#1F2937")

        # ---- Build Mermaid config JSON ---------------------------------- #
        mermaid_config = {
            "theme": "dark",
            "themeVariables": {
                "primaryColor": self._safe_color(colors, 1, "#3B82F6"),
                "primaryTextColor": "#FFFFFF",
                "primaryBorderColor": self._safe_color(colors, 2, "#DBEAFE"),
                "lineColor": "#9CA3AF",
                "background": bg_color,
                "mainBkg": bg_color,
                "nodeBorder": self._safe_color(colors, 1, "#3B82F6"),
                "clusterBkg": bg_color,
            },
        }

        # Write Mermaid source + config files
        mmd_path = temp_dir / f"scene_{scene_idx:02d}.mmd"
        cfg_path = temp_dir / f"scene_{scene_idx:02d}_config.json"
        img_path = temp_dir / f"scene_{scene_idx:02d}_diagram.png"

        mmd_path.write_text(mermaid_src, encoding="utf-8")
        cfg_path.write_text(json.dumps(mermaid_config), encoding="utf-8")

        # ---- Run mmdc CLI ----------------------------------------------- #
        cmd = [
            self.settings.MERMAID_CLI_PATH,
            "-i", str(mmd_path),
            "-o", str(img_path),
            "--configFile", str(cfg_path),
            "--width", "1920",
            "--height", "1080",
            "--backgroundColor", bg_color.lstrip("#"),
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_MMDC_TIMEOUT
            )
            if proc.returncode != 0 or not img_path.exists():
                err = stderr.decode("utf-8", errors="ignore")[:300]
                log.warning("diagram_renderer.mmdc_failed", error=err)
                img_path = await self._fallback_diagram_image(
                    package, temp_dir, bg_color
                )
        except (asyncio.TimeoutError, FileNotFoundError) as exc:
            log.warning("diagram_renderer.mmdc_unavailable", error=str(exc))
            img_path = await self._fallback_diagram_image(package, temp_dir, bg_color)

        # ---- Image → video ---------------------------------------------- #
        await self._image_to_video(str(img_path), output_path, duration, zoom_effect=False)
        await self._validate_output(output_path, scene_idx)
        log.info("diagram_renderer.done", output=output_path)
        return output_path

    async def _fallback_diagram_image(
        self, package: FinalScenePackage, temp_dir: Path, bg_color: str
    ) -> Path:
        """Generate a plain-text fallback image when mmdc is unavailable."""
        from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415

        img = Image.new("RGB", (1920, 1080), color=self._hex_to_rgb(bg_color))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36
            )
            title_font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52
            )
        except OSError:
            font = title_font = ImageFont.load_default()

        draw.text((960, 200), package.title, fill=(255, 255, 255),
                  font=title_font, anchor="mm")
        content_preview = (package.visual_spec.primary_content or "")[:400]
        draw.multiline_text((100, 350), content_preview, fill=(180, 180, 180),
                            font=font, spacing=8)

        out_path = temp_dir / f"scene_{package.scene_index:02d}_fallback.png"
        img.save(str(out_path))
        return out_path

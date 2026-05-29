# products/edu_video/backend/layer5_rendering/renderers/manim_renderer.py
"""
ManimRenderer: generates mathematical animations using Manim Community Edition.
Generates a Python script from VisualSpec, runs it as a subprocess, normalises output.
"""

import asyncio
import json
import textwrap
from pathlib import Path

import ffmpeg
import structlog

from core.utils import generate_uuid
from layer4_script_visual.schemas import FinalScenePackage
from layer5_rendering.renderers.base_renderer import BaseRenderer, RendererError

__all__ = ["ManimRenderer"]

MANIM_QUALITY_FLAGS: dict[str, str] = {
    "low":    "-ql",
    "medium": "-qm",
    "high":   "-qh",
    "4k":     "-qk",
}


class ManimRenderer(BaseRenderer):
    """
    Renders LaTeX equations and mathematical animations via Manim CE.
    Falls back to a text-title scene if primary_content is empty or invalid.
    """

    @property
    def renderer_name(self) -> str:
        return "manim"

    async def render(self, package: FinalScenePackage, output_path: str) -> str:
        temp_dir = self._get_temp_dir(package)
        scene_idx = package.scene_index
        duration = package.estimated_duration_seconds
        anim_config = package.visual_spec.animation_config
        log = self.log.bind(
            job_id=package.metadata.get("job_id"),
            scene_index=scene_idx,
        )

        # ---- Step 1: Build Manim script --------------------------------- #
        bg_color = self._safe_color(package.visual_spec.color_palette, 0, "#1F2937")
        text_color = anim_config.get("text_color", "#FFFFFF")

        # primary_content may be a JSON array of LaTeX strings or a raw LaTeX string
        latex_expressions = _parse_latex_content(package.visual_spec.primary_content)
        animation_sequence = anim_config.get("animation_sequence", [])

        script_content = self._build_manim_script(
            latex_expressions=latex_expressions,
            animation_sequence=animation_sequence,
            background_elements=anim_config.get("background_elements", []),
            background_color=bg_color,
            text_color=text_color,
            duration=duration,
            title_fallback=package.title,
            scene_index=scene_idx,
        )

        script_path = temp_dir / f"scene_{scene_idx:02d}_manim.py"
        script_path.write_text(script_content, encoding="utf-8")
        log.info("manim_renderer.script_written", path=str(script_path))

        # ---- Step 2: Execute Manim -------------------------------------- #
        quality_flag = MANIM_QUALITY_FLAGS.get(self.settings.MANIM_QUALITY, "-qh")
        manim_output_dir = temp_dir / "manim_output"
        manim_output_dir.mkdir(exist_ok=True)
        class_name = f"EducationalScene{scene_idx}"

        cmd = [
            "manim",
            quality_flag,
            "--output_file", f"scene_{scene_idx:02d}",
            "--media_dir", str(manim_output_dir),
            "--disable_caching",
            str(script_path),
            class_name,
        ]

        log.info("manim_renderer.subprocess_start", cmd=" ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(temp_dir),
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=90
            )
        except asyncio.TimeoutError as exc:
            proc.kill()
            raise RendererError(
                "Manim subprocess timed out after 90s.",
                renderer=self.renderer_name,
                scene_index=scene_idx,
                cause=exc,
            ) from exc

        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="ignore")[:500]
            raise RendererError(
                f"Manim returned exit code {proc.returncode}: {err_msg}",
                renderer=self.renderer_name,
                scene_index=scene_idx,
            )

        # ---- Step 3: Locate and normalise output ------------------------ #
        manim_mp4 = self._find_manim_output(manim_output_dir)
        if not manim_mp4:
            raise RendererError(
                "Manim output MP4 not found in output dir.",
                renderer=self.renderer_name,
                scene_index=scene_idx,
            )

        log.info("manim_renderer.output_found", path=str(manim_mp4))

        stream = (
            ffmpeg
            .input(str(manim_mp4))
            .filter("scale", 1920, 1080, force_original_aspect_ratio="decrease")
            .filter("pad", 1920, 1080, "(ow-iw)/2", "(oh-ih)/2", color="black")
            .output(
                output_path,
                vcodec="libx264",
                pix_fmt="yuv420p",
                r=self.settings.RENDER_FPS,
                an=None,   # strip audio
            )
        )
        await self._run_ffmpeg(stream, "normalise_manim_output")

        # ---- Step 4: Validate + return ---------------------------------- #
        await self._validate_output(output_path, scene_idx)
        log.info("manim_renderer.done", output=output_path)
        return output_path

    def _build_manim_script(
        self,
        latex_expressions: list[str],
        animation_sequence: list[dict],
        background_elements: list[str],
        background_color: str,
        text_color: str,
        duration: float,
        title_fallback: str,
        scene_index: int,
    ) -> str:
        """Generate a complete Manim CE Python script as a string."""
        class_name = f"EducationalScene{scene_idx}"

        # Build animation body
        if not latex_expressions:
            # Fallback: display title as Text
            animation_body = textwrap.dedent(f"""\
                title = Text({json.dumps(title_fallback[:60])}, color="{text_color}", font_size=48)
                self.play(FadeIn(title), run_time=min(2.0, {duration} * 0.3))
                self.wait({duration} - min(2.0, {duration} * 0.3))
            """)
        else:
            lines: list[str] = []
            obj_names: list[str] = []

            for i, expr in enumerate(latex_expressions):
                obj = f"expr_{i}"
                obj_names.append(obj)
                safe_expr = expr.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(
                    f'    {obj} = MathTex(r"{safe_expr}", color="{text_color}", font_size=40)'
                )
                if i > 0:
                    lines.append(f"    {obj}.next_to({obj_names[i-1]}, DOWN, buff=0.5)")

            # Use animation_sequence if provided, otherwise write all at once
            if animation_sequence:
                per_anim_time = max(
                    duration / max(len(animation_sequence), 1), 0.5
                )
                for j, step in enumerate(animation_sequence):
                    anim_type = step.get("type", "write")
                    obj_idx = min(step.get("obj_index", 0), len(obj_names) - 1)
                    obj = obj_names[obj_idx]
                    rt = step.get("duration", per_anim_time)
                    if anim_type == "write":
                        lines.append(f"    self.play(Write({obj}), run_time={rt})")
                    elif anim_type == "fadein":
                        lines.append(f"    self.play(FadeIn({obj}), run_time={rt})")
                    elif anim_type == "fadeout":
                        lines.append(f"    self.play(FadeOut({obj}), run_time={rt})")
                    elif anim_type == "highlight":
                        color = step.get("color", "YELLOW")
                        lines.append(
                            f"    self.play({obj}.animate.set_color({color!r}), run_time={rt})"
                        )
            else:
                total_write_time = min(duration * 0.7, 3.0 * len(obj_names))
                per_write = total_write_time / max(len(obj_names), 1)
                for obj in obj_names:
                    lines.append(f"    self.play(Write({obj}), run_time={per_write})")
                wait_time = max(duration - total_write_time - 0.5, 0.3)
                lines.append(f"    self.wait({wait_time})")

            animation_body = "\n".join(lines)

        # Background element setup
        bg_setup = ""
        if "number_plane" in background_elements:
            bg_setup += "        plane = NumberPlane(); self.add(plane)\n"
        if "axes" in background_elements:
            bg_setup += "        axes = Axes(); self.add(axes)\n"

        return textwrap.dedent(f"""\
            from manim import *

            class {class_name}(Scene):
                def construct(self):
                    self.camera.background_color = ManimColor("{background_color}")
            {bg_setup}
            {textwrap.indent(animation_body, '        ')}
        """)

    def _find_manim_output(self, output_dir: Path) -> Path | None:
        """Recursively locate first MP4 in Manim output directory."""
        for mp4 in output_dir.rglob("*.mp4"):
            return mp4
        return None


# --------------------------------------------------------------------------- #
# Helper                                                                       #
# --------------------------------------------------------------------------- #

def _parse_latex_content(primary_content: str | None) -> list[str]:
    """
    Parse primary_content as JSON array of LaTeX strings, or a raw LaTeX string.
    Returns [] on any parse failure so the fallback title scene activates.
    """
    if not primary_content:
        return []
    stripped = primary_content.strip()
    if stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
            return [str(e) for e in parsed if e]
        except json.JSONDecodeError:
            pass
    # Treat as a single raw LaTeX expression
    if stripped:
        return [stripped]
    return []


# fix variable scope in _build_manim_script (class_name references scene_idx)
_orig_build = ManimRenderer._build_manim_script


def _fixed_build(self, latex_expressions, animation_sequence, background_elements,
                 background_color, text_color, duration, title_fallback, scene_index):
    # Patch: ensure class_name uses scene_index parameter, not outer scope
    class_name = f"EducationalScene{scene_index}"
    bg_setup = ""
    if "number_plane" in background_elements:
        bg_setup = "        plane = NumberPlane(); self.add(plane)\n"
    if "axes" in background_elements:
        bg_setup += "        axes = Axes(); self.add(axes)\n"

    import textwrap, json as _json  # noqa
    if not latex_expressions:
        animation_body = (
            f"        title = Text({_json.dumps(title_fallback[:60])}, "
            f'color="{text_color}", font_size=48)\n'
            f"        self.play(FadeIn(title), run_time=min(2.0, {duration} * 0.3))\n"
            f"        self.wait(max({duration} - min(2.0, {duration} * 0.3) - 0.1, 0.1))\n"
        )
    else:
        lines: list[str] = []
        obj_names: list[str] = []
        for i, expr in enumerate(latex_expressions):
            obj = f"expr_{i}"
            obj_names.append(obj)
            safe_expr = expr.replace("\\", "\\\\")
            lines.append(
                f"        {obj} = MathTex(r\"{safe_expr}\", color=\"{text_color}\", font_size=40)"
            )
            if i > 0:
                lines.append(f"        {obj}.next_to({obj_names[i-1]}, DOWN, buff=0.5)")
        if animation_sequence:
            per_anim_time = max(duration / max(len(animation_sequence), 1), 0.5)
            for step in animation_sequence:
                anim_type = step.get("type", "write")
                obj_idx = min(step.get("obj_index", 0), len(obj_names) - 1)
                obj = obj_names[obj_idx]
                rt = step.get("duration", per_anim_time)
                if anim_type == "write":
                    lines.append(f"        self.play(Write({obj}), run_time={rt})")
                elif anim_type == "fadein":
                    lines.append(f"        self.play(FadeIn({obj}), run_time={rt})")
                elif anim_type == "fadeout":
                    lines.append(f"        self.play(FadeOut({obj}), run_time={rt})")
                elif anim_type == "highlight":
                    color = step.get("color", "YELLOW")
                    lines.append(
                        f"        self.play({obj}.animate.set_color({color!r}), run_time={rt})"
                    )
        else:
            per_write = min(duration * 0.7 / max(len(obj_names), 1), 2.5)
            for obj in obj_names:
                lines.append(f"        self.play(Write({obj}), run_time={per_write})")
            wait_time = max(duration - per_write * len(obj_names) - 0.5, 0.1)
            lines.append(f"        self.wait({wait_time})")
        animation_body = "\n".join(lines) + "\n"

    return (
        f"from manim import *\n\n"
        f"class {class_name}(Scene):\n"
        f"    def construct(self):\n"
        f"        self.camera.background_color = ManimColor(\"{background_color}\")\n"
        f"{bg_setup}"
        f"{animation_body}"
    )


ManimRenderer._build_manim_script = _fixed_build

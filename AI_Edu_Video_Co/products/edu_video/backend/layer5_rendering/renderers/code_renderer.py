# products/edu_video/backend/layer5_rendering/renderers/code_renderer.py
"""
CodeRenderer: renders syntax-highlighted code using Pygments + Pillow,
with optional line highlighting. Converts to video with no zoom (static display).
"""

import re
from pathlib import Path

import structlog

from layer4_script_visual.schemas import FinalScenePackage
from layer5_rendering.renderers.base_renderer import BaseRenderer, RendererError

__all__ = ["CodeRenderer"]

_FIGURE_DPI = 100
_FONT_SIZE = 22
_LINE_HEIGHT = 34
_PADDING = 60
_MAX_LINES = 28


class CodeRenderer(BaseRenderer):
    """
    Syntax-highlights code using Pygments, composites onto a colored background
    using Pillow, and converts to a static MP4.
    """

    @property
    def renderer_name(self) -> str:
        return "code"

    async def render(self, package: FinalScenePackage, output_path: str) -> str:
        from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415
        from pygments import highlight  # noqa: PLC0415
        from pygments.lexers import get_lexer_by_name, TextLexer  # noqa: PLC0415
        from pygments.formatters import ImageFormatter  # noqa: PLC0415
        from pygments.styles import get_style_by_name  # noqa: PLC0415

        temp_dir = self._get_temp_dir(package)
        scene_idx = package.scene_index
        duration = package.estimated_duration_seconds
        colors = package.visual_spec.color_palette
        anim_config = package.visual_spec.animation_config
        log = self.log.bind(
            job_id=package.metadata.get("job_id"),
            scene_index=scene_idx,
        )

        # ---- Parse code content ----------------------------------------- #
        raw = (package.visual_spec.primary_content or "").strip()
        language, code = _extract_language_and_code(raw, anim_config)
        highlight_lines = anim_config.get("highlight_lines", [])

        log.info("code_renderer.rendering", language=language, lines=len(code.splitlines()))

        # ---- Pygments → PIL Image --------------------------------------- #
        bg_color = self._safe_color(colors, 0, "#1F2937")
        bg_rgb = self._hex_to_rgb(bg_color)

        try:
            lexer = get_lexer_by_name(language, stripall=True)
        except Exception:
            lexer = TextLexer()

        # Use monokai style for dark backgrounds
        style = get_style_by_name("monokai")

        formatter = ImageFormatter(
            style=style,
            font_name="DejaVu Sans Mono",
            font_size=_FONT_SIZE,
            line_numbers=anim_config.get("show_line_numbers", True),
            line_number_bg=bg_color,
            line_number_fg="#6B7280",
            hl_lines=highlight_lines,
            hl_color="#374151",
            image_pad=_PADDING,
        )

        code_lines = code.splitlines()[:_MAX_LINES]
        truncated_code = "\n".join(code_lines)

        # Generate Pygments image to a temp PNG
        code_img_path = temp_dir / f"scene_{scene_idx:02d}_code_raw.png"
        try:
            img_bytes = highlight(truncated_code, lexer, formatter)
            code_img_path.write_bytes(img_bytes)
        except Exception as exc:
            log.warning("code_renderer.pygments_failed", error=str(exc))
            # Fallback: white text on dark background
            code_img_path = await self._text_fallback(
                code=truncated_code, bg_rgb=bg_rgb, temp_dir=temp_dir, scene_idx=scene_idx
            )

        # ---- Composite onto 1920×1080 canvas ---------------------------- #
        canvas = Image.new("RGB", (1920, 1080), color=bg_rgb)
        code_img = Image.open(str(code_img_path)).convert("RGB")

        # Centre code image on canvas
        cw, ch = code_img.size
        scale = min(1820 / cw, 980 / ch, 1.0)
        if scale < 1.0:
            new_w, new_h = int(cw * scale), int(ch * scale)
            code_img = code_img.resize((new_w, new_h), Image.LANCZOS)
            cw, ch = new_w, new_h

        x_off = (1920 - cw) // 2
        y_off = (1080 - ch) // 2
        canvas.paste(code_img, (x_off, y_off))

        # Add scene title bar at top
        draw = ImageDraw.Draw(canvas)
        try:
            title_font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28
            )
        except OSError:
            title_font = ImageFont.load_default()

        title_text = f"{language.upper()} — {package.title[:80]}"
        draw.rectangle([(0, 0), (1920, 50)], fill=(30, 30, 30))
        draw.text((20, 10), title_text, fill=(200, 200, 200), font=title_font)

        final_img_path = str(temp_dir / f"scene_{scene_idx:02d}_final.png")
        canvas.save(final_img_path)

        # ---- Image → video (no zoom for code — static display) ---------- #
        await self._image_to_video(final_img_path, output_path, duration, zoom_effect=False)
        await self._validate_output(output_path, scene_idx)
        log.info("code_renderer.done", output=output_path)
        return output_path

    async def _text_fallback(
        self,
        code: str,
        bg_rgb: tuple[int, int, int],
        temp_dir: Path,
        scene_idx: int,
    ) -> Path:
        """Plain monospace text fallback when Pygments fails."""
        from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415

        img = Image.new("RGB", (1800, 900), color=bg_rgb)
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", _FONT_SIZE
            )
        except OSError:
            font = ImageFont.load_default()

        y = _PADDING
        for line in code.splitlines()[:_MAX_LINES]:
            draw.text((_PADDING, y), line, fill=(220, 220, 220), font=font)
            y += _LINE_HEIGHT

        path = temp_dir / f"scene_{scene_idx:02d}_code_fallback.png"
        img.save(str(path))
        return path


# --------------------------------------------------------------------------- #
# Helper                                                                       #
# --------------------------------------------------------------------------- #

def _extract_language_and_code(raw: str, anim_config: dict) -> tuple[str, str]:
    """
    Extract language identifier and code body from primary_content.
    Handles: '# language: python\\ncode...', '```python\\ncode```', or raw code.
    """
    # Markdown fence
    fence_match = re.match(r"```(\w+)?\n(.*?)```", raw, re.DOTALL)
    if fence_match:
        lang = (fence_match.group(1) or "text").lower()
        return lang, fence_match.group(2).strip()

    # Comment-style language hint: '# language: python'
    comment_match = re.match(r"#\s*language:\s*(\w+)\s*\n(.*)", raw, re.DOTALL | re.IGNORECASE)
    if comment_match:
        return comment_match.group(1).lower(), comment_match.group(2).strip()

    # Fallback to anim_config or default
    language = anim_config.get("language", "python").lower()
    return language, raw

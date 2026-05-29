# products/edu_video/backend/layer5_rendering/renderers/lottie_renderer.py
"""
LottieRenderer: renders Lottie JSON animations to MP4 via headless Chromium.
Uses pyppeteer to capture frames, converts to MP4 via FFmpeg.
"""

import json
from pathlib import Path

import structlog

from layer4_script_visual.schemas import FinalScenePackage
from layer5_rendering.renderers.base_renderer import BaseRenderer, RendererError

__all__ = ["LottieRenderer"]

# --------------------------------------------------------------------------- #
# HTML template                                                                #
# --------------------------------------------------------------------------- #

LOTTIE_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { width: 1920px; height: 1080px; overflow: hidden;
         background: {{BG_COLOR}}; }
  #animation-container { width: 1920px; height: 1080px; }
</style>
</head>
<body>
<div id="animation-container"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/bodymovin/5.12.2/lottie.min.js"></script>
<script>
  const animData = {{LOTTIE_DATA}};
  const anim = lottie.loadAnimation({
    container: document.getElementById('animation-container'),
    renderer: 'canvas',
    autoplay: false,
    loop: false,
    animationData: animData
  });
  const totalFrames = {{TOTAL_FRAMES}};
  window.renderFrame = function(frameNum) {
    return new Promise(function(resolve) {
      anim.goToAndStop(frameNum, true);
      requestAnimationFrame(function() { resolve(); });
    });
  };
  window.animReady = false;
  anim.addEventListener('DOMLoaded', function() { window.animReady = true; });
</script>
</body>
</html>"""


class LottieRenderer(BaseRenderer):
    """
    Renders Lottie JSON animations to MP4 via headless Chromium frame capture.
    Falls back to a solid-color text card if Chromium is unavailable.
    """

    @property
    def renderer_name(self) -> str:
        return "lottie"

    async def render(self, package: FinalScenePackage, output_path: str) -> str:
        temp_dir = self._get_temp_dir(package)
        scene_idx = package.scene_index
        duration = package.estimated_duration_seconds
        fps = self.settings.RENDER_FPS
        total_frames = int(duration * fps)
        anim_config = package.visual_spec.animation_config
        colors = package.visual_spec.color_palette
        log = self.log.bind(
            job_id=package.metadata.get("job_id"),
            scene_index=scene_idx,
        )

        # ---- Step 1: Build Lottie JSON ---------------------------------- #
        animation_type = anim_config.get("animation_type", "text_reveal")
        text = anim_config.get("text_overlay", package.title or "")
        key_terms = anim_config.get("key_terms_highlight", [])
        bg_color = self._safe_color(colors, 0, "#1F2937")
        accent_color = self._safe_color(colors, 1, "#3B82F6")

        lottie_data = self._get_lottie_template(
            animation_type=animation_type,
            text=text,
            key_terms=key_terms,
            bg_colors=[bg_color, accent_color],
            duration_frames=total_frames,
            fps=fps,
        )

        # ---- Step 2: Write HTML ----------------------------------------- #
        html_path = temp_dir / "lottie_scene.html"
        html_content = (
            LOTTIE_HTML_TEMPLATE
            .replace("{{LOTTIE_DATA}}", json.dumps(lottie_data))
            .replace("{{BG_COLOR}}", bg_color)
            .replace("{{TOTAL_FRAMES}}", str(total_frames))
        )
        html_path.write_text(html_content, encoding="utf-8")

        # ---- Step 3: Capture frames via Puppeteer ----------------------- #
        frames_dir = temp_dir / "frames"
        frames_dir.mkdir(exist_ok=True)

        try:
            await self._capture_frames(
                html_path=html_path,
                frames_dir=frames_dir,
                total_frames=total_frames,
                log=log,
            )
        except Exception as exc:
            log.warning(
                "lottie_renderer.puppeteer_failed_using_fallback",
                error=str(exc),
            )
            # Fallback: solid color card with title text
            return await self._render_text_fallback(
                package=package,
                output_path=output_path,
                bg_color=bg_color,
                text=text,
                duration=duration,
                temp_dir=temp_dir,
            )

        # ---- Step 4: Frames → MP4 --------------------------------------- #
        await self._frames_to_video(
            str(frames_dir), output_path, duration, fps=fps
        )

        await self._validate_output(output_path, scene_idx)
        log.info("lottie_renderer.done", output=output_path)
        return output_path

    async def _capture_frames(
        self,
        html_path: Path,
        frames_dir: Path,
        total_frames: int,
        log,
    ) -> None:
        """Capture Lottie animation frames using pyppeteer."""
        from pyppeteer import launch  # noqa: PLC0415

        browser = await launch(
            executablePath=self.settings.PUPPETEER_EXECUTABLE,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--window-size=1920,1080",
                "--disable-gpu",
            ],
            headless=True,
        )
        try:
            page = await browser.newPage()
            await page.setViewport({"width": 1920, "height": 1080})
            await page.goto(f"file://{html_path.absolute()}")
            await page.waitForFunction("window.animReady === true", timeout=10000)

            _BATCH = 10
            for frame_num in range(0, total_frames, _BATCH):
                batch_end = min(frame_num + _BATCH, total_frames)
                for f in range(frame_num, batch_end):
                    await page.evaluate(f"window.renderFrame({f})")
                    screenshot_path = frames_dir / f"frame_{f:04d}.png"
                    await page.screenshot({
                        "path": str(screenshot_path),
                        "clip": {"x": 0, "y": 0, "width": 1920, "height": 1080},
                    })
        finally:
            await browser.close()

    async def _render_text_fallback(
        self,
        package: FinalScenePackage,
        output_path: str,
        bg_color: str,
        text: str,
        duration: float,
        temp_dir: Path,
    ) -> str:
        """Generate a simple text-on-color-background video using Pillow + FFmpeg."""
        from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415

        img = Image.new("RGB", (1920, 1080), color=self._hex_to_rgb(bg_color))
        draw = ImageDraw.Draw(img)

        # Center text
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)
        except OSError:
            font = ImageFont.load_default()

        safe_text = text[:120] if text else package.title[:120]
        bbox = draw.textbbox((0, 0), safe_text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x, y = (1920 - tw) // 2, (1080 - th) // 2
        draw.text((x, y), safe_text, fill=(255, 255, 255), font=font)

        img_path = str(temp_dir / f"fallback_{package.scene_index:02d}.png")
        img.save(img_path)

        await self._image_to_video(img_path, output_path, duration, zoom_effect=False)
        await self._validate_output(output_path, package.scene_index)
        return output_path

    def _get_lottie_template(
        self,
        animation_type: str,
        text: str,
        key_terms: list[str],
        bg_colors: list[str],
        duration_frames: int,
        fps: int,
    ) -> dict:
        """Return a minimal valid Lottie JSON dict for the given animation_type."""
        bg_r, bg_g, bg_b = self._hex_to_rgb_float(bg_colors[0])
        ac_r, ac_g, ac_b = self._hex_to_rgb_float(
            bg_colors[1] if len(bg_colors) > 1 else "#3B82F6"
        )

        base = {
            "v": "5.12.2",
            "fr": fps,
            "ip": 0,
            "op": duration_frames,
            "w": 1920,
            "h": 1080,
            "nm": f"edu_{animation_type}",
            "ddd": 0,
            "assets": [],
        }

        # Background solid layer
        bg_layer = {
            "ddd": 0, "ind": 2, "ty": 1, "nm": "Background",
            "sr": 1, "ks": {
                "o": {"a": 0, "k": 100},
                "r": {"a": 0, "k": 0},
                "p": {"a": 0, "k": [960, 540, 0]},
                "a": {"a": 0, "k": [0, 0, 0]},
                "s": {"a": 0, "k": [100, 100, 100]},
            },
            "ao": 0,
            "sc": bg_colors[0],
            "sh": 1080, "sw": 1920,
            "ip": 0, "op": duration_frames, "st": 0,
            "bm": 0,
        }

        if animation_type == "fade_transition":
            text_layer = _make_text_layer(
                text=text, fps=fps, duration_frames=duration_frames,
                fade_in=True, fade_out=True,
                color=[ac_r, ac_g, ac_b],
            )
            base["layers"] = [text_layer, bg_layer]

        elif animation_type == "particle_float":
            text_layer = _make_text_layer(
                text=text, fps=fps, duration_frames=duration_frames,
                fade_in=True, fade_out=False,
                color=[1.0, 1.0, 1.0],
            )
            base["layers"] = [text_layer, bg_layer]

        else:  # "text_reveal" (default)
            text_layer = _make_text_layer(
                text=text, fps=fps, duration_frames=duration_frames,
                fade_in=True, fade_out=False,
                color=[1.0, 1.0, 1.0],
            )
            base["layers"] = [text_layer, bg_layer]

        return base


# --------------------------------------------------------------------------- #
# Lottie layer helpers                                                         #
# --------------------------------------------------------------------------- #

def _make_text_layer(
    text: str,
    fps: int,
    duration_frames: int,
    fade_in: bool,
    fade_out: bool,
    color: list[float],
) -> dict:
    """Build a minimal Lottie text layer dict."""
    fade_in_frames = min(int(fps * 0.5), duration_frames // 4)
    fade_out_frames = min(int(fps * 0.5), duration_frames // 4)

    opacity_keys: list[dict] = []
    if fade_in:
        opacity_keys.append({"t": 0, "s": [0], "e": [100]})
        opacity_keys.append({"t": fade_in_frames, "s": [100], "e": [100]})
    if fade_out:
        opacity_keys.append({"t": duration_frames - fade_out_frames, "s": [100], "e": [0]})
        opacity_keys.append({"t": duration_frames, "s": [0]})

    opacity = (
        {"a": 1, "k": opacity_keys}
        if opacity_keys
        else {"a": 0, "k": 100}
    )

    return {
        "ddd": 0, "ind": 1, "ty": 5, "nm": "Text",
        "sr": 1, "ks": {
            "o": opacity,
            "r": {"a": 0, "k": 0},
            "p": {"a": 0, "k": [960, 540, 0]},
            "a": {"a": 0, "k": [0, 0, 0]},
            "s": {"a": 0, "k": [100, 100, 100]},
        },
        "ao": 0,
        "t": {
            "d": {
                "k": [{
                    "s": {
                        "sz": [1600, 200],
                        "ps": [-800, -100],
                        "s": 56,
                        "f": "Arial",
                        "t": text[:200] if text else " ",
                        "j": 2,  # center
                        "tr": 0,
                        "lh": 67.2,
                        "ls": 0,
                        "fc": color,
                    },
                    "t": 0,
                }]
            },
            "p": {},
            "m": {"g": 1, "a": {"a": 0, "k": [0, 0]}},
            "a": [],
        },
        "ip": 0, "op": duration_frames, "st": 0, "bm": 0,
      }

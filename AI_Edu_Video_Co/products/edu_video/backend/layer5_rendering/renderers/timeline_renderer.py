# products/edu_video/backend/layer5_rendering/renderers/timeline_renderer.py
"""
TimelineRenderer: renders chronological timeline visualisations using Matplotlib.
Input: JSON array of {date, event} objects in primary_content.
"""

import json
from pathlib import Path

import structlog

from layer4_script_visual.schemas import FinalScenePackage
from layer5_rendering.renderers.base_renderer import BaseRenderer, RendererError

__all__ = ["TimelineRenderer"]

_MAX_EVENTS = 10
_FIGURE_DPI = 100


class TimelineRenderer(BaseRenderer):
    """
    Creates a horizontal or vertical timeline from event data using Matplotlib,
    saves as PNG, then converts to animated video.
    """

    @property
    def renderer_name(self) -> str:
        return "timeline"

    async def render(self, package: FinalScenePackage, output_path: str) -> str:
        import matplotlib  # noqa: PLC0415
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415
        import matplotlib.patches as mpatches  # noqa: PLC0415

        temp_dir = self._get_temp_dir(package)
        scene_idx = package.scene_index
        duration = package.estimated_duration_seconds
        colors = package.visual_spec.color_palette
        anim_config = package.visual_spec.animation_config
        log = self.log.bind(
            job_id=package.metadata.get("job_id"),
            scene_index=scene_idx,
        )

        # ---- Parse events ----------------------------------------------- #
        events = _parse_timeline_events(package.visual_spec.primary_content)
        if not events:
            events = [{"date": "N/A", "event": package.title}]

        events = events[:_MAX_EVENTS]
        log.info("timeline_renderer.events_parsed", count=len(events))

        # ---- Build figure ----------------------------------------------- #
        bg_color = self._safe_color(colors, 0, "#1F2937")
        line_color = self._safe_color(colors, 1, "#3B82F6")
        text_color = self._safe_color(colors, 3, "#F9FAFB")
        accent_color = self._safe_color(colors, 2, "#DBEAFE")

        bg_rgb = self._hex_to_rgb_float(bg_color)
        line_rgb = self._hex_to_rgb_float(line_color)
        text_rgb = self._hex_to_rgb_float(text_color)
        accent_rgb = self._hex_to_rgb_float(accent_color)

        n = len(events)
        fig, ax = plt.subplots(figsize=(19.2, 10.8), dpi=_FIGURE_DPI)
        fig.patch.set_facecolor(bg_rgb)
        ax.set_facecolor(bg_rgb)
        ax.axis("off")

        # Horizontal timeline line
        ax.plot([0.05, 0.95], [0.5, 0.5], color=line_rgb, linewidth=3,
                transform=ax.transAxes, zorder=1)

        for i, ev in enumerate(events):
            x = 0.05 + (0.90 / max(n - 1, 1)) * i if n > 1 else 0.5
            # Dot on line
            ax.plot(x, 0.5, "o", color=line_rgb, markersize=14,
                    transform=ax.transAxes, zorder=2)
            # Connector + label (alternating above/below)
            y_label = 0.70 if i % 2 == 0 else 0.30
            y_connect_end = 0.58 if i % 2 == 0 else 0.42
            ax.plot([x, x], [0.5, y_connect_end], color=line_rgb, linewidth=1.5,
                    transform=ax.transAxes, zorder=1, linestyle="--", alpha=0.6)
            # Date label
            ax.text(x, y_label + (0.06 if i % 2 == 0 else -0.06),
                    str(ev.get("date", "")),
                    ha="center", va="center", fontsize=11, fontweight="bold",
                    color=line_rgb, transform=ax.transAxes)
            # Event text (wrapped)
            event_text = str(ev.get("event", ""))[:80]
            ax.text(x, y_label, event_text,
                    ha="center", va="center", fontsize=9,
                    color=text_rgb, transform=ax.transAxes,
                    wrap=True, multialignment="center",
                    bbox=dict(
                        boxstyle="round,pad=0.3",
                        facecolor=accent_rgb,
                        edgecolor=line_rgb,
                        alpha=0.85,
                    ))

        # Title
        title = anim_config.get("title", package.title)
        ax.text(0.5, 0.92, title, ha="center", va="center",
                fontsize=22, fontweight="bold",
                color=text_rgb, transform=ax.transAxes)

        # ---- Save + convert --------------------------------------------- #
        result = await self._matplotlib_fig_to_video(
            fig=fig,
            output_path=output_path,
            duration=duration,
            temp_dir=temp_dir,
            scene_index=scene_idx,
        )

        await self._validate_output(output_path, scene_idx)
        log.info("timeline_renderer.done", output=output_path)
        return result


def _parse_timeline_events(primary_content: str | None) -> list[dict]:
    """Parse JSON array of {date, event} from primary_content."""
    if not primary_content:
        return []
    stripped = primary_content.strip()
    if stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                return [e for e in parsed if isinstance(e, dict)]
        except json.JSONDecodeError:
            pass
    return []

# products/edu_video/backend/layer5_rendering/renderers/graph_renderer.py
"""
GraphRenderer: renders economic, statistical, and scientific graphs
using Matplotlib. Parses structured graph data from primary_content JSON.
"""

import json
from pathlib import Path

import structlog

from layer4_script_visual.schemas import FinalScenePackage
from layer5_rendering.renderers.base_renderer import BaseRenderer, RendererError

__all__ = ["GraphRenderer"]

_FIGURE_DPI = 100


class GraphRenderer(BaseRenderer):
    """
    Renders charts (line, bar, scatter) from structured JSON graph data.
    Falls back to a labeled placeholder if data is missing or malformed.
    """

    @property
    def renderer_name(self) -> str:
        return "graph"

    async def render(self, package: FinalScenePackage, output_path: str) -> str:
        import matplotlib  # noqa: PLC0415
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        temp_dir = self._get_temp_dir(package)
        scene_idx = package.scene_index
        duration = package.estimated_duration_seconds
        colors = package.visual_spec.color_palette
        anim_config = package.visual_spec.animation_config
        log = self.log.bind(
            job_id=package.metadata.get("job_id"),
            scene_index=scene_idx,
        )

        graph_data = _parse_graph_data(package.visual_spec.primary_content)

        bg_color = self._safe_color(colors, 0, "#1F2937")
        bg_rgb = self._hex_to_rgb_float(bg_color)
        text_rgb = self._hex_to_rgb_float(self._safe_color(colors, 3, "#F9FAFB"))
        line_colors = [
            self._hex_to_rgb_float(self._safe_color(colors, i, "#3B82F6"))
            for i in range(1, min(len(colors), 4))
        ] or [(0.23, 0.51, 0.96)]

        chart_type = graph_data.get("type") or anim_config.get("chart_type", "line")
        x_label = graph_data.get("x_label", anim_config.get("x_axis", {}).get("label", "X"))
        y_label = graph_data.get("y_label", anim_config.get("y_axis", {}).get("label", "Y"))
        datasets = graph_data.get("datasets", [])
        title = graph_data.get("title", package.title)

        fig, ax = plt.subplots(figsize=(19.2, 10.8), dpi=_FIGURE_DPI)
        fig.patch.set_facecolor(bg_rgb)
        ax.set_facecolor(bg_rgb)

        # Style
        ax.tick_params(colors=text_rgb, labelsize=14)
        ax.xaxis.label.set_color(text_rgb)
        ax.yaxis.label.set_color(text_rgb)
        ax.title.set_color(text_rgb)
        for spine in ax.spines.values():
            spine.set_edgecolor(text_rgb)
        ax.grid(True, alpha=0.2, color=text_rgb)

        if not datasets:
            # Placeholder: empty axes with title
            ax.set_xlabel(x_label, fontsize=16)
            ax.set_ylabel(y_label, fontsize=16)
            ax.set_title(title, fontsize=22, fontweight="bold", pad=20)
            ax.text(0.5, 0.5, "Graph data not provided",
                    ha="center", va="center", transform=ax.transAxes,
                    fontsize=18, color=text_rgb, alpha=0.5)
        else:
            for idx, ds in enumerate(datasets[:4]):
                color = line_colors[idx % len(line_colors)]
                label = ds.get("label", f"Series {idx+1}")
                data = ds.get("data", [])
                if not data:
                    continue
                xs = list(range(len(data)))
                ys = [float(v) if v is not None else 0.0 for v in data]

                if chart_type == "bar":
                    width = 0.8 / max(len(datasets), 1)
                    offset = (idx - len(datasets) / 2) * width + width / 2
                    ax.bar([x + offset for x in xs], ys, width=width,
                           color=color, label=label, alpha=0.85)
                elif chart_type == "scatter":
                    ax.scatter(xs, ys, color=color, label=label, s=80, zorder=3)
                else:  # line
                    ax.plot(xs, ys, color=color, label=label,
                            linewidth=2.5, marker="o", markersize=6)

            ax.set_xlabel(x_label, fontsize=16)
            ax.set_ylabel(y_label, fontsize=16)
            ax.set_title(title, fontsize=22, fontweight="bold", pad=20)
            if len(datasets) > 1:
                legend = ax.legend(fontsize=12)
                legend.get_frame().set_facecolor(bg_rgb)
                for text in legend.get_texts():
                    text.set_color(text_rgb)

        plt.tight_layout(pad=1.5)

        result = await self._matplotlib_fig_to_video(
            fig=fig,
            output_path=output_path,
            duration=duration,
            temp_dir=temp_dir,
            scene_index=scene_idx,
        )

        await self._validate_output(output_path, scene_idx)
        log.info("graph_renderer.done", output=output_path)
        return result


def _parse_graph_data(primary_content: str | None) -> dict:
    """Parse primary_content as graph data JSON dict."""
    if not primary_content:
        return {}
    stripped = primary_content.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    return {}

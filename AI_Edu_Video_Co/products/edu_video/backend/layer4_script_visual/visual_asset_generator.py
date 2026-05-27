# products/edu_video/backend/layer4_script_visual/visual_asset_generator.py
"""
VisualAssetGenerator: takes refined scripts and produces production-ready
VisualSpec objects for every scene. Layer 5 rendering workers consume these
directly — all content must be renderer-actionable without clarification.
"""

import asyncio
import json

import structlog

from core.llm import llm_factory
from core.utils import generate_uuid, utcnow
from layer4_script_visual.difficulty_adapter import _call_llm_json
from layer4_script_visual.schemas import (
    FinalScenePackage,
    JobContext,
    Layer4Result,
    RefinedScript,
    VisualSpec,
)

__all__ = ["VisualAssetGenerator", "visual_asset_generator"]

logger = structlog.get_logger(__name__)

_VISUAL_PROMPT_TOKENS = 600
_VISUAL_COMPLETION_TOKENS = 400
_CLAUDE_INPUT_COST = 0.000003
_CLAUDE_OUTPUT_COST = 0.000015
_MAX_PARALLEL = 3

# --------------------------------------------------------------------------- #
# Renderer-specific config templates                                           #
# --------------------------------------------------------------------------- #

_DEFAULT_DIMENSIONS = {"width": 1920, "height": 1080}

_DEFAULT_ANIMATION_CONFIGS: dict[str, dict] = {
    "manim": {
        "background_color": "#1F2937",
        "frame_rate": 60,
        "pixel_height": 1080,
        "pixel_width": 1920,
        "quality": "production_quality",
        "run_time": 3.0,        # seconds per animation step (overridden per scene)
    },
    "diagram": {
        "format": "svg",
        "theme": "dark",
        "layout_direction": "LR",  # left-to-right default
        "font_size": 18,
    },
    "graph": {
        "chart_type": "line",   # overridden per scene
        "x_axis": {"label": "", "unit": ""},
        "y_axis": {"label": "", "unit": ""},
        "grid": True,
        "legend": True,
        "theme": "educational_dark",
    },
    "code": {
        "language": "python",   # overridden per scene
        "theme": "monokai",
        "font_size": 22,
        "show_line_numbers": True,
        "highlight_lines": [],
    },
    "timeline": {
        "orientation": "horizontal",
        "theme": "historical",
        "event_count": 5,       # overridden per scene
    },
    "flux_sdxl": {
        "steps": 30,
        "cfg_scale": 7.5,
        "width": 1920,
        "height": 1080,
        "style_preset": "educational-illustration",
    },
    "lottie": {
        "loop": False,
        "autoplay": True,
        "speed": 1.0,
    },
    "kling": {
        "duration_seconds": 5,
        "aspect_ratio": "16:9",
        "motion_strength": 0.7,
    },
}

# Subject-to-color palette mapping (fallback when subject_profile not available)
_SUBJECT_PALETTES: dict[str, list[str]] = {
    "mathematics":      ["#3B82F6", "#1E40AF", "#DBEAFE", "#1F2937"],
    "physics":          ["#10B981", "#064E3B", "#D1FAE5", "#111827"],
    "chemistry":        ["#F59E0B", "#78350F", "#FEF3C7", "#1F2937"],
    "biology":          ["#22C55E", "#14532D", "#DCFCE7", "#1F2937"],
    "history":          ["#DC2626", "#7F1D1D", "#FEE2E2", "#1F2937"],
    "geography":        ["#0EA5E9", "#0C4A6E", "#E0F2FE", "#1F2937"],
    "economics":        ["#8B5CF6", "#4C1D95", "#EDE9FE", "#1F2937"],
    "literature":       ["#F97316", "#7C2D12", "#FFEDD5", "#1F2937"],
    "computer_science": ["#06B6D4", "#164E63", "#CFFAFE", "#1F2937"],
    "language":         ["#EC4899", "#831843", "#FCE7F3", "#1F2937"],
}


# --------------------------------------------------------------------------- #
# VisualAssetGenerator                                                         #
# --------------------------------------------------------------------------- #

class VisualAssetGenerator:
    """
    Produces production-ready VisualSpec for each scene.
    Combines LLM-generated visual content with deterministic renderer config.
    Returns a Layer4Result containing all FinalScenePackages.
    """

    def __init__(self) -> None:
        self.llm = llm_factory.get_llm().with_fallbacks(
            [llm_factory.get_llm("grok")]
        )
        self.log = structlog.get_logger(__name__)

    async def generate(
        self,
        refined_scripts: list[RefinedScript],
        job_context: JobContext,
    ) -> Layer4Result:
        """
        Generate VisualSpec for all scenes concurrently.
        Assembles FinalScenePackage per scene and wraps in Layer4Result.
        """
        import time  # noqa: PLC0415
        t0 = time.perf_counter()

        log = self.log.bind(
            job_id=job_context.job_id,
            subject=job_context.subject,
            scene_count=len(refined_scripts),
        )
        log.info("visual_asset_generator.started")

        semaphore = asyncio.Semaphore(_MAX_PARALLEL)

        async def _generate_one(script: RefinedScript) -> FinalScenePackage:
            async with semaphore:
                return await self._generate_scene_visual(script, job_context)

        results = await asyncio.gather(
            *[_generate_one(s) for s in refined_scripts],
            return_exceptions=True,
        )

        packages: list[FinalScenePackage] = []
        errors: list[str] = []
        total_cost = 0.0

        for script, result in zip(refined_scripts, results):
            if isinstance(result, Exception):
                err = f"scene_{script.scene_index}: {result}"
                log.error("visual_asset_generator.scene_failed", error=err)
                errors.append(err)
                # Fallback: build a minimal package with empty visual spec
                packages.append(_fallback_package(script, job_context))
            else:
                packages.append(result)
                total_cost += (
                    _VISUAL_PROMPT_TOKENS * _CLAUDE_INPUT_COST
                    + _VISUAL_COMPLETION_TOKENS * _CLAUDE_OUTPUT_COST
                )

        packages.sort(key=lambda p: p.scene_index)
        duration = round(time.perf_counter() - t0, 2)

        log.info(
            "visual_asset_generator.completed",
            packages=len(packages),
            errors=len(errors),
            total_cost_usd=total_cost,
            duration_seconds=duration,
        )

        return Layer4Result(
            job_id=job_context.job_id,
            success=len(errors) == 0,
            scene_packages=packages,
            total_cost_usd=total_cost,
            processing_time_seconds=duration,
            errors=errors,
        )

    async def _generate_scene_visual(
        self,
        script: RefinedScript,
        job_context: JobContext,
    ) -> FinalScenePackage:
        """
        Generate a VisualSpec for one scene using LLM, then assemble
        the FinalScenePackage combining script + visual spec.
        """
        renderer_type = _infer_renderer_type(script)
        color_palette = _SUBJECT_PALETTES.get(
            job_context.subject.value, _SUBJECT_PALETTES["mathematics"]
        )

        system_prompt = _build_visual_system_prompt(
            job_context, renderer_type, color_palette
        )
        user_prompt = _build_visual_user_prompt(script, renderer_type)

        raw = await _call_llm_json(
            llm=self.llm,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            expected_keys=[
                "primary_content",
                "secondary_content",
                "generation_prompt",
                "animation_config_overrides",
            ],
            log=self.log.bind(
                job_id=job_context.job_id,
                scene_index=script.scene_index,
            ),
        )

        # ---- Build animation config: base + LLM overrides -------------- #
        base_config = dict(_DEFAULT_ANIMATION_CONFIGS.get(renderer_type, {}))
        overrides = raw.get("animation_config_overrides")
        if isinstance(overrides, dict):
            base_config.update(overrides)

        visual_spec = VisualSpec(
            renderer_type=renderer_type,
            primary_content=str(raw.get("primary_content") or "").strip(),
            secondary_content=_coerce_optional_str(raw.get("secondary_content")),
            color_palette=color_palette,
            dimensions=_DEFAULT_DIMENSIONS,
            animation_config=base_config,
            asset_references=[],      # populated by orchestrator from reuse_assets
            generation_prompt=_coerce_optional_str(raw.get("generation_prompt")),
        )

        package = FinalScenePackage(
            scene_index=script.scene_index,
            title=script.title,
            refined_script=script,
            visual_spec=visual_spec,
            renderer_type=renderer_type,
            estimated_duration_seconds=script.estimated_duration_seconds,
            subject=job_context.subject.value,
            curriculum=job_context.curriculum.value,
            difficulty_level=job_context.difficulty_level.value,
            language=job_context.language,
            metadata={
                "job_id": job_context.job_id,
                "user_id": job_context.user_id,
                "created_at": utcnow().isoformat(),
                "layer4_package_id": generate_uuid(),
            },
        )

        return package


# --------------------------------------------------------------------------- #
# Prompt builders                                                              #
# --------------------------------------------------------------------------- #

def _build_visual_system_prompt(
    job_context: JobContext,
    renderer_type: str,
    color_palette: list[str],
) -> str:
    renderer_instructions = _renderer_specific_instructions(renderer_type)

    return (
        f"You are an expert educational visual designer for {job_context.subject.value}.\n"
        f"Generate production-ready visual content for the '{renderer_type}' renderer.\n\n"
        f"=== RENDERER: {renderer_type.upper()} ===\n"
        f"{renderer_instructions}\n\n"
        "=== VISUAL CONSTRAINTS ===\n"
        f"Color palette: {', '.join(color_palette)}\n"
        "Dimensions: 1920×1080 (16:9)\n"
        f"Difficulty: {job_context.difficulty_level.value}\n"
        f"Curriculum: {job_context.curriculum.value}\n\n"
        "=== OUTPUT FORMAT ===\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        '  "primary_content": "main visual content (LaTeX/Mermaid/code/prompt/etc.)",\n'
        '  "secondary_content": "supporting content or null",\n'
        '  "generation_prompt": "image generation prompt for flux_sdxl/kling or null",\n'
        '  "animation_config_overrides": {}\n'
        "}"
    )


def _build_visual_user_prompt(
    script: RefinedScript,
    renderer_type: str,
) -> str:
    return (
        f"Scene {script.scene_index}: '{script.title}'\n\n"
        f"Narration ({script.estimated_word_count} words):\n{script.narration_text}\n\n"
        f"Key terms to visualize: {', '.join(script.key_terms)}\n\n"
        f"Generate primary_content for renderer: {renderer_type}\n\n"
        "Requirements:\n"
        + _renderer_content_requirements(renderer_type)
    )


def _renderer_specific_instructions(renderer_type: str) -> str:
    instructions = {
        "manim": (
            "Write complete Python Manim scene code OR provide LaTeX expressions.\n"
            "If providing LaTeX: use $$ ... $$ for display math.\n"
            "If providing Manim code: define a Scene subclass with construct() method.\n"
            "primary_content = LaTeX string or full Manim Python code.\n"
            "animation_config_overrides: set 'run_time' per step."
        ),
        "diagram": (
            "Write Mermaid diagram syntax in primary_content.\n"
            "Use: flowchart LR, sequenceDiagram, classDiagram, or erDiagram.\n"
            "Label every node and edge clearly.\n"
            "animation_config_overrides: set 'layout_direction' (LR/TB/RL/BT)."
        ),
        "graph": (
            "Describe the graph data in primary_content as JSON:\n"
            '{"type":"line|bar|scatter","x_label":"","y_label":"","datasets":[{"label":"","data":[]}]}\n'
            "animation_config_overrides: set 'chart_type', 'x_axis', 'y_axis'."
        ),
        "code": (
            "Write the complete, executable code snippet in primary_content.\n"
            "Start with a comment: # language: python (or appropriate language).\n"
            "animation_config_overrides: set 'language', 'highlight_lines':[1,2,3]."
        ),
        "timeline": (
            "List events as JSON in primary_content:\n"
            '[{"date":"1905","event":"Einstein publishes special relativity"}, ...]\n'
            "animation_config_overrides: set 'event_count'."
        ),
        "flux_sdxl": (
            "Write a detailed image generation prompt in generation_prompt.\n"
            "Include: subject, style, mood, lighting, composition, detail level.\n"
            "primary_content = brief description of what the image shows.\n"
            "Style: 'educational illustration, detailed, accurate, textbook quality'."
        ),
        "lottie": (
            "Describe the text/animation in primary_content.\n"
            "Include: text content, animation style (fade/slide/typewriter), timing.\n"
            "Format: JSON {'text': '...', 'animation': 'fade_in', 'duration': 2.0}\n"
            "animation_config_overrides: set 'speed'."
        ),
        "kling": (
            "Write a video generation prompt in generation_prompt.\n"
            "Include: scene description, camera movement, motion style, duration.\n"
            "primary_content = brief description of video content."
        ),
    }
    return instructions.get(renderer_type, "Describe the visual content in primary_content.")


def _renderer_content_requirements(renderer_type: str) -> str:
    requirements = {
        "manim":    "- Provide valid LaTeX or Manim Python code\n- All symbols must be properly escaped",
        "diagram":  "- Use valid Mermaid syntax\n- Every node must have a label",
        "graph":    "- Include axis labels with units\n- Provide actual data points where possible",
        "code":     "- Code must be syntactically correct\n- Include language comment on line 1",
        "timeline": "- Include at least 3 events with dates\n- Dates must be historically accurate",
        "flux_sdxl":"- Prompt must be detailed (50+ words)\n- Specify educational illustration style",
        "lottie":   "- Specify animation type and duration\n- Include exact text content",
        "kling":    "- Specify camera movement\n- Keep to 5-10 second scenes",
    }
    return requirements.get(renderer_type, "- Provide complete, actionable visual content")


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _infer_renderer_type(script: RefinedScript) -> str:
    """
    Extract renderer_type from the script's source scene.
    The renderer_type field is populated from the LocalizedScene which
    carries it from AnimationRouterAgent through the pipeline.
    This function provides a safe fallback path.
    """
    # RefinedScript doesn't directly carry renderer_type from the localized scene.
    # We rely on the narration content as a heuristic fallback.
    # In practice, the worker passes the renderer_type from the original scene.
    # This is a defensive fallback only.
    text_lower = script.narration_text.lower()
    if any(kw in text_lower for kw in ["equation", "formula", "theorem", "proof"]):
        return "manim"
    if any(kw in text_lower for kw in ["algorithm", "code", "function", "loop"]):
        return "code"
    if any(kw in text_lower for kw in ["timeline", "century", "era", "event"]):
        return "timeline"
    if any(kw in text_lower for kw in ["supply", "demand", "graph", "chart"]):
        return "graph"
    return "lottie"


def _coerce_optional_str(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s and s.lower() not in ("null", "none", "") else None


def _fallback_package(
    script: RefinedScript,
    job_context: JobContext,
) -> FinalScenePackage:
    """Minimal FinalScenePackage when visual generation fails."""
    color_palette = _SUBJECT_PALETTES.get(
        job_context.subject.value, _SUBJECT_PALETTES["mathematics"]
    )
    return FinalScenePackage(
        scene_index=script.scene_index,
        title=script.title,
        refined_script=script,
        visual_spec=VisualSpec(
            renderer_type="lottie",
            primary_content=json.dumps({
                "text": script.narration_text[:200],
                "animation": "fade_in",
                "duration": script.estimated_duration_seconds,
            }),
            secondary_content=None,
            color_palette=color_palette,
            dimensions=_DEFAULT_DIMENSIONS,
            animation_config=dict(_DEFAULT_ANIMATION_CONFIGS.get("lottie", {})),
            asset_references=[],
            generation_prompt=None,
        ),
        renderer_type="lottie",
        estimated_duration_seconds=script.estimated_duration_seconds,
        subject=job_context.subject.value,
        curriculum=job_context.curriculum.value,
        difficulty_level=job_context.difficulty_level.value,
        language=job_context.language,
        metadata={
            "job_id": job_context.job_id,
            "user_id": job_context.user_id,
            "created_at": utcnow().isoformat(),
            "layer4_package_id": generate_uuid(),
            "visual_generation_failed": True,
        },
    )


visual_asset_generator = VisualAssetGenerator()

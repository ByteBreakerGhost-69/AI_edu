# products/edu_video/backend/layer2_orchestrator/agents/visual_asset_agent.py
"""
VisualAssetAgent: generates renderer-ready visual descriptions for all scenes
in a single batched LLM call.

Called by: node_generate_scenes (graph.py), immediately after ScriptAgent
Depends on: scenes (with narration_text filled), subject_profile, renderer_preference

Cost: ~1800 tokens ≈ $0.0051 per invocation (Claude claude-sonnet-4-5)
      Scales slightly with scene count and narration length.
"""

import json

from layer2_orchestrator.agents.base_agent import BaseAgent
from layer2_orchestrator.graph import GraphState, SceneData

__all__ = ["VisualAssetAgent"]

# Token estimates
_EST_PROMPT_TOKENS: int = 1000
_EST_COMPLETION_TOKENS_PER_SCENE: int = 130  # description + elements + color hints

# How many chars of narration_text to include in the batch prompt per scene.
# Enough context without ballooning the prompt for long narrations.
_NARRATION_PREVIEW_CHARS: int = 250

# Valid hex color pattern — used to filter LLM color_hints output
import re
_HEX_COLOR_PATTERN = re.compile(r"^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")


class VisualAssetAgent(BaseAgent):
    """
    Takes scenes with narration_text and generates a concrete visual_description
    for each, plus visual_elements and color_hints stored in render_metadata.

    All scenes are processed in one LLM call (batch) to minimize
    latency and cost. Results are merged back into the scenes list by
    scene_index so ordering is guaranteed even if the LLM reorders output.

    Reads from GraphState:
        scenes             — list[SceneData] with narration_text filled
        subject_profile    — for visual_style config
        renderer_preference — for renderer-aware description hints
        subject            — for subject-specific visual instruction

    Writes to GraphState:
        scenes             — same list with visual_description and
                             render_metadata.visual_elements +
                             render_metadata.color_hints filled
        total_cost_usd     — accumulated via _record_cost
        cost_breakdown     — accumulated via _record_cost
        current_node       — "node_generate_scenes"

    On any exception: returns scenes unchanged so AnimationRouterAgent
    can still assign renderers (visual_description will be empty string).
    """

    @property
    def agent_name(self) -> str:
        return "visual_asset_agent"

    async def run(self, state: GraphState) -> dict:
        job_id = state["job_id"]
        scenes = state.get("scenes", [])
        log = self.log.bind(
            job_id=job_id,
            subject=state["subject"],
            scene_count=len(scenes),
        )
        log.info("visual_asset_agent.started")

        with self._timer() as t:

            # ---------------------------------------------------------- #
            # Guard: nothing to process                                    #
            # ---------------------------------------------------------- #
            if not scenes:
                log.warning("visual_asset_agent.no_scenes — returning unchanged")
                return {
                    "scenes": [],
                    "current_node": "node_generate_scenes",
                    **self._record_cost(job_id, 0, 0.0, state),
                }

            try:
                system_prompt = _build_system_prompt(state)
                user_prompt = _build_user_prompt(scenes)

                raw = await self._call_llm_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    job_id=job_id,
                    expected_keys=["visual_descriptions"],
                )

                visual_map = _extract_visual_map(raw, log)
                updated_scenes = _merge_visuals_into_scenes(scenes, visual_map, log)

                completion_tokens = _EST_COMPLETION_TOKENS_PER_SCENE * len(scenes)
                total_tokens = _EST_PROMPT_TOKENS + completion_tokens
                cost_usd = self._estimate_cost(_EST_PROMPT_TOKENS, completion_tokens)

                matched = sum(
                    1 for s in updated_scenes
                    if s.get("visual_description")
                )

                log.info(
                    "visual_asset_agent.completed",
                    scenes_total=len(updated_scenes),
                    scenes_matched=matched,
                    scenes_unmatched=len(updated_scenes) - matched,
                    total_tokens=total_tokens,
                    cost_usd=cost_usd,
                    duration_ms=t["elapsed_ms"],
                )

                return {
                    "scenes": updated_scenes,
                    "current_node": "node_generate_scenes",
                    **self._record_cost(job_id, total_tokens, cost_usd, state),
                }

            except Exception as exc:
                log.error(
                    "visual_asset_agent.failed",
                    error=str(exc),
                    duration_ms=t["elapsed_ms"],
                )
                # Return scenes unchanged — empty visual_description is
                # handled gracefully by AnimationRouterAgent (falls back
                # to content_type-based routing).
                return self._safe_return(
                    state,
                    error=str(exc),
                    defaults={
                        "scenes": scenes,
                        "current_node": "node_generate_scenes",
                    },
                )


# --------------------------------------------------------------------------- #
# Prompt builders                                                              #
# --------------------------------------------------------------------------- #

def _build_system_prompt(state: GraphState) -> str:
    """
    Build system prompt. Encodes visual style constraints and
    per-content-type description conventions so output is
    renderer-actionable without ambiguity.
    """
    profile = state.get("subject_profile", {})
    visual_style = profile.get("visual_style", {})
    renderer_preference = state.get("renderer_preference", ["lottie"])

    color_palette = visual_style.get("color_palette", [])
    layout = visual_style.get("layout", "default")
    font_emphasis = visual_style.get("font_emphasis", "normal")
    animation_speed = visual_style.get("animation_speed", "moderate")

    palette_hint = (
        f"Preferred color palette: {', '.join(color_palette)}"
        if color_palette
        else "No specific color palette — use subject-appropriate colors."
    )

    return (
        f"You are an expert educational visual designer for {state['subject']} content.\n\n"

        "=== VISUAL STYLE ===\n"
        f"Layout: {layout}\n"
        f"Font emphasis: {font_emphasis}\n"
        f"Animation speed: {animation_speed}\n"
        f"{palette_hint}\n\n"

        "=== AVAILABLE RENDERERS ===\n"
        f"{_renderer_capability_block(renderer_preference)}\n\n"

        "=== DESCRIPTION CONVENTIONS ===\n"
        "Write descriptions specific enough that a renderer can execute "
        "without asking follow-up questions. Follow these rules per content type:\n\n"
        "  equation  → Write the complete expression in LaTeX notation. "
        "Example: '$$\\frac{d}{dx}[x^n] = nx^{n-1}$$'. "
        "Include axis labels if a plot is needed.\n\n"
        "  diagram   → Name every component, label every arrow, specify spatial layout "
        "(left→right, top→bottom). "
        "Example: 'Flowchart: oval START → rectangle PROCESS → diamond DECISION → oval END'.\n\n"
        "  graph     → Specify: axis names with units, data range, curve shape/trend, "
        "any labeled points. "
        "Example: 'Supply-demand graph: Price ($/unit) on Y, Quantity on X, "
        "downward-sloping demand curve D1, equilibrium at P=10 Q=50'.\n\n"
        "  image     → Describe subject, artistic style, mood, lighting, foreground/background. "
        "Example: 'Detailed scientific illustration of a plant cell, "
        "cross-section view, labeled organelles, clean white background, "
        "biology textbook style'.\n\n"
        "  code      → Specify language, then write the exact code snippet. "
        "Example: 'Python: def factorial(n): return 1 if n==0 else n*factorial(n-1)'. "
        "Include syntax highlighting hints.\n\n"
        "  text      → Describe animated text layout: font size, position, "
        "reveal style. "
        "Example: 'Large centered title text: PHOTOSYNTHESIS, fade-in, "
        "subtitle: Converting light to energy, slide-up'.\n\n"

        "=== OUTPUT FORMAT ===\n"
        "Return a single JSON object. No markdown. No prose outside JSON."
    )


def _build_user_prompt(scenes: list[SceneData]) -> str:
    """
    Build user prompt with a compact batch representation of all scenes.
    Truncates narration to _NARRATION_PREVIEW_CHARS to keep prompt manageable
    while preserving enough context for the LLM to infer visual needs.
    """
    scenes_payload = []
    for scene in scenes:
        # Skip placeholder scenes — no visual needed
        is_placeholder = scene.get("render_metadata", {}).get(
            "is_placeholder", False
        )
        scenes_payload.append({
            "scene_index": scene["scene_index"],
            "title": scene["title"],
            "narration": scene["narration_text"][:_NARRATION_PREVIEW_CHARS],
            "content_type": scene.get("render_metadata", {}).get(
                "content_type", "text"
            ),
            "is_placeholder": is_placeholder,
        })

    return (
        "Generate visual descriptions for each scene below.\n"
        "Skip placeholder scenes (is_placeholder: true) — "
        "return an empty visual_description for those.\n\n"
        f"Scenes:\n{json.dumps(scenes_payload, indent=2)}\n\n"
        "Return JSON:\n"
        "{\n"
        '  "visual_descriptions": [\n'
        "    {\n"
        '      "scene_index": 0,\n'
        '      "visual_description": "Renderer-ready description...",\n'
        '      "visual_elements": ["element1", "element2"],\n'
        '      "color_hints": ["#3B82F6", "#1F2937"]\n'
        "    }\n"
        "    // one entry per scene, same count as input\n"
        "  ]\n"
        "}"
    )


# --------------------------------------------------------------------------- #
# Response parsers                                                             #
# --------------------------------------------------------------------------- #

def _extract_visual_map(
    raw: dict,
    log,
) -> dict[int, dict]:
    """
    Extract visual_descriptions from raw LLM response and index by scene_index
    for O(1) lookup during merge.

    Returns:
        {scene_index: {visual_description, visual_elements, color_hints}}

    Drops entries with missing or invalid scene_index — logs each drop.
    """
    raw_list = raw.get("visual_descriptions")

    if not raw_list:
        log.warning("visual_asset_agent.empty_visual_descriptions_in_response")
        return {}

    if not isinstance(raw_list, list):
        log.warning(
            "visual_asset_agent.visual_descriptions_not_a_list",
            type_received=type(raw_list).__name__,
        )
        return {}

    visual_map: dict[int, dict] = {}

    for entry in raw_list:
        if not isinstance(entry, dict):
            continue

        raw_index = entry.get("scene_index")
        try:
            idx = int(raw_index)
        except (TypeError, ValueError):
            log.warning(
                "visual_asset_agent.invalid_scene_index_dropped",
                raw_index=raw_index,
            )
            continue

        visual_map[idx] = {
            "visual_description": _extract_visual_description(entry),
            "visual_elements": _extract_visual_elements(entry, log, idx),
            "color_hints": _extract_color_hints(entry, log, idx),
        }

    return visual_map


def _merge_visuals_into_scenes(
    scenes: list[SceneData],
    visual_map: dict[int, dict],
    log,
) -> list[SceneData]:
    """
    Merge visual descriptions back into the scene list by scene_index.
    Scenes without a matching entry in visual_map keep their empty
    visual_description — this is logged as a warning but not an error.

    Returns a new list (does not mutate input scenes).
    """
    updated: list[SceneData] = []

    for scene in scenes:
        idx = scene["scene_index"]
        match = visual_map.get(idx)

        if match is None:
            log.warning(
                "visual_asset_agent.no_visual_for_scene",
                scene_index=idx,
                title=scene.get("title"),
            )
            updated.append(scene)
            continue

        # Build updated scene — copy to avoid mutating shared GraphState reference
        updated_scene = dict(scene)
        updated_scene["visual_description"] = match["visual_description"]

        # Merge into render_metadata without overwriting existing keys
        # (content_type and is_placeholder set by ScriptAgent must survive)
        meta = dict(updated_scene.get("render_metadata") or {})
        meta["visual_elements"] = match["visual_elements"]
        meta["color_hints"] = match["color_hints"]
        updated_scene["render_metadata"] = meta

        updated.append(updated_scene)  # type: ignore[arg-type]

    return updated


# --------------------------------------------------------------------------- #
# Field extractors                                                             #
# --------------------------------------------------------------------------- #

def _extract_visual_description(entry: dict) -> str:
    """Return stripped visual_description string, or empty string."""
    raw = entry.get("visual_description")
    if not raw:
        return ""
    return str(raw).strip()


def _extract_visual_elements(entry: dict, log, scene_index: int) -> list[str]:
    """
    Return a list of visual element strings.
    Filters out non-string items; coerces if possible.
    """
    raw = entry.get("visual_elements")
    if not raw or not isinstance(raw, list):
        return []

    result = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
        elif item is not None:
            coerced = str(item).strip()
            if coerced:
                result.append(coerced)

    return result


def _extract_color_hints(entry: dict, log, scene_index: int) -> list[str]:
    """
    Return a list of validated hex color strings.
    Invalid hex values are dropped with a debug log — not a warning,
    since color_hints are aesthetic hints, not functional requirements.
    """
    raw = entry.get("color_hints")
    if not raw or not isinstance(raw, list):
        return []

    valid = []
    for item in raw:
        if not isinstance(item, str):
            continue
        color = item.strip()
        if _HEX_COLOR_PATTERN.match(color):
            valid.append(color)
        else:
            log.debug(
                "visual_asset_agent.invalid_color_hint_dropped",
                scene_index=scene_index,
                value=color,
            )

    return valid


# --------------------------------------------------------------------------- #
# Renderer capability block                                                    #
# --------------------------------------------------------------------------- #

def _renderer_capability_block(renderer_preference: list[str]) -> str:
    """
    Generate a renderer capability description based on what renderers
    are available for this subject. Only includes renderers in the
    subject's preference list so the LLM doesn't suggest unavailable ones.
    """
    capabilities = {
        "manim":     "manim     → LaTeX equations, geometric animations, function plots",
        "diagram":   "diagram   → flowcharts, circuit diagrams, force diagrams, molecular structures, maps",
        "graph":     "graph     → supply/demand curves, statistical charts, economic models, data plots",
        "code":      "code      → syntax-highlighted code with language label",
        "timeline":  "timeline  → chronological event sequences with dates",
        "flux_sdxl": "flux_sdxl → photorealistic or illustrated images (biology, history, geography)",
        "lottie":    "lottie    → animated text, transitions, particle effects, simple motion",
        "kling":     "kling     → short video clips, cinematic sequences",
    }

    lines = []
    for renderer in renderer_preference:
        cap = capabilities.get(renderer)
        if cap:
            lines.append(f"  {cap}")

    return "\n".join(lines) if lines else "  lottie → animated text and transitions"

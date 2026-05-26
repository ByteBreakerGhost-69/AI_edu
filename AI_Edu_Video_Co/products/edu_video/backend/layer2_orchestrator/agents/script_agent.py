# products/edu_video/backend/layer2_orchestrator/agents/script_agent.py
"""
ScriptAgent: generates narration_text for ALL scenes in a single LLM call.

Called by: node_generate_scenes (graph.py), before VisualAssetAgent
Depends on: subject_profile, curriculum_standards, learning_objectives,
            prerequisite_concepts, memory_context (all set by prior agents)

Cost: ~2000 tokens ≈ $0.0057 per invocation (Claude claude-sonnet-4-5)
      Scales slightly with target_scene_count and input_text length.
"""

import json

from layer2_orchestrator.agents.base_agent import BaseAgent
from layer2_orchestrator.graph import GraphState, SceneData

__all__ = ["ScriptAgent"]

# Token estimates — completion scales with scene count
_EST_PROMPT_TOKENS: int = 800
_EST_COMPLETION_TOKENS_PER_SCENE: int = 200  # ~120 words per scene narration

# Narration reading speed used for duration estimation
_WORDS_PER_MINUTE: float = 130.0

# Buffer added to every scene for visual transition time
_SCENE_BUFFER_SECONDS: float = 5.0

# Hard cap on input_text sent to LLM — 1000 chars is enough context
_INPUT_TEXT_PREVIEW_CHARS: int = 1000

# Valid content_type values — anything else gets coerced to "text"
_VALID_CONTENT_TYPES = frozenset(
    {"equation", "diagram", "text", "graph", "code", "image"}
)


class ScriptAgent(BaseAgent):
    """
    Generates narration scripts for all scenes in one LLM call.

    Output scenes have narration_text, title, scene_index, duration_seconds,
    and render_metadata.content_type filled. visual_description and
    renderer_type are intentionally left empty — those are filled by
    VisualAssetAgent and AnimationRouterAgent respectively.

    Reads from GraphState:
        subject, curriculum, difficulty_level, language, title,
        input_text, target_scene_count, subject_profile,
        curriculum_standards, learning_objectives,
        prerequisite_concepts, memory_context

    Writes to GraphState:
        scenes         — list[SceneData] with narration filled
        total_cost_usd — accumulated via _record_cost
        cost_breakdown — accumulated via _record_cost
        current_node   — "node_generate_scenes"
    """

    @property
    def agent_name(self) -> str:
        return "script_agent"

    async def run(self, state: GraphState) -> dict:
        job_id = state["job_id"]
        target = state["target_scene_count"]
        log = self.log.bind(
            job_id=job_id,
            subject=state["subject"],
            target_scene_count=target,
            difficulty=state["difficulty_level"],
        )
        log.info("script_agent.started")

        with self._timer() as t:
            try:
                system_prompt = _build_system_prompt(state)
                user_prompt = _build_user_prompt(state)

                raw = await self._call_llm_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    job_id=job_id,
                    expected_keys=["scenes"],
                )

                raw_scenes = _extract_raw_scenes(raw, log)
                raw_scenes = _normalize_scene_count(raw_scenes, target, log)
                scenes = _build_scene_data_list(raw_scenes)

                # Completion tokens scale with how many scenes were generated
                completion_tokens = _EST_COMPLETION_TOKENS_PER_SCENE * len(scenes)
                total_tokens = _EST_PROMPT_TOKENS + completion_tokens
                cost_usd = self._estimate_cost(_EST_PROMPT_TOKENS, completion_tokens)

                log.info(
                    "script_agent.completed",
                    scenes_generated=len(scenes),
                    total_tokens=total_tokens,
                    cost_usd=cost_usd,
                    duration_ms=t["elapsed_ms"],
                )

                return {
                    "scenes": scenes,
                    "current_node": "node_generate_scenes",
                    **self._record_cost(job_id, total_tokens, cost_usd, state),
                }

            except Exception as exc:
                log.error(
                    "script_agent.failed",
                    error=str(exc),
                    duration_ms=t["elapsed_ms"],
                )
                return self._safe_return(
                    state,
                    error=str(exc),
                    defaults={
                        "scenes": [],
                        "current_node": "node_generate_scenes",
                    },
                )


# --------------------------------------------------------------------------- #
# Prompt builders                                                              #
# --------------------------------------------------------------------------- #

def _build_system_prompt(state: GraphState) -> str:
    """
    Build the system prompt. Injects all context that shapes the
    writing style and content scope — not the specific topic.
    """
    target = state["target_scene_count"]
    profile = state.get("subject_profile", {})
    guidelines = profile.get("script_guidelines", "")
    memory_context = state.get("memory_context") or "None — this is a fresh topic."

    scene_template_hint = _scene_template_hint(profile, target)

    return (
        f"You are an expert educational scriptwriter producing narration for a "
        f"{state['difficulty_level']}-level {state['subject']} video.\n\n"

        f"=== JOB CONTEXT ===\n"
        f"Curriculum: {state['curriculum']}\n"
        f"Output language: {state['language']}\n"
        f"Learning objectives:\n{_numbered_list(state.get('learning_objectives', []))}\n"
        f"Prerequisite concepts the viewer already knows:\n"
        f"{_numbered_list(state.get('prerequisite_concepts', []))}\n\n"

        f"=== WRITING GUIDELINES ===\n"
        f"{guidelines}\n\n"

        f"=== MEMORY CONTEXT (similar past videos) ===\n"
        f"{memory_context}\n\n"

        f"=== SCENE STRUCTURE ===\n"
        f"Generate exactly {target} scenes.\n"
        f"{scene_template_hint}\n"
        f"Each narration: 60–120 words. Conversational but precise. "
        f"No filler phrases ('In this video we will...'). "
        f"Start each scene with substance, not setup.\n\n"

        "=== OUTPUT FORMAT ===\n"
        "Return a single JSON object. "
        "No prose before or after. "
        "No markdown fences."
    )


def _build_user_prompt(state: GraphState) -> str:
    """
    Build the user prompt. Contains the specific topic and content
    the LLM should base the script on.
    """
    target = state["target_scene_count"]

    if state["input_text"]:
        content_block = (
            f"Source content (first {_INPUT_TEXT_PREVIEW_CHARS} chars):\n"
            f"{state['input_text'][:_INPUT_TEXT_PREVIEW_CHARS]}"
        )
    else:
        content_block = (
            "Source content: Image-based input — no text available.\n"
            "Base the script on the title and curriculum standards below."
        )

    standards = state.get("curriculum_standards", [])
    standards_block = (
        "\n".join(f"  - {s}" for s in standards)
        if standards
        else "  (none specified — use subject knowledge)"
    )

    scene_index_range = f"0 to {target - 1}"

    return (
        f"Topic title: {state['title']}\n\n"
        f"{content_block}\n\n"
        f"Curriculum standards to cover:\n{standards_block}\n\n"
        f"Return JSON:\n"
        "{\n"
        '  "scenes": [\n'
        "    {\n"
        f'      "scene_index": 0,           // integer, {scene_index_range}\n'
        '      "title": "...",             // short scene title, max 60 chars\n'
        '      "narration_text": "...",    // 60-120 words of spoken narration\n'
        '      "content_type": "..."       // one of: equation|diagram|text|graph|code|image\n'
        "    }\n"
        f"    // ... exactly {target} scenes total\n"
        "  ]\n"
        "}"
    )


# --------------------------------------------------------------------------- #
# Response parsers                                                             #
# --------------------------------------------------------------------------- #

def _extract_raw_scenes(raw: dict, log) -> list[dict]:
    """
    Pull the scenes list out of the LLM response dict.
    Handles: None (all-retries-failed), non-list, empty list.
    """
    scenes_value = raw.get("scenes")

    if not scenes_value:
        log.warning("script_agent.empty_scenes_in_response")
        return []

    if not isinstance(scenes_value, list):
        log.warning(
            "script_agent.scenes_not_a_list",
            type_received=type(scenes_value).__name__,
        )
        return []

    # Filter out non-dict items (LLM occasionally returns strings in the list)
    valid = [s for s in scenes_value if isinstance(s, dict)]
    if len(valid) < len(scenes_value):
        log.warning(
            "script_agent.non_dict_scenes_dropped",
            total=len(scenes_value),
            valid=len(valid),
        )

    return valid


def _normalize_scene_count(
    scenes: list[dict],
    target: int,
    log,
) -> list[dict]:
    """
    Ensure exactly `target` scene dicts are returned.

    Truncation: drop trailing scenes (keep the first `target`).
    Padding: append minimal placeholder dicts so downstream parsing
             doesn't produce a scene list shorter than target.
             Placeholders are flagged so fact_checker_agent can identify them.
    """
    actual = len(scenes)

    if actual == target:
        return scenes

    if actual > target:
        log.warning(
            "script_agent.truncating_scenes",
            received=actual,
            target=target,
        )
        return scenes[:target]

    # actual < target — pad with placeholders
    log.warning(
        "script_agent.padding_scenes",
        received=actual,
        target=target,
        padding=target - actual,
    )
    padded = list(scenes)
    for i in range(actual, target):
        padded.append({
            "scene_index": i,
            "title": f"Scene {i}",
            "narration_text": (
                "This scene could not be generated. "
                "Please review and expand the source content."
            ),
            "content_type": "text",
            "_is_placeholder": True,  # flag for fact_checker_agent
        })
    return padded


def _build_scene_data_list(raw_scenes: list[dict]) -> list[SceneData]:
    """
    Convert raw LLM response dicts into typed SceneData TypedDicts.
    Coerces and sanitizes each field — never raises on bad LLM output.
    """
    scenes: list[SceneData] = []

    for i, raw in enumerate(raw_scenes):
        narration = _coerce_str(raw.get("narration_text"), fallback="")
        content_type = _coerce_content_type(raw.get("content_type"))

        scene: SceneData = {
            "scene_index": _coerce_int(raw.get("scene_index"), fallback=i),
            "title": _coerce_str(raw.get("title"), fallback=f"Scene {i}"),
            "narration_text": narration,
            "visual_description": "",   # filled by VisualAssetAgent
            "renderer_type": "",        # filled by AnimationRouterAgent
            "duration_seconds": _estimate_duration(narration),
            "render_metadata": {
                "content_type": content_type,
                "is_placeholder": raw.get("_is_placeholder", False),
            },
            "llm_cost_usd": 0.0,        # filled by cost tracker post-render
            "fact_checked": False,
        }
        scenes.append(scene)

    return scenes


# --------------------------------------------------------------------------- #
# Duration estimation                                                          #
# --------------------------------------------------------------------------- #

def _estimate_duration(narration_text: str) -> float:
    """
    Estimate scene audio duration in seconds based on word count.
    Formula: (words / 130 wpm) * 60 + 5s visual transition buffer.

    Returns 5.0 minimum (the buffer) for empty narration.
    """
    word_count = len(narration_text.split())
    if word_count == 0:
        return _SCENE_BUFFER_SECONDS
    return round((word_count / _WORDS_PER_MINUTE) * 60 + _SCENE_BUFFER_SECONDS, 1)


# --------------------------------------------------------------------------- #
# Field coercers                                                               #
# --------------------------------------------------------------------------- #

def _coerce_str(value, fallback: str) -> str:
    """Return stripped string or fallback if value is None/empty."""
    if value is None:
        return fallback
    coerced = str(value).strip()
    return coerced if coerced else fallback


def _coerce_int(value, fallback: int) -> int:
    """Return int or fallback on conversion failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_content_type(value) -> str:
    """
    Validate content_type against allowed values.
    Falls back to "text" for anything invalid — better than crashing
    AnimationRouterAgent with an unknown content_type.
    """
    if isinstance(value, str) and value.strip().lower() in _VALID_CONTENT_TYPES:
        return value.strip().lower()
    return "text"


# --------------------------------------------------------------------------- #
# Prompt formatting helpers                                                    #
# --------------------------------------------------------------------------- #

def _numbered_list(items: list[str]) -> str:
    """Format a list as a numbered string, or return a placeholder if empty."""
    if not items:
        return "  (none specified)"
    return "\n".join(f"  {i + 1}. {item}" for i, item in enumerate(items))


def _scene_template_hint(profile: dict, target: int) -> str:
    """
    Extract scene role hints from subject_profile.scene_structure_template.
    Gives the LLM a structural blueprint to follow instead of inventing structure.
    Falls back gracefully if profile is empty (subject_router failed).
    """
    template: list[dict] = profile.get("scene_structure_template", [])
    if not template:
        return ""

    # Use template as-is for 6-scene (intermediate) target.
    # For other counts, take first `target` entries or pad with "continuation".
    entries = template[:target]
    while len(entries) < target:
        entries.append({
            "scene_role": "continuation",
            "content_focus": "further_explanation",
            "suggested_duration_seconds": 45,
        })

    lines = ["Suggested scene structure (follow this order):"]
    for i, entry in enumerate(entries):
        role = entry.get("scene_role", f"scene_{i}")
        focus = entry.get("content_focus", "")
        duration = entry.get("suggested_duration_seconds", 45)
        lines.append(f"  Scene {i}: [{role}] {focus} (~{duration}s)")

    return "\n".join(lines)

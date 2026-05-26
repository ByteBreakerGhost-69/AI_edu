# products/edu_video/backend/layer2_orchestrator/agents/animation_router.py
"""
AnimationRouterAgent: assigns renderer_type to every scene using a
three-tier decision hierarchy — no LLM call, pure deterministic routing.

Called by: node_route_animations (graph.py), last agent in the pipeline
Depends on: scenes (visual_description filled), subject_profile,
            renderer_preference

Cost: $0.00 — no LLM call.

Decision hierarchy per scene (higher tier wins if signal is strong enough):
  Tier 1 — Profile method:   profile.get_renderer_for_content(content_type)
  Tier 2 — Keyword scoring:  scan visual_description for renderer signals
                              (overrides Tier 1 if score >= _KEYWORD_OVERRIDE_MIN)
  Tier 3 — Safety valve:     if chosen renderer not in renderer_preference,
                              fall back to renderer_preference[0]
"""

from collections import Counter

from layer1_input.schemas import SubjectEnum
from layer2_orchestrator.agents.base_agent import BaseAgent
from layer2_orchestrator.agents.subject_profiles import ProfileNotFoundError, get_profile
from layer2_orchestrator.graph import GraphState, SceneData

__all__ = ["AnimationRouterAgent"]

# Minimum keyword hits in visual_description to override the profile default
_KEYWORD_OVERRIDE_MIN: int = 2

# Renderer keyword signals — order within each list does not matter,
# all hits are weighted equally (score += 1 per hit)
RENDERER_KEYWORDS: dict[str, list[str]] = {
    "manim": [
        "equation", "formula", "proof", "derivative", "integral",
        "matrix", "latex", "theorem", "graph of", "plot of",
        "eigenvalue", "determinant", "trigonometric", "differentiate",
        "$$", "\\frac", "\\sum", "\\int",
    ],
    "diagram": [
        "diagram", "flowchart", "circuit", "force", "structure",
        "cycle", "process", "map", "cross-section", "tree",
        "bond", "molecule", "orbital", "reaction arrow", "arrow",
        "node", "edge", "flow", "network",
    ],
    "graph": [
        "supply", "demand", "gdp", "inflation", "axes", "curve",
        "trend", "bar chart", "histogram", "scatter", "equilibrium",
        "x-axis", "y-axis", "data point", "plot", "growth rate",
        "percentage", "population pyramid", "climate graph",
    ],
    "code": [
        "```", "def ", "function", "algorithm", "pseudocode",
        "syntax", "import ", "class ", "for loop", "recursion",
        "variable", "return", "while loop", "if statement",
        "data structure", "binary tree", "linked list",
    ],
    "timeline": [
        "century", "chronology", "timeline", "period", "era",
        "event sequence", "bc", "ad", "decade", "epoch",
        "before", "after", "during", "sequence of events",
        "chronological", "historical period",
    ],
    "flux_sdxl": [
        "illustration", "portrait", "landscape", "scene",
        "organism", "cell", "microscope", "historical image",
        "photograph", "artwork", "depict", "visualize",
        "scientific illustration", "cross section of",
        "detailed drawing", "labeled diagram of",
    ],
    "lottie": [
        "animation", "motion", "transition", "text reveal",
        "particle", "dialogue", "conversation", "fade",
        "slide", "animated text", "kinetic typography",
        "simple animation", "icon animation",
    ],
    "kling": [
        "video", "motion picture", "live action", "documentary style",
        "cinematic", "footage", "film clip",
    ],
}


class AnimationRouterAgent(BaseAgent):
    """
    Assigns renderer_type to every scene in state["scenes"].
    Updates animation_assignments: dict[scene_index, renderer_type].

    Reads from GraphState:
        scenes              — list[SceneData] with visual_description filled
        subject             — used to load subject profile
        renderer_preference — subject's ordered renderer list
        subject_profile     — for get_renderer_for_content()

    Writes to GraphState:
        scenes               — same list with renderer_type filled
        animation_assignments — {scene_index: renderer_type}
        current_node          — "node_route_animations"

    No cost recorded — no LLM call.
    On exception: assigns renderer_preference[0] to all scenes.
    """

    @property
    def agent_name(self) -> str:
        return "animation_router"

    async def run(self, state: GraphState) -> dict:
        job_id = state["job_id"]
        scenes = state.get("scenes", [])
        renderer_preference = state.get("renderer_preference") or ["lottie"]

        log = self.log.bind(
            job_id=job_id,
            subject=state["subject"],
            scene_count=len(scenes),
        )
        log.info("animation_router.started")

        with self._timer() as t:

            # ---------------------------------------------------------- #
            # Guard: nothing to route                                      #
            # ---------------------------------------------------------- #
            if not scenes:
                log.warning("animation_router.no_scenes — returning empty")
                return {
                    "scenes": [],
                    "animation_assignments": {},
                    "current_node": "node_route_animations",
                }

            try:
                profile = _load_profile(state, log)
                primary_renderer = renderer_preference[0]

                routed_scenes: list[SceneData] = []
                animation_assignments: dict[int, str] = {}
                decision_log: list[dict] = []

                for scene in scenes:
                    renderer, tier, score = _decide_renderer(
                        scene=scene,
                        profile=profile,
                        renderer_preference=renderer_preference,
                        primary_renderer=primary_renderer,
                        log=log,
                    )

                    updated_scene = dict(scene)
                    updated_scene["renderer_type"] = renderer
                    routed_scenes.append(updated_scene)  # type: ignore[arg-type]

                    idx = scene["scene_index"]
                    animation_assignments[idx] = renderer
                    decision_log.append({
                        "scene_index": idx,
                        "renderer": renderer,
                        "tier": tier,
                        "keyword_score": score,
                    })

                distribution = dict(Counter(animation_assignments.values()))
                log.info(
                    "animation_router.completed",
                    renderer_distribution=distribution,
                    scenes_routed=len(routed_scenes),
                    duration_ms=t["elapsed_ms"],
                )
                log.debug("animation_router.decision_log", decisions=decision_log)

                return {
                    "scenes": routed_scenes,
                    "animation_assignments": animation_assignments,
                    "current_node": "node_route_animations",
                }

            except Exception as exc:
                log.error(
                    "animation_router.failed",
                    error=str(exc),
                    duration_ms=t["elapsed_ms"],
                )
                fallback_scenes, fallback_assignments = _assign_fallback(
                    scenes, renderer_preference
                )
                return self._safe_return(
                    state,
                    error=str(exc),
                    defaults={
                        "scenes": fallback_scenes,
                        "animation_assignments": fallback_assignments,
                        "current_node": "node_route_animations",
                    },
                )


# --------------------------------------------------------------------------- #
# Core routing logic                                                           #
# --------------------------------------------------------------------------- #

def _decide_renderer(
    scene: SceneData,
    profile,
    renderer_preference: list[str],
    primary_renderer: str,
    log,
) -> tuple[str, str, int]:
    """
    Run the three-tier decision hierarchy for a single scene.

    Returns:
        renderer  — chosen renderer string
        tier      — "profile" | "keyword" | "safety_valve"
                    (which tier made the final decision)
        score     — keyword hit count (0 if profile or safety_valve won)
    """
    content_type = _extract_content_type(scene)
    visual_desc = scene.get("visual_description", "").lower()
    is_placeholder = (scene.get("render_metadata") or {}).get(
        "is_placeholder", False
    )

    # Placeholders get the lightest renderer — no expensive animation
    if is_placeholder:
        chosen = "lottie" if "lottie" in renderer_preference else primary_renderer
        return chosen, "placeholder", 0

    # ---- Tier 1: subject profile ---------------------------------------- #
    if profile is not None:
        tier1_renderer = profile.get_renderer_for_content(content_type)
    else:
        tier1_renderer = primary_renderer

    # ---- Tier 2: keyword scoring ---------------------------------------- #
    scores = _score_keywords(visual_desc)
    best_renderer, best_score = max(scores.items(), key=lambda kv: kv[1])

    if best_score >= _KEYWORD_OVERRIDE_MIN:
        tier2_renderer = best_renderer
        chosen_renderer = tier2_renderer
        chosen_tier = "keyword"
        chosen_score = best_score
    else:
        chosen_renderer = tier1_renderer
        chosen_tier = "profile"
        chosen_score = 0

    # ---- Tier 3: safety valve ------------------------------------------- #
    if chosen_renderer not in renderer_preference:
        log.debug(
            "animation_router.safety_valve_triggered",
            scene_index=scene["scene_index"],
            attempted=chosen_renderer,
            fallback=primary_renderer,
        )
        return primary_renderer, "safety_valve", chosen_score

    return chosen_renderer, chosen_tier, chosen_score


def _score_keywords(visual_desc: str) -> dict[str, int]:
    """
    Score each renderer by counting keyword hits in visual_description.
    Case-insensitive substring match. Returns {renderer: hit_count}.
    """
    scores: dict[str, int] = {renderer: 0 for renderer in RENDERER_KEYWORDS}
    for renderer, keywords in RENDERER_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in visual_desc:
                scores[renderer] += 1
    return scores


# --------------------------------------------------------------------------- #
# Profile loader                                                               #
# --------------------------------------------------------------------------- #

def _load_profile(state: GraphState, log):
    """
    Load subject profile for get_renderer_for_content().
    Returns None on failure — _decide_renderer handles None gracefully
    by using primary_renderer as Tier 1 fallback.
    """
    try:
        subject = SubjectEnum(state["subject"])
        return get_profile(subject)
    except (ProfileNotFoundError, ValueError) as exc:
        log.warning(
            "animation_router.profile_load_failed",
            error=str(exc),
            note="Tier 1 will use primary_renderer as fallback",
        )
        return None


# --------------------------------------------------------------------------- #
# Field extractor                                                              #
# --------------------------------------------------------------------------- #

def _extract_content_type(scene: SceneData) -> str:
    """
    Extract content_type from render_metadata.
    Falls back to "text" if missing or invalid — same fallback
    used by ScriptAgent's _coerce_content_type.
    """
    meta = scene.get("render_metadata") or {}
    content_type = meta.get("content_type", "text")
    if not isinstance(content_type, str) or not content_type.strip():
        return "text"
    return content_type.strip().lower()


# --------------------------------------------------------------------------- #
# Fallback helper                                                              #
# --------------------------------------------------------------------------- #

def _assign_fallback(
    scenes: list[SceneData],
    renderer_preference: list[str],
) -> tuple[list[SceneData], dict[int, str]]:
    """
    Assign renderer_preference[0] to every scene.
    Used in the except block — guarantees all scenes have a renderer
    even if the routing logic crashed entirely.
    Returns (updated_scenes, animation_assignments).
    """
    fallback = renderer_preference[0] if renderer_preference else "lottie"
    updated_scenes: list[SceneData] = []
    assignments: dict[int, str] = {}

    for scene in scenes:
        updated = dict(scene)
        updated["renderer_type"] = fallback
        updated_scenes.append(updated)  # type: ignore[arg-type]
        assignments[scene["scene_index"]] = fallback

    return updated_scenes, assignments

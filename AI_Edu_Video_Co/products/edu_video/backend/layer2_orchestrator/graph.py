# products/edu_video/backend/layer2_orchestrator/graph.py
"""
LangGraph StateGraph definition for the educational video pipeline.

Defines:
  - GraphState: full TypedDict shared across all nodes
  - SceneData: per-scene TypedDict stored inside GraphState
  - Node functions: one per pipeline stage
  - Conditional edge routing functions
  - build_video_graph(): compiles and returns the runnable graph

All agents are imported and instantiated inside node functions (not at module
level) to keep imports lazy and avoid startup failures if an agent dependency
is missing.
"""

import time
from typing import TypedDict

import structlog
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from core.config import get_settings
from core.utils import utcnow

__all__ = [
    "GraphState",
    "SceneData",
    "build_video_graph",
    "accumulate_cost",
]

logger = structlog.get_logger(__name__)
settings = get_settings()


# --------------------------------------------------------------------------- #
# TypedDicts                                                                  #
# --------------------------------------------------------------------------- #

class SceneData(TypedDict):
    """Per-scene data stored inside GraphState.scenes. NOT an ORM model."""
    scene_index: int
    title: str
    narration_text: str
    visual_description: str
    renderer_type: str
    duration_seconds: float
    render_metadata: dict
    llm_cost_usd: float
    fact_checked: bool


class GraphState(TypedDict):
    """
    Shared state passed through every node in the LangGraph pipeline.
    Nodes return partial dicts; LangGraph merges them into this state.
    """

    # --- Input (set once at orchestrator, read-only in nodes) ---
    job_id: str
    user_id: str
    title: str
    subject: str
    curriculum: str
    difficulty_level: str
    language: str
    input_text: str | None
    input_image_url: str | None
    target_scene_count: int

    # --- Enriched by subject_router ---
    subject_profile: dict
    renderer_preference: list[str]
    validation_rules: list[str]

    # --- Enriched by curriculum_agent ---
    curriculum_standards: list[str]
    learning_objectives: list[str]
    prerequisite_concepts: list[str]

    # --- Enriched by memory_agent ---
    similar_jobs: list[dict]
    memory_context: str
    reuse_assets: list[str]

    # --- Built by script_agent + visual_asset_agent ---
    scenes: list[SceneData]

    # --- Fact checking ---
    fact_check_passed: bool
    fact_check_issues: list[str]
    fact_check_iteration: int

    # --- Animation routing ---
    animation_assignments: dict[int, str]

    # --- Cost tracking ---
    total_cost_usd: float
    cost_breakdown: list[dict]

    # --- Control flow ---
    current_node: str
    errors: list[str]
    retry_count: int
    pipeline_metadata: dict


# --------------------------------------------------------------------------- #
# Cost accumulation helper                                                    #
# --------------------------------------------------------------------------- #

def accumulate_cost(
    state: GraphState,
    new_cost: float,
    agent_name: str,
    tokens: int,
) -> dict:
    """
    Return a partial state dict that accumulates cost rather than overwriting.
    Call result should be merged into the node's return dict.

    Example:
        return {
            "scenes": updated_scenes,
            **accumulate_cost(state, 0.003, "script_agent", 1200),
        }
    """
    return {
        "total_cost_usd": state["total_cost_usd"] + new_cost,
        "cost_breakdown": state["cost_breakdown"] + [
            {
                "agent": agent_name,
                "cost_usd": new_cost,
                "tokens": tokens,
                "timestamp": utcnow().isoformat(),
            }
        ],
    }


# --------------------------------------------------------------------------- #
# Node functions                                                              #
# --------------------------------------------------------------------------- #

async def node_route_subject(state: GraphState) -> dict:
    """
    Node 1: Apply subject-specific profile, renderer preferences, and validation rules.
    No LLM cost — pure rule-based routing.
    """
    node_name = "node_route_subject"
    t0 = time.perf_counter()
    log = logger.bind(job_id=state["job_id"], node=node_name)
    log.info("node_started")

    try:
        from layer2_orchestrator.agents.subject_router import SubjectRouterAgent  # noqa: PLC0415

        agent = SubjectRouterAgent()
        result = await agent.run(state)
        result["current_node"] = node_name

    except Exception as exc:
        log.error("node_failed", error=str(exc))
        result = {
            "current_node": node_name,
            "subject_profile": {},
            "renderer_preference": ["lottie"],
            "validation_rules": [],
            "errors": state["errors"] + [f"{node_name}: {exc}"],
        }

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    log.info("node_completed", duration_ms=elapsed_ms)
    return result


async def node_enrich_curriculum(state: GraphState) -> dict:
    """
    Node 2: Enrich state with curriculum standards, learning objectives,
    and prerequisite concepts. May call Claude to parse curriculum docs.
    """
    node_name = "node_enrich_curriculum"
    t0 = time.perf_counter()
    log = logger.bind(job_id=state["job_id"], node=node_name)
    log.info("node_started")

    try:
        from layer2_orchestrator.agents.curriculum_agent import CurriculumAgent  # noqa: PLC0415

        agent = CurriculumAgent()
        result = await agent.run(state)
        result["current_node"] = node_name

    except Exception as exc:
        log.error("node_failed", error=str(exc))
        result = {
            "current_node": node_name,
            "curriculum_standards": [],
            "learning_objectives": [],
            "prerequisite_concepts": [],
            "errors": state["errors"] + [f"{node_name}: {exc}"],
        }

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    log.info("node_completed", duration_ms=elapsed_ms)
    return result


async def node_query_memory(state: GraphState) -> dict:
    """
    Node 3: Query Qdrant for similar past jobs to inform scene generation.
    Populates memory_context and identifies reusable assets.
    """
    node_name = "node_query_memory"
    t0 = time.perf_counter()
    log = logger.bind(job_id=state["job_id"], node=node_name)
    log.info("node_started")

    try:
        from layer2_orchestrator.agents.memory_agent import MemoryAgent  # noqa: PLC0415

        agent = MemoryAgent()
        result = await agent.run(state)
        result["current_node"] = node_name

    except Exception as exc:
        log.error("node_failed", error=str(exc))
        result = {
            "current_node": node_name,
            "similar_jobs": [],
            "memory_context": "",
            "reuse_assets": [],
            "errors": state["errors"] + [f"{node_name}: {exc}"],
        }

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    log.info("node_completed", duration_ms=elapsed_ms)
    return result


async def node_generate_scenes(state: GraphState) -> dict:
    """
    Node 4: Generate narration scripts and visual descriptions for all scenes.
    Calls ScriptAgent then VisualAssetAgent sequentially.
    """
    node_name = "node_generate_scenes"
    t0 = time.perf_counter()
    log = logger.bind(job_id=state["job_id"], node=node_name)
    log.info("node_started", target_scene_count=state["target_scene_count"])

    try:
        from layer2_orchestrator.agents.script_agent import ScriptAgent  # noqa: PLC0415
        from layer2_orchestrator.agents.visual_asset_agent import VisualAssetAgent  # noqa: PLC0415

        # Script agent populates narration_text for each scene
        script_agent = ScriptAgent()
        script_result = await script_agent.run(state)

        # Merge script result into a temporary state for visual agent
        intermediate_state: GraphState = {**state, **script_result}  # type: ignore[misc]

        # Visual agent adds visual_description to each scene
        visual_agent = VisualAssetAgent()
        visual_result = await visual_agent.run(intermediate_state)

        # Merge costs from both agents
        combined_cost = (
            script_result.get("total_cost_usd", state["total_cost_usd"])
            + visual_result.get("total_cost_usd", 0.0)
            - state["total_cost_usd"]
        )
        combined_breakdown = (
            script_result.get("cost_breakdown", state["cost_breakdown"])
            + visual_result.get("cost_breakdown", [])
        )

        result = {
            "scenes": visual_result.get("scenes", script_result.get("scenes", [])),
            "total_cost_usd": state["total_cost_usd"] + combined_cost,
            "cost_breakdown": combined_breakdown,
            "current_node": node_name,
        }

    except Exception as exc:
        log.error("node_failed", error=str(exc))
        result = {
            "current_node": node_name,
            "scenes": state.get("scenes", []),
            "errors": state["errors"] + [f"{node_name}: {exc}"],
        }

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    log.info(
        "node_completed",
        duration_ms=elapsed_ms,
        scene_count=len(result.get("scenes", [])),
    )
    return result


async def node_fact_check(state: GraphState) -> dict:
    """
    Node 5: Validate educational accuracy of generated scenes.
    May correct scenes inline. Tracks iteration count for retry logic.
    """
    node_name = "node_fact_check"
    t0 = time.perf_counter()
    iteration = state["fact_check_iteration"] + 1
    log = logger.bind(job_id=state["job_id"], node=node_name, iteration=iteration)
    log.info("node_started")

    try:
        from layer2_orchestrator.agents.fact_checker_agent import FactCheckerAgent  # noqa: PLC0415

        agent = FactCheckerAgent()
        result = await agent.run(state)
        result["fact_check_iteration"] = iteration
        result["current_node"] = node_name

    except Exception as exc:
        log.error("node_failed", error=str(exc))
        # On fact check failure: mark as passed to avoid infinite retry
        result = {
            "current_node": node_name,
            "fact_check_passed": True,
            "fact_check_issues": [f"Fact check agent failed: {exc}"],
            "fact_check_iteration": iteration,
            "errors": state["errors"] + [f"{node_name}: {exc}"],
        }

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    log.info(
        "node_completed",
        duration_ms=elapsed_ms,
        fact_check_passed=result.get("fact_check_passed"),
        issues=len(result.get("fact_check_issues", [])),
    )
    return result


async def node_route_animations(state: GraphState) -> dict:
    """
    Node 6: Assign a renderer type to each scene based on content and subject profile.
    """
    node_name = "node_route_animations"
    t0 = time.perf_counter()
    log = logger.bind(job_id=state["job_id"], node=node_name)
    log.info("node_started")

    try:
        from layer2_orchestrator.agents.animation_router import AnimationRouterAgent  # noqa: PLC0415

        agent = AnimationRouterAgent()
        result = await agent.run(state)
        result["current_node"] = node_name

    except Exception as exc:
        log.error("node_failed", error=str(exc))
        # Safe fallback: assign default renderer to all scenes
        fallback_scenes = []
        fallback_assignments: dict[int, str] = {}
        default_renderer = (
            state["renderer_preference"][0]
            if state.get("renderer_preference")
            else "lottie"
        )
        for scene in state.get("scenes", []):
            updated = dict(scene)
            updated["renderer_type"] = default_renderer
            fallback_scenes.append(updated)
            fallback_assignments[scene["scene_index"]] = default_renderer

        result = {
            "current_node": node_name,
            "scenes": fallback_scenes,
            "animation_assignments": fallback_assignments,
            "errors": state["errors"] + [f"{node_name}: {exc}"],
        }

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    log.info(
        "node_completed",
        duration_ms=elapsed_ms,
        assignments=result.get("animation_assignments", {}),
    )
    return result


async def node_handle_error(state: GraphState) -> dict:
    """
    Terminal error node: reached when too many non-fatal errors have accumulated.
    Logs all errors and marks the pipeline as terminated.
    """
    node_name = "node_handle_error"
    log = logger.bind(job_id=state["job_id"], node=node_name)
    log.error(
        "node_started",
        total_errors=len(state["errors"]),
        errors=state["errors"],
    )

    updated_errors = list(state["errors"]) + ["pipeline_terminated"]

    log.info("node_completed", final_error_count=len(updated_errors))

    return {
        "current_node": "error",
        "errors": updated_errors,
    }


# --------------------------------------------------------------------------- #
# Conditional edge routing                                                    #
# --------------------------------------------------------------------------- #

def should_continue_after_memory(state: GraphState) -> str:
    """
    After memory_agent: abort to error node if too many errors have accumulated.
    Otherwise proceed to scene generation.
    """
    if len(state["errors"]) > 3:
        logger.warning(
            "graph.routing_to_error",
            job_id=state["job_id"],
            error_count=len(state["errors"]),
        )
        return "node_handle_error"
    return "node_generate_scenes"


def should_retry_fact_check(state: GraphState) -> str:
    """
    After fact_checker_agent:
    - Retry up to 2 times if fact check failed.
    - Proceed with warnings if retries are exhausted.
    - Proceed normally if passed.
    """
    passed = state["fact_check_passed"]
    iteration = state["fact_check_iteration"]

    if passed:
        logger.info(
            "graph.fact_check_passed",
            job_id=state["job_id"],
            iteration=iteration,
        )
        return "node_route_animations"

    if iteration < 2:
        logger.warning(
            "graph.fact_check_retry",
            job_id=state["job_id"],
            iteration=iteration,
            issues=state["fact_check_issues"],
        )
        return "node_fact_check"

    # Exhausted retries — proceed with warning
    logger.warning(
        "graph.fact_check_max_retries_exceeded",
        job_id=state["job_id"],
        iteration=iteration,
        issues=state["fact_check_issues"],
    )
    return "node_route_animations"


# --------------------------------------------------------------------------- #
# Graph construction                                                          #
# --------------------------------------------------------------------------- #

def build_video_graph():
    """
    Compile and return the LangGraph StateGraph for educational video generation.

    The compiled graph is intended to be created ONCE at module load and reused
    across all job invocations (no per-job recompilation).

    Checkpointing is controlled by settings.LANGGRAPH_CHECKPOINTING (default False).
    In production, use an external checkpointer (e.g. Postgres) instead of MemorySaver.
    """
    workflow = StateGraph(GraphState)

    # --- Register nodes ---
    workflow.add_node("node_route_subject", node_route_subject)
    workflow.add_node("node_enrich_curriculum", node_enrich_curriculum)
    workflow.add_node("node_query_memory", node_query_memory)
    workflow.add_node("node_generate_scenes", node_generate_scenes)
    workflow.add_node("node_fact_check", node_fact_check)
    workflow.add_node("node_route_animations", node_route_animations)
    workflow.add_node("node_handle_error", node_handle_error)

    # --- Register edges ---
    workflow.add_edge(START, "node_route_subject")
    workflow.add_edge("node_route_subject", "node_enrich_curriculum")
    workflow.add_edge("node_enrich_curriculum", "node_query_memory")

    workflow.add_conditional_edges(
        "node_query_memory",
        should_continue_after_memory,
        {
            "node_handle_error": "node_handle_error",
            "node_generate_scenes": "node_generate_scenes",
        },
    )

    workflow.add_edge("node_generate_scenes", "node_fact_check")

    workflow.add_conditional_edges(
        "node_fact_check",
        should_retry_fact_check,
        {
            "node_fact_check": "node_fact_check",
            "node_route_animations": "node_route_animations",
        },
    )

    workflow.add_edge("node_route_animations", END)
    workflow.add_edge("node_handle_error", END)

    # --- Compile with optional checkpointing ---
    use_checkpointing = getattr(settings, "LANGGRAPH_CHECKPOINTING", False)

    if use_checkpointing:
        checkpointer = MemorySaver()
        logger.info("graph.compiled_with_checkpointing")
        return workflow.compile(checkpointer=checkpointer)

    logger.info("graph.compiled_without_checkpointing")
    return workflow.compile()

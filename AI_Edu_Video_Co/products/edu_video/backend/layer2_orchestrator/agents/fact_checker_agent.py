# products/edu_video/backend/layer2_orchestrator/agents/fact_checker_agent.py
"""
FactCheckerAgent: validates educational accuracy of all scenes,
applies inline corrections, and tracks iteration count for retry logic.

Called by: node_fact_check (graph.py)
Retry logic: graph.py calls this up to 2 times if fact_check_passed=False
             (controlled by should_retry_fact_check conditional edge)
Depends on: scenes (narration_text filled), subject_profile, curriculum_standards

Cost: ~1800 tokens ≈ $0.0051 per invocation (Claude claude-sonnet-4-5)
      Called up to 2 times → max $0.0102 for fact checking per job.

Failure policy:
  On any exception → fact_check_passed=True (fail open).
  Rationale: an infinite retry loop caused by a broken fact checker is worse
  than publishing a video that may have minor inaccuracies and goes to
  human review anyway (layer6_delivery/review/).
"""

import json

from layer2_orchestrator.agents.base_agent import BaseAgent
from layer2_orchestrator.graph import GraphState, SceneData

__all__ = ["FactCheckerAgent"]

# Token estimates
_EST_PROMPT_TOKENS: int = 1200
_EST_COMPLETION_TOKENS_PER_SCENE: int = 100  # issue description + corrected narration

# Minimum confidence below which a "passed" result is still flagged
# in errors so orchestrator can route to human review
_LOW_CONFIDENCE_THRESHOLD: float = 0.70

# Valid error_type values from LLM — anything else is coerced to "unknown"
_VALID_ERROR_TYPES = frozenset({
    "factual_error",
    "outdated_info",
    "curriculum_mismatch",
    "terminology",
    "unknown",
})

# Hard cap on corrected_narration length — prevents LLM from returning
# an entire essay as a "correction"
_MAX_CORRECTED_NARRATION_CHARS: int = 800


class FactCheckerAgent(BaseAgent):
    """
    Reviews all scene narrations for factual accuracy against curriculum
    standards. Applies corrections directly to scene narration_text when
    issues are found. Marks all scenes fact_checked=True on pass.

    Reads from GraphState:
        scenes, subject, curriculum, difficulty_level,
        subject_profile (fact_check_prompt_fragment),
        curriculum_standards, fact_check_iteration

    Writes to GraphState:
        scenes                — narration_text corrected where issues found,
                                fact_checked=True for all scenes on pass
        fact_check_passed     — bool
        fact_check_issues     — list[str] human-readable issue summaries
        fact_check_iteration  — incremented by 1
        total_cost_usd        — accumulated via _record_cost
        cost_breakdown        — accumulated via _record_cost
        current_node          — "node_fact_check"
    """

    @property
    def agent_name(self) -> str:
        return "fact_checker_agent"

    async def run(self, state: GraphState) -> dict:
        job_id = state["job_id"]
        iteration = state["fact_check_iteration"]
        scenes = state.get("scenes", [])

        log = self.log.bind(
            job_id=job_id,
            subject=state["subject"],
            curriculum=state["curriculum"],
            iteration=iteration,
            scene_count=len(scenes),
        )
        log.info("fact_checker_agent.started")

        with self._timer() as t:

            # ---------------------------------------------------------- #
            # Guard: nothing to check                                      #
            # ---------------------------------------------------------- #
            if not scenes:
                log.warning("fact_checker_agent.no_scenes — marking passed")
                return _fail_open(state, iteration, reason="no_scenes_to_check")

            try:
                # Filter out placeholder scenes — no narration to validate
                checkable, placeholders = _split_scenes(scenes)

                if not checkable:
                    log.warning(
                        "fact_checker_agent.only_placeholders — marking passed"
                    )
                    return _fail_open(
                        state, iteration, reason="only_placeholder_scenes"
                    )

                system_prompt = _build_system_prompt(state)
                user_prompt = _build_user_prompt(checkable, state)

                raw = await self._call_llm_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    job_id=job_id,
                    expected_keys=[
                        "fact_check_passed",
                        "issues",
                        "overall_confidence",
                    ],
                )

                passed, issues, confidence = _parse_response(raw, log)

                # -------------------------------------------------- #
                # Apply corrections to checkable scenes               #
                # -------------------------------------------------- #
                corrected_scenes, fact_check_issues = _apply_corrections(
                    checkable, issues, log
                )

                # -------------------------------------------------- #
                # Mark fact_checked on all scenes                     #
                # -------------------------------------------------- #
                if passed:
                    corrected_scenes = _mark_all_fact_checked(corrected_scenes)

                # Recombine corrected checkable scenes with placeholders,
                # preserving original scene_index order
                final_scenes = _recombine_scenes(corrected_scenes, placeholders)

                # -------------------------------------------------- #
                # Low confidence warning                              #
                # -------------------------------------------------- #
                if passed and confidence < _LOW_CONFIDENCE_THRESHOLD:
                    warning = (
                        f"fact_checker passed but with low confidence "
                        f"({confidence:.2f} < {_LOW_CONFIDENCE_THRESHOLD}). "
                        "Recommend human review."
                    )
                    log.warning("fact_checker_agent.low_confidence", confidence=confidence)
                    fact_check_issues.append(warning)

                completion_tokens = _EST_COMPLETION_TOKENS_PER_SCENE * len(checkable)
                total_tokens = _EST_PROMPT_TOKENS + completion_tokens
                cost_usd = self._estimate_cost(_EST_PROMPT_TOKENS, completion_tokens)

                log.info(
                    "fact_checker_agent.completed",
                    passed=passed,
                    issues_found=len(issues),
                    confidence=confidence,
                    scenes_corrected=sum(
                        1 for s in corrected_scenes if s.get("fact_checked")
                    ),
                    total_tokens=total_tokens,
                    cost_usd=cost_usd,
                    duration_ms=t["elapsed_ms"],
                )

                return {
                    "fact_check_passed": passed,
                    "fact_check_issues": fact_check_issues,
                    "fact_check_iteration": iteration + 1,
                    "scenes": final_scenes,
                    "current_node": "node_fact_check",
                    **self._record_cost(job_id, total_tokens, cost_usd, state),
                }

            except Exception as exc:
                log.error(
                    "fact_checker_agent.failed",
                    error=str(exc),
                    duration_ms=t["elapsed_ms"],
                )
                # Fail open: assume passed to prevent infinite retry loop.
                # The error is recorded in both fact_check_issues and state["errors"]
                # so the orchestrator and human review queue can see it.
                return {
                    **_fail_open(state, iteration, reason=str(exc)),
                    "errors": state["errors"] + [f"fact_checker_agent: {exc}"],
                }


# --------------------------------------------------------------------------- #
# Prompt builders                                                              #
# --------------------------------------------------------------------------- #

def _build_system_prompt(state: GraphState) -> str:
    """
    Build system prompt. Injects subject-specific validation rules
    from the profile so the LLM knows what domain errors to look for.
    """
    profile = state.get("subject_profile", {})
    fact_check_fragment = profile.get("fact_check_prompt_fragment", "")
    validation_rules = state.get("validation_rules", [])

    rules_block = (
        "\n".join(f"  - {r}" for r in validation_rules)
        if validation_rules
        else "  (use general educational accuracy standards)"
    )

    iteration = state["fact_check_iteration"]
    iteration_hint = (
        ""
        if iteration == 0
        else (
            f"\n⚠️  This is retry attempt {iteration + 1}. "
            "Previous check found issues. Be thorough — focus especially on "
            "any content that was recently corrected."
        )
    )

    return (
        f"You are an expert educational fact-checker specializing in "
        f"{state['subject']} at {state['difficulty_level']} level.\n"
        f"Curriculum framework: {state['curriculum']}\n"
        f"{iteration_hint}\n\n"

        "=== SUBJECT-SPECIFIC VALIDATION RULES ===\n"
        f"{fact_check_fragment}\n\n"

        "=== ACTIVE VALIDATION RULE IDs ===\n"
        f"{rules_block}\n\n"

        "=== REVIEW STANDARD ===\n"
        "Be STRICT on factual errors:\n"
        "  - Wrong formulas, constants, or numerical values\n"
        "  - Incorrect dates, names, or attributions\n"
        "  - Unbalanced chemical equations\n"
        "  - Violated physical laws or conservation principles\n"
        "  - Outdated scientific consensus (post-2015 revisions)\n"
        "  - Wrong taxonomy, nomenclature, or classification\n"
        "  - Incorrect algorithm behavior or complexity claims\n\n"
        "Be LENIENT on pedagogical choices:\n"
        "  - Simplified analogies appropriate for the difficulty level\n"
        "  - Word order or narrative style\n"
        "  - Choice of examples (unless the example itself contains an error)\n"
        "  - Deliberate omissions of advanced edge cases at beginner level\n\n"

        "=== CORRECTION STANDARD ===\n"
        "When writing corrected_narration:\n"
        "  - Preserve the original tone and difficulty level\n"
        "  - Fix ONLY the factual error — do not rewrite the entire scene\n"
        "  - Keep the corrected narration within 60-120 words\n\n"

        "=== OUTPUT FORMAT ===\n"
        "Return a single JSON object. No markdown. No prose outside JSON."
    )


def _build_user_prompt(
    checkable_scenes: list[SceneData],
    state: GraphState,
) -> str:
    """
    Build user prompt with scenes to check and standards to check against.
    Only includes checkable (non-placeholder) scenes.
    """
    scenes_payload = [
        {
            "scene_index": s["scene_index"],
            "title": s["title"],
            "narration_text": s["narration_text"],
        }
        for s in checkable_scenes
    ]

    standards = state.get("curriculum_standards", [])
    standards_block = (
        "\n".join(f"  - {s}" for s in standards)
        if standards
        else "  (no specific standards provided — use subject knowledge)"
    )

    return (
        f"Check these {len(checkable_scenes)} scene(s) against "
        f"{state['curriculum']} {state['subject']} standards "
        f"at {state['difficulty_level']} level:\n\n"
        f"{json.dumps(scenes_payload, indent=2)}\n\n"
        f"Curriculum standards to verify against:\n{standards_block}\n\n"
        "Return JSON:\n"
        "{\n"
        '  "fact_check_passed": true,\n'
        '  "issues": [\n'
        "    {\n"
        '      "scene_index": 0,\n'
        '      "error_type": "factual_error|outdated_info|curriculum_mismatch|terminology",\n'
        '      "description": "Precise description of what is wrong and why",\n'
        '      "corrected_narration": "Complete corrected narration (60-120 words)"\n'
        "    }\n"
        "  ],\n"
        '  "overall_confidence": 0.95\n'
        "}\n\n"
        'Set "fact_check_passed": false if ANY issue is found. '
        'Return an empty "issues" list if everything is correct.'
    )


# --------------------------------------------------------------------------- #
# Response parser                                                              #
# --------------------------------------------------------------------------- #

def _parse_response(
    raw: dict,
    log,
) -> tuple[bool, list[dict], float]:
    """
    Extract and validate the three top-level fields from LLM response.

    Returns:
        passed      — bool (True if no issues found)
        issues      — list of validated issue dicts
        confidence  — float 0.0–1.0
    """
    # fact_check_passed
    raw_passed = raw.get("fact_check_passed")
    if raw_passed is None:
        # LLM failed entirely — treat as passed to avoid retry loop
        log.warning("fact_checker.missing_fact_check_passed — defaulting to True")
        passed = True
    else:
        passed = bool(raw_passed)

    # issues
    raw_issues = raw.get("issues")
    issues = _parse_issues(raw_issues, log)

    # Reconcile: if issues exist, passed must be False
    if issues and passed:
        log.warning(
            "fact_checker.passed_true_but_issues_found — overriding to False",
            issue_count=len(issues),
        )
        passed = False

    # confidence
    try:
        confidence = float(raw.get("overall_confidence", 1.0))
        confidence = max(0.0, min(1.0, confidence))  # clamp to [0.0, 1.0]
    except (TypeError, ValueError):
        confidence = 1.0

    return passed, issues, confidence


def _parse_issues(raw_issues, log) -> list[dict]:
    """
    Validate and sanitize the issues list from LLM response.
    Each issue must have scene_index, error_type, description,
    and corrected_narration. Missing or invalid entries are dropped.
    """
    if not raw_issues:
        return []

    if not isinstance(raw_issues, list):
        log.warning(
            "fact_checker.issues_not_a_list",
            type_received=type(raw_issues).__name__,
        )
        return []

    valid_issues = []
    for i, issue in enumerate(raw_issues):
        if not isinstance(issue, dict):
            continue

        # scene_index
        try:
            scene_index = int(issue["scene_index"])
        except (KeyError, TypeError, ValueError):
            log.warning("fact_checker.issue_missing_scene_index", position=i)
            continue

        # error_type
        raw_error_type = str(issue.get("error_type", "unknown")).strip().lower()
        error_type = (
            raw_error_type
            if raw_error_type in _VALID_ERROR_TYPES
            else "unknown"
        )

        # description
        description = str(issue.get("description", "")).strip()
        if not description:
            log.warning(
                "fact_checker.issue_missing_description",
                scene_index=scene_index,
            )
            continue

        # corrected_narration
        corrected = str(issue.get("corrected_narration", "")).strip()
        if len(corrected) > _MAX_CORRECTED_NARRATION_CHARS:
            log.warning(
                "fact_checker.corrected_narration_truncated",
                scene_index=scene_index,
                original_chars=len(corrected),
            )
            corrected = corrected[:_MAX_CORRECTED_NARRATION_CHARS]

        valid_issues.append({
            "scene_index": scene_index,
            "error_type": error_type,
            "description": description,
            "corrected_narration": corrected,
        })

    return valid_issues


# --------------------------------------------------------------------------- #
# Scene mutation helpers                                                       #
# --------------------------------------------------------------------------- #

def _apply_corrections(
    scenes: list[SceneData],
    issues: list[dict],
    log,
) -> tuple[list[SceneData], list[str]]:
    """
    Apply LLM corrections to matching scenes by scene_index.
    Returns updated scene list and human-readable issue summaries.

    Scenes are copied — input list is not mutated.
    Issues with no matching scene_index are logged and skipped.
    """
    # Index scenes for O(1) lookup
    scenes_by_index: dict[int, dict] = {
        s["scene_index"]: dict(s) for s in scenes
    }

    fact_check_issues: list[str] = []

    for issue in issues:
        idx = issue["scene_index"]

        if idx not in scenes_by_index:
            log.warning(
                "fact_checker.issue_references_unknown_scene",
                scene_index=idx,
            )
            continue

        scene = scenes_by_index[idx]
        corrected = issue["corrected_narration"]

        if corrected:
            scene["narration_text"] = corrected
            scene["fact_checked"] = True
            log.info(
                "fact_checker.correction_applied",
                scene_index=idx,
                error_type=issue["error_type"],
            )

        fact_check_issues.append(
            f"Scene {idx} [{issue['error_type']}]: {issue['description']}"
        )

    # Preserve original scene order
    corrected_scenes: list[SceneData] = [
        scenes_by_index[s["scene_index"]]  # type: ignore[misc]
        for s in scenes
        if s["scene_index"] in scenes_by_index
    ]

    return corrected_scenes, fact_check_issues


def _mark_all_fact_checked(scenes: list[SceneData]) -> list[SceneData]:
    """
    Set fact_checked=True on all scenes when the check passes.
    Returns new list — does not mutate input.
    """
    return [
        {**dict(s), "fact_checked": True}  # type: ignore[misc]
        for s in scenes
    ]


def _split_scenes(
    scenes: list[SceneData],
) -> tuple[list[SceneData], list[SceneData]]:
    """
    Separate scenes into checkable and placeholder.
    Placeholders are identified by render_metadata.is_placeholder=True.
    Returns (checkable, placeholders).
    """
    checkable = []
    placeholders = []
    for scene in scenes:
        meta = scene.get("render_metadata") or {}
        if meta.get("is_placeholder", False):
            placeholders.append(scene)
        else:
            checkable.append(scene)
    return checkable, placeholders


def _recombine_scenes(
    corrected: list[SceneData],
    placeholders: list[SceneData],
) -> list[SceneData]:
    """
    Merge corrected scenes and placeholder scenes back into a single list
    sorted by scene_index. Preserves original pipeline scene order.
    """
    combined = list(corrected) + list(placeholders)
    return sorted(combined, key=lambda s: s["scene_index"])


# --------------------------------------------------------------------------- #
# Fail-open helper                                                             #
# --------------------------------------------------------------------------- #

def _fail_open(
    state: GraphState,
    iteration: int,
    reason: str,
) -> dict:
    """
    Return a safe 'passed' result used in all fail-open paths.
    Records the reason in fact_check_issues so human review queue
    can see why fact checking was skipped.

    Does NOT include "errors" key — caller appends that if needed.
    """
    return {
        "fact_check_passed": True,
        "fact_check_issues": [f"fact_check_skipped: {reason}"],
        "fact_check_iteration": iteration + 1,
        "scenes": state.get("scenes", []),
        "current_node": "node_fact_check",
}

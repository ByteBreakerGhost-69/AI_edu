# products/edu_video/backend/layer2_orchestrator/agents/curriculum_agent.py
"""
CurriculumAgent: enriches GraphState with curriculum standards,
learning objectives, and prerequisite concepts via a single LLM call.

Called by: node_enrich_curriculum (graph.py)
Depends on: subject_profile already set by SubjectRouterAgent
Cost: ~700 tokens ≈ $0.0033 per invocation (Claude claude-sonnet-4-5)
"""

import json

from layer1_input.schemas import CurriculumEnum, DifficultyEnum, SubjectEnum
from layer2_orchestrator.agents.base_agent import BaseAgent
from layer2_orchestrator.graph import GraphState

__all__ = ["CurriculumAgent"]

# Token estimates for cost calculation
# Actual usage varies by input length — these are conservative midpoints
_EST_PROMPT_TOKENS: int = 400
_EST_COMPLETION_TOKENS: int = 300

# Hard cap on input_text passed to LLM — enough context without
# blowing up the prompt for long user inputs
_INPUT_TEXT_PREVIEW_CHARS: int = 500

# Minimum acceptable counts — if LLM returns fewer, we log a warning
# but still proceed (better than blocking the pipeline)
_MIN_STANDARDS: int = 1
_MIN_OBJECTIVES: int = 1
_MIN_PREREQUISITES: int = 0  # genuinely optional for beginner content


class CurriculumAgent(BaseAgent):
    """
    Queries Claude to identify the most relevant curriculum standards,
    measurable learning objectives, and prerequisite concepts for a job.

    Reads from GraphState:
        subject, curriculum, difficulty_level, input_text, title

    Writes to GraphState:
        curriculum_standards   — list[str]: 3-5 standard codes/descriptions
        learning_objectives    — list[str]: 3-5 measurable objectives
        prerequisite_concepts  — list[str]: 2-4 concepts student must know first
        total_cost_usd         — accumulated (via _record_cost)
        cost_breakdown         — accumulated (via _record_cost)
        current_node           — "node_enrich_curriculum"
    """

    @property
    def agent_name(self) -> str:
        return "curriculum_agent"

    async def run(self, state: GraphState) -> dict:
        job_id = state["job_id"]
        log = self.log.bind(
            job_id=job_id,
            subject=state["subject"],
            curriculum=state["curriculum"],
            difficulty=state["difficulty_level"],
        )
        log.info("curriculum_agent.started")

        with self._timer() as t:
            try:
                system_prompt = _build_system_prompt()
                user_prompt = _build_user_prompt(state)

                raw = await self._call_llm_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    job_id=job_id,
                    expected_keys=[
                        "curriculum_standards",
                        "learning_objectives",
                        "prerequisite_concepts",
                    ],
                )

                standards, objectives, prerequisites = _parse_and_validate(
                    raw, state, log
                )

                tokens = _EST_PROMPT_TOKENS + _EST_COMPLETION_TOKENS
                cost_usd = self._estimate_cost(
                    _EST_PROMPT_TOKENS, _EST_COMPLETION_TOKENS
                )

                log.info(
                    "curriculum_agent.completed",
                    standards_count=len(standards),
                    objectives_count=len(objectives),
                    prerequisites_count=len(prerequisites),
                    cost_usd=cost_usd,
                    duration_ms=t["elapsed_ms"],
                )

                return {
                    "curriculum_standards": standards,
                    "learning_objectives": objectives,
                    "prerequisite_concepts": prerequisites,
                    "current_node": "node_enrich_curriculum",
                    **self._record_cost(job_id, tokens, cost_usd, state),
                }

            except Exception as exc:
                log.error(
                    "curriculum_agent.failed",
                    error=str(exc),
                    duration_ms=t["elapsed_ms"],
                )
                return self._safe_return(
                    state,
                    error=str(exc),
                    defaults={
                        "curriculum_standards": [],
                        "learning_objectives": [],
                        "prerequisite_concepts": [],
                        "current_node": "node_enrich_curriculum",
                    },
                )


# --------------------------------------------------------------------------- #
# Prompt builders — pure functions, easy to unit test independently           #
# --------------------------------------------------------------------------- #

def _build_system_prompt() -> str:
    return (
        "You are an expert educational curriculum specialist with deep knowledge of "
        "the IB (International Baccalaureate), Cambridge (IGCSE and A-Level), "
        "and AP (Advanced Placement) frameworks, as well as general international "
        "educational standards.\n\n"
        "Given a subject, curriculum, difficulty level, and topic, you identify:\n"
        "1. The most relevant curriculum standard codes or descriptions\n"
        "2. Measurable learning objectives (start each with an action verb: "
        "Explain, Calculate, Analyze, Compare, Apply, etc.)\n"
        "3. Prerequisite concepts the student must already understand\n\n"
        "Be specific — generic objectives like 'understand mathematics' are not acceptable. "
        "Reference actual syllabus section numbers or standard codes where they exist."
    )


def _build_user_prompt(state: GraphState) -> str:
    # Determine what content context to provide
    if state["input_text"]:
        content_context = (
            f"Topic input (first {_INPUT_TEXT_PREVIEW_CHARS} chars):\n"
            f"{state['input_text'][:_INPUT_TEXT_PREVIEW_CHARS]}"
        )
    else:
        content_context = (
            f"Topic title: {state['title']}\n"
            "(Input was image-based — use title and subject as content basis)"
        )

    # Build curriculum-specific instruction
    curriculum_instruction = _curriculum_specific_instruction(
        state["curriculum"], state["subject"]
    )

    return (
        f"Subject: {state['subject']}\n"
        f"Curriculum: {state['curriculum']}\n"
        f"Difficulty level: {state['difficulty_level']}\n"
        f"Video title: {state['title']}\n"
        f"{content_context}\n\n"
        f"{curriculum_instruction}\n\n"
        "Return a JSON object with exactly these keys:\n"
        "{\n"
        '  "curriculum_standards": [\n'
        '    "3 to 5 specific standard codes or descriptions"\n'
        '  ],\n'
        '  "learning_objectives": [\n'
        '    "3 to 5 measurable objectives, each starting with an action verb"\n'
        '  ],\n'
        '  "prerequisite_concepts": [\n'
        '    "2 to 4 concepts the student must already know"\n'
        '  ]\n'
        "}"
    )


def _curriculum_specific_instruction(curriculum: str, subject: str) -> str:
    """
    Return a curriculum-specific instruction fragment so the LLM produces
    standard codes in the right format for each framework.
    """
    instructions = {
        "IB": (
            "Use IB syllabus notation. "
            "For sciences: reference Topic numbers (e.g., 'IB Biology HL Topic 6.1 — Digestion'). "
            "For mathematics: reference the Analysis & Approaches or Applications & Interpretation "
            "syllabus sections (e.g., 'IB Math AA HL 5.9 — Maclaurin series'). "
            "Include whether content is SL-only, HL-only, or both where relevant."
        ),
        "Cambridge": (
            "Use Cambridge syllabus notation. "
            "Reference the syllabus code and section "
            "(e.g., 'Cambridge A-Level Chemistry 9701 — Section 4.1 Ionic equilibria', "
            "'Cambridge IGCSE Physics 0625 — Section 3: Waves'). "
            "Specify whether content is Core or Supplement for IGCSE, "
            "or AS/A2 for A-Level."
        ),
        "AP": (
            "Use AP framework notation. "
            "Reference Big Ideas and Learning Objectives "
            "(e.g., 'AP Biology — EVO-1.C: Describe the connection between evolution "
            "and population genetics'). "
            "For STEM subjects reference the relevant AP equation sheet or formula "
            "where applicable."
        ),
        "general": (
            "Use clear, descriptive standard statements since no specific "
            "curriculum framework is required. "
            "Reference widely accepted educational standards "
            "(e.g., 'Common Core Math: HSF.IF.C.7 — Graph functions', "
            "or 'Standard: Student can balance chemical equations'). "
            "Prioritize practical, measurable outcomes."
        ),
    }
    return instructions.get(curriculum, instructions["general"])


# --------------------------------------------------------------------------- #
# Response parser                                                              #
# --------------------------------------------------------------------------- #

def _parse_and_validate(
    raw: dict,
    state: GraphState,
    log,
) -> tuple[list[str], list[str], list[str]]:
    """
    Extract and validate the three lists from the LLM response dict.

    Rules:
    - Each field must be a list of strings.
    - Non-string items are coerced to str or dropped.
    - If the LLM returned None (all-retries-failed sentinel), use empty list.
    - Log a warning if counts fall below minimums, but never block.

    Returns:
        (curriculum_standards, learning_objectives, prerequisite_concepts)
    """
    standards = _extract_string_list(raw, "curriculum_standards")
    objectives = _extract_string_list(raw, "learning_objectives")
    prerequisites = _extract_string_list(raw, "prerequisite_concepts")

    # Warn on suspiciously low counts — not an error, pipeline continues
    if len(standards) < _MIN_STANDARDS:
        log.warning(
            "curriculum_agent.low_standard_count",
            count=len(standards),
            minimum=_MIN_STANDARDS,
            subject=state["subject"],
            curriculum=state["curriculum"],
        )

    if len(objectives) < _MIN_OBJECTIVES:
        log.warning(
            "curriculum_agent.low_objective_count",
            count=len(objectives),
            minimum=_MIN_OBJECTIVES,
        )

    # Cap at 5 each — LLMs occasionally return more than asked
    standards = standards[:5]
    objectives = objectives[:5]
    prerequisites = prerequisites[:4]

    return standards, objectives, prerequisites


def _extract_string_list(raw: dict, key: str) -> list[str]:
    """
    Safely extract a list[str] from a raw LLM response dict.
    Handles: None values, non-list types, mixed-type lists.
    """
    value = raw.get(key)

    if not value:
        return []

    if not isinstance(value, list):
        # LLM sometimes returns a single string instead of a list
        if isinstance(value, str):
            return [value]
        return []

    result = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
        elif item is not None:
            # Coerce non-string non-null to string (e.g., LLM returned a dict)
            coerced = str(item).strip()
            if coerced:
                result.append(coerced)

    return result

# products/edu_video/backend/layer2_orchestrator/agents/subject_router.py
"""
SubjectRouterAgent: resolves the subject profile for a job and enriches
GraphState with renderer preferences, validation rules, and prompt fragments.

No LLM call — pure profile registry lookup.
Cost: $0.00 per invocation.
"""

import structlog

from layer1_input.schemas import CurriculumEnum, DifficultyEnum, SubjectEnum
from layer2_orchestrator.agents.base_agent import BaseAgent
from layer2_orchestrator.agents.subject_profiles import (
    ProfileNotFoundError,
    get_profile,
)
from layer2_orchestrator.graph import GraphState

__all__ = ["SubjectRouterAgent"]


class SubjectRouterAgent(BaseAgent):
    """
    Loads the registered BaseSubjectProfile for the job's subject and injects
    its configuration into GraphState so downstream agents don't need to
    re-instantiate the profile themselves.

    What it writes to GraphState:
        subject_profile        — full profile dict (includes script_guidelines
                                 and fact_check_prompt_fragment)
        renderer_preference    — ordered list of renderer strings
        validation_rules       — list of rule IDs for fact_checker_agent
        current_node           — "node_route_subject"

    What it does NOT do:
        - No LLM call
        - No DB or Redis access
        - No cost recorded (cost_usd = 0.0)
    """

    @property
    def agent_name(self) -> str:
        return "subject_router"

    async def run(self, state: GraphState) -> dict:
        job_id = state["job_id"]
        log = self.log.bind(
            job_id=job_id,
            subject=state["subject"],
            curriculum=state["curriculum"],
            difficulty=state["difficulty_level"],
        )
        log.info("subject_router.started")

        with self._timer() as t:
            try:
                # -------------------------------------------------- #
                # Step 1 — Validate and resolve SubjectEnum            #
                # -------------------------------------------------- #
                try:
                    subject = SubjectEnum(state["subject"])
                except ValueError:
                    # Subject value from queue payload doesn't match any enum member.
                    # This should never happen if Layer 1 validated correctly,
                    # but we handle it explicitly so the error message is clear.
                    raise ValueError(
                        f"Unknown subject {state['subject']!r}. "
                        f"Valid values: {[s.value for s in SubjectEnum]}"
                    )

                difficulty = DifficultyEnum(state["difficulty_level"])
                curriculum = CurriculumEnum(state["curriculum"])

                # -------------------------------------------------- #
                # Step 2 — Load profile from registry                 #
                # -------------------------------------------------- #
                profile = get_profile(subject)

                # -------------------------------------------------- #
                # Step 3 — Serialize profile to plain dict            #
                # -------------------------------------------------- #
                # to_dict() returns: subject, display_name,
                # renderer_preference, validation_rules,
                # visual_style, scene_structure_template
                profile_dict = profile.to_dict()

                # -------------------------------------------------- #
                # Step 4 — Inject agent-facing text fragments         #
                # -------------------------------------------------- #
                # These are computed here (not in to_dict) because they
                # require difficulty + curriculum context from the job,
                # which the profile itself doesn't hold as state.
                profile_dict["script_guidelines"] = profile.get_script_guidelines(
                    difficulty, curriculum
                )
                profile_dict["fact_check_prompt_fragment"] = (
                    profile.get_fact_check_prompt_fragment()
                )

                log.info(
                    "subject_router.completed",
                    display_name=profile.display_name,
                    primary_renderer=profile.get_primary_renderer(),
                    renderer_preference=profile.renderer_preference,
                    validation_rule_count=len(profile.validation_rules),
                    duration_ms=t["elapsed_ms"],
                )

                return {
                    "subject_profile": profile_dict,
                    "renderer_preference": profile.renderer_preference,
                    "validation_rules": profile.validation_rules,
                    "current_node": "node_route_subject",
                }

            # -------------------------------------------------- #
            # Error handling                                       #
            # -------------------------------------------------- #

            except ProfileNotFoundError as exc:
                # Subject is valid enum but no profile registered.
                # Possible during dev when a new subject is added to
                # SubjectEnum before its profile class is implemented.
                log.warning(
                    "subject_router.profile_not_found",
                    error=str(exc),
                    fallback_renderer="lottie",
                    duration_ms=t["elapsed_ms"],
                )
                return self._safe_return(
                    state,
                    error=str(exc),
                    defaults={
                        "subject_profile": _empty_profile_dict(state),
                        "renderer_preference": ["lottie"],
                        "validation_rules": [],
                        "current_node": "node_route_subject",
                    },
                )

            except ValueError as exc:
                # Bad enum value — payload corruption or Layer 1 bug.
                log.error(
                    "subject_router.invalid_enum_value",
                    error=str(exc),
                    duration_ms=t["elapsed_ms"],
                )
                return self._safe_return(
                    state,
                    error=str(exc),
                    defaults={
                        "subject_profile": _empty_profile_dict(state),
                        "renderer_preference": ["lottie"],
                        "validation_rules": [],
                        "current_node": "node_route_subject",
                    },
                )

            except Exception as exc:
                # Catch-all: unexpected error in profile code itself.
                log.error(
                    "subject_router.unexpected_error",
                    error=str(exc),
                    duration_ms=t["elapsed_ms"],
                )
                return self._safe_return(
                    state,
                    error=str(exc),
                    defaults={
                        "subject_profile": _empty_profile_dict(state),
                        "renderer_preference": ["lottie"],
                        "validation_rules": [],
                        "current_node": "node_route_subject",
                    },
                )


# --------------------------------------------------------------------------- #
# Module-level helpers                                                         #
# --------------------------------------------------------------------------- #

def _empty_profile_dict(state: GraphState) -> dict:
    """
    Minimal fallback profile dict used when the real profile cannot be loaded.
    Downstream agents check for empty dicts with .get(key, default), so this
    keeps them from KeyError-ing on missing profile fields.
    """
    return {
        "subject": state["subject"],
        "display_name": state["subject"].replace("_", " ").title(),
        "renderer_preference": ["lottie"],
        "validation_rules": [],
        "visual_style": {
            "color_palette": ["#6B7280", "#1F2937", "#F9FAFB", "#111827"],
            "layout": "default",
            "font_emphasis": "normal",
            "animation_speed": "moderate",
        },
        "scene_structure_template": [],
        "script_guidelines": "",
        "fact_check_prompt_fragment": "",
      }

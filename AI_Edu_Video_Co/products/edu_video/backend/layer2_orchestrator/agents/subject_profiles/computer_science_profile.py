# products/edu_video/backend/layer2_orchestrator/agents/subject_profiles/computer_science_profile.py
"""Computer Science subject profile — code-first, logic-accurate."""

from layer1_input.schemas import CurriculumEnum, DifficultyEnum, SubjectEnum
from layer2_orchestrator.agents.subject_profiles.base_profile import (
    BaseSubjectProfile,
    register_profile,
)

__all__ = ["ComputerScienceProfile"]


@register_profile(SubjectEnum.computer_science)
class ComputerScienceProfile(BaseSubjectProfile):
    """
    Profile for computer science content.
    Prioritizes code renderer for syntax-highlighted code, diagram for
    flowcharts and data structures, manim for algorithm visualization.
    """

    @property
    def subject(self) -> SubjectEnum:
        return SubjectEnum.computer_science

    @property
    def display_name(self) -> str:
        return "Computer Science"

    @property
    def renderer_preference(self) -> list[str]:
        return ["code", "diagram", "manim"]

    @property
    def validation_rules(self) -> list[str]:
        return [
            "check_code_syntax",
            "check_algorithm_correctness",
            "check_complexity_claims",
            "check_logical_consistency",
            "check_terminology_accuracy",
        ]

    @property
    def visual_style(self) -> dict:
        return {
            "color_palette": ["#06B6D4", "#164E63", "#CFFAFE", "#1F2937"],
            "layout": "code_with_explanation_sidebar",
            "font_emphasis": "monospace",
            "animation_speed": "step_by_step",
        }

    @property
    def scene_structure_template(self) -> list[dict]:
        return [
            {"scene_role": "hook", "content_focus": "real_world_problem_or_use_case", "suggested_duration_seconds": 30},
            {"scene_role": "concept_intro", "content_focus": "definition_and_mental_model", "suggested_duration_seconds": 45},
            {"scene_role": "pseudocode_or_algorithm", "content_focus": "high_level_logic_walkthrough", "suggested_duration_seconds": 60},
            {"scene_role": "code_implementation", "content_focus": "working_code_with_explanation", "suggested_duration_seconds": 60},
            {"scene_role": "complexity_and_tradeoffs", "content_focus": "time_space_complexity_analysis", "suggested_duration_seconds": 45},
            {"scene_role": "summary", "content_focus": "key_concepts_and_best_practices", "suggested_duration_seconds": 30},
        ]

    def get_renderer_for_content(self, content_type: str) -> str:
        mapping = {
            "equation": "manim",
            "diagram": "diagram",
            "graph": "diagram",
            "text": "lottie",
            "image": "flux_sdxl",
            "code": "code",
        }
        return mapping.get(content_type, "code")

    def get_script_guidelines(
        self,
        difficulty: DifficultyEnum,
        curriculum: CurriculumEnum,
    ) -> str:
        base = (
            "You are narrating a computer science lesson. Follow these guidelines:\n"
            "- Introduce concepts with a concrete real-world use case before abstraction.\n"
            "- Walk through code line by line when introducing new constructs; "
            "never skip steps on first exposure.\n"
            "- State Big-O complexity explicitly for all algorithms discussed.\n"
            "- Distinguish between the algorithm (logic) and the implementation (code).\n"
            "- When showing code, specify the programming language being used.\n"
        )

        difficulty_fragment = {
            DifficultyEnum.beginner: (
                "- Use Python as the default language for beginner content (most readable).\n"
                "- Avoid recursion and pointer-based explanations at this level.\n"
                "- Narrate every line of code in plain English before showing it.\n"
            ),
            DifficultyEnum.intermediate: (
                "- Introduce multiple implementation approaches and compare them.\n"
                "- Include both iterative and recursive solutions where applicable.\n"
                "- Discuss edge cases and input validation.\n"
            ),
            DifficultyEnum.advanced: (
                "- Cover formal proofs of correctness and complexity where relevant.\n"
                "- Discuss memory models, caching effects, and low-level performance.\n"
                "- Reference foundational papers or algorithms by their canonical names.\n"
            ),
        }.get(difficulty, "")

        curriculum_fragment = {
            CurriculumEnum.IB: "- Reference IB Computer Science SL/HL syllabus topics and option chapters.\n",
            CurriculumEnum.Cambridge: "- Use Cambridge A-Level Computer Science 9618 pseudocode conventions.\n",
            CurriculumEnum.AP: "- Align with AP Computer Science A (Java) or AP Computer Science Principles framework.\n",
            CurriculumEnum.general: "- Use language-agnostic pseudocode and standard CS terminology.\n",
        }.get(curriculum, "")

        return base + difficulty_fragment + curriculum_fragment

    def get_fact_check_prompt_fragment(self) -> str:
        return (
            "Verify the following for every computer science scene:\n"
            "1) All code snippets are syntactically correct for the stated language.\n"
            "2) Algorithms produce the correct output for the described inputs.\n"
            "3) Big-O complexity claims are accurate for the described algorithm.\n"
            "4) Logical reasoning (if/else, loop termination, recursion base cases) is correct.\n"
            "5) CS terminology is used precisely "
            "(e.g., 'stack' vs 'heap', 'class' vs 'object', 'parameter' vs 'argument').\n"
            "Flag any code that would produce a runtime error or incorrect output."
      )

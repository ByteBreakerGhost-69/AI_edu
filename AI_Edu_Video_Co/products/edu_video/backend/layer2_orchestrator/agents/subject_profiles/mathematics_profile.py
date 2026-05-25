# products/edu_video/backend/layer2_orchestrator/agents/subject_profiles/mathematics_profile.py
"""Mathematics subject profile — Manim-first, equation-centered."""

from layer1_input.schemas import CurriculumEnum, DifficultyEnum, SubjectEnum
from layer2_orchestrator.agents.subject_profiles.base_profile import (
    BaseSubjectProfile,
    register_profile,
)

__all__ = ["MathematicsProfile"]


@register_profile(SubjectEnum.mathematics)
class MathematicsProfile(BaseSubjectProfile):
    """
    Profile for mathematics content.
    Prioritizes Manim for equation rendering and step-by-step animations.
    Emphasizes formal notation, variable definition, and proof completeness.
    """

    @property
    def subject(self) -> SubjectEnum:
        return SubjectEnum.mathematics

    @property
    def display_name(self) -> str:
        return "Mathematics"

    @property
    def renderer_preference(self) -> list[str]:
        return ["manim", "diagram", "lottie"]

    @property
    def validation_rules(self) -> list[str]:
        return [
            "check_equation_syntax",
            "check_unit_consistency",
            "check_proof_completeness",
            "check_variable_definition",
            "check_numeric_accuracy",
        ]

    @property
    def visual_style(self) -> dict:
        return {
            "color_palette": ["#3B82F6", "#1E40AF", "#DBEAFE", "#1F2937"],
            "layout": "equation_centered",
            "font_emphasis": "latex",
            "animation_speed": "deliberate",
        }

    @property
    def scene_structure_template(self) -> list[dict]:
        """Returns intermediate (6-scene) template."""
        return [
            {
                "scene_role": "hook",
                "content_focus": "real_world_problem",
                "suggested_duration_seconds": 30,
            },
            {
                "scene_role": "concept_intro",
                "content_focus": "definition_and_notation",
                "suggested_duration_seconds": 45,
            },
            {
                "scene_role": "worked_example_1",
                "content_focus": "step_by_step_solution",
                "suggested_duration_seconds": 60,
            },
            {
                "scene_role": "worked_example_2",
                "content_focus": "variation_or_harder_case",
                "suggested_duration_seconds": 60,
            },
            {
                "scene_role": "common_mistakes",
                "content_focus": "error_analysis",
                "suggested_duration_seconds": 45,
            },
            {
                "scene_role": "summary",
                "content_focus": "key_formulas_and_takeaways",
                "suggested_duration_seconds": 30,
            },
        ]

    def get_scene_structure_for_difficulty(self, difficulty: DifficultyEnum) -> list[dict]:
        """Return difficulty-adjusted scene structure."""
        if difficulty == DifficultyEnum.beginner:
            return [
                {"scene_role": "hook", "content_focus": "real_world_problem", "suggested_duration_seconds": 30},
                {"scene_role": "concept_intro", "content_focus": "definition_and_notation", "suggested_duration_seconds": 45},
                {"scene_role": "worked_example_1", "content_focus": "step_by_step_solution", "suggested_duration_seconds": 60},
                {"scene_role": "summary", "content_focus": "key_formulas_and_takeaways", "suggested_duration_seconds": 30},
            ]
        if difficulty == DifficultyEnum.advanced:
            return [
                {"scene_role": "hook", "content_focus": "real_world_problem", "suggested_duration_seconds": 30},
                {"scene_role": "concept_intro", "content_focus": "formal_definition_and_notation", "suggested_duration_seconds": 45},
                {"scene_role": "proof", "content_focus": "formal_proof_walkthrough", "suggested_duration_seconds": 60},
                {"scene_role": "worked_example_1", "content_focus": "step_by_step_solution", "suggested_duration_seconds": 60},
                {"scene_role": "worked_example_2", "content_focus": "variation_or_harder_case", "suggested_duration_seconds": 60},
                {"scene_role": "extension", "content_focus": "generalization_or_related_theorem", "suggested_duration_seconds": 45},
                {"scene_role": "applications", "content_focus": "real_world_mathematical_applications", "suggested_duration_seconds": 45},
                {"scene_role": "summary", "content_focus": "key_formulas_and_takeaways", "suggested_duration_seconds": 30},
            ]
        return self.scene_structure_template

    def get_renderer_for_content(self, content_type: str) -> str:
        mapping = {
            "equation": "manim",
            "diagram": "manim",
            "graph": "manim",
            "text": "lottie",
            "image": "flux_sdxl",
            "code": "code",
        }
        return mapping.get(content_type, "manim")

    def get_script_guidelines(
        self,
        difficulty: DifficultyEnum,
        curriculum: CurriculumEnum,
    ) -> str:
        base = (
            "You are narrating a mathematics lesson. Follow these guidelines:\n"
            "- Always define every variable before its first use.\n"
            "- State the theorem or formula explicitly before applying it.\n"
            "- Use the 'we' perspective throughout: 'We now substitute x=...'\n"
            "- Announce each step before performing it: 'Next, we factor the left side...'\n"
            "- Confirm intermediate results with a brief check.\n"
        )

        difficulty_fragment = {
            DifficultyEnum.beginner: (
                "- Avoid sigma notation; write out sums in expanded form.\n"
                "- Use simple numeric examples before introducing general cases.\n"
                "- Avoid proofs; focus on procedural understanding.\n"
            ),
            DifficultyEnum.intermediate: (
                "- Introduce both procedural and conceptual understanding.\n"
                "- Include one numerical worked example and one symbolic generalization.\n"
            ),
            DifficultyEnum.advanced: (
                "- Use formal proof language: 'Let ε > 0 be given...', 'It follows that...'\n"
                "- Mark the end of proofs with QED or ∎.\n"
                "- Reference relevant theorems by name (e.g., Fundamental Theorem of Calculus).\n"
            ),
        }.get(difficulty, "")

        curriculum_fragment = {
            CurriculumEnum.IB: "- Reference IB formula booklet notation and topic numbers (e.g., Topic 5.4).\n",
            CurriculumEnum.Cambridge: "- Use Cambridge A-Level standard notation as per syllabus 9709.\n",
            CurriculumEnum.AP: "- Align with AP Calculus AB/BC or AP Statistics formula sheet notation.\n",
            CurriculumEnum.general: "- Use widely accepted standard mathematical notation.\n",
        }.get(curriculum, "")

        return base + difficulty_fragment + curriculum_fragment

    def get_fact_check_prompt_fragment(self) -> str:
        return (
            "Verify the following for every mathematics scene:\n"
            "1) All equations are syntactically correct and valid LaTeX.\n"
            "2) Arithmetic results are numerically accurate (double-check all calculations).\n"
            "3) Every variable is defined before its first use in the narration.\n"
            "4) Proof steps follow logically with no skipped or unjustified gaps.\n"
            "5) Units are consistent throughout any applied problems.\n"
            "Flag any equation that cannot be rendered as valid LaTeX."
      )

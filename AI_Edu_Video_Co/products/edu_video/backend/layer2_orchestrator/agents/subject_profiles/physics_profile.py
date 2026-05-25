# products/edu_video/backend/layer2_orchestrator/agents/subject_profiles/physics_profile.py
"""Physics subject profile — diagram-first, SI units enforced."""

from layer1_input.schemas import CurriculumEnum, DifficultyEnum, SubjectEnum
from layer2_orchestrator.agents.subject_profiles.base_profile import (
    BaseSubjectProfile,
    register_profile,
)

__all__ = ["PhysicsProfile"]


@register_profile(SubjectEnum.physics)
class PhysicsProfile(BaseSubjectProfile):
    """
    Profile for physics content.
    Prioritizes diagrams for force/circuit/wave visualization,
    Manim for equation derivations. Enforces SI units and conservation laws.
    """

    @property
    def subject(self) -> SubjectEnum:
        return SubjectEnum.physics

    @property
    def display_name(self) -> str:
        return "Physics"

    @property
    def renderer_preference(self) -> list[str]:
        return ["diagram", "manim", "lottie"]

    @property
    def validation_rules(self) -> list[str]:
        return [
            "check_formula_syntax",
            "check_unit_consistency",
            "check_significant_figures",
            "check_vector_direction",
            "check_conservation_laws",
        ]

    @property
    def visual_style(self) -> dict:
        return {
            "color_palette": ["#10B981", "#064E3B", "#D1FAE5", "#111827"],
            "layout": "diagram_with_equation_sidebar",
            "font_emphasis": "mixed",
            "animation_speed": "moderate",
        }

    @property
    def scene_structure_template(self) -> list[dict]:
        return [
            {"scene_role": "hook", "content_focus": "phenomenon_observation", "suggested_duration_seconds": 30},
            {"scene_role": "concept_intro", "content_focus": "physics_law_statement", "suggested_duration_seconds": 45},
            {"scene_role": "diagram_explanation", "content_focus": "force_circuit_or_wave_diagram", "suggested_duration_seconds": 60},
            {"scene_role": "mathematical_derivation", "content_focus": "equation_walkthrough", "suggested_duration_seconds": 60},
            {"scene_role": "real_world_application", "content_focus": "engineering_or_natural_example", "suggested_duration_seconds": 45},
            {"scene_role": "summary", "content_focus": "formula_sheet_review", "suggested_duration_seconds": 30},
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
        return mapping.get(content_type, "diagram")

    def get_script_guidelines(
        self,
        difficulty: DifficultyEnum,
        curriculum: CurriculumEnum,
    ) -> str:
        base = (
            "You are narrating a physics lesson. Follow these guidelines:\n"
            "- Always state the SI unit of every quantity on first mention.\n"
            "- Describe physical intuition and the observable phenomenon BEFORE the mathematical derivation.\n"
            "- Use vivid language: 'Imagine a ball rolling down a ramp...', 'Picture the magnetic field lines...'\n"
            "- When introducing vector quantities, always specify direction as well as magnitude.\n"
            "- Connect equations back to the physical meaning after deriving them.\n"
        )

        difficulty_fragment = {
            DifficultyEnum.beginner: (
                "- Avoid calculus; use algebra-based relationships only.\n"
                "- Emphasize everyday analogies over abstract formalism.\n"
                "- Use concrete numbers rather than symbolic derivations.\n"
            ),
            DifficultyEnum.intermediate: (
                "- Introduce both conceptual and algebraic treatments.\n"
                "- Include one diagram-based and one equation-based explanation per topic.\n"
            ),
            DifficultyEnum.advanced: (
                "- Use calculus-based derivations where appropriate.\n"
                "- Reference fundamental postulates (Newton's laws, Maxwell's equations, etc.) by name.\n"
                "- Discuss limiting cases and boundary conditions.\n"
            ),
        }.get(difficulty, "")

        curriculum_fragment = {
            CurriculumEnum.IB: "- Reference IB Physics data booklet values and equation numbers.\n",
            CurriculumEnum.Cambridge: "- Use Cambridge A-Level Physics 9702 formula notation and syllabus section references.\n",
            CurriculumEnum.AP: "- Align notation with AP Physics 1, 2, or C equation sheets as appropriate.\n",
            CurriculumEnum.general: "- Use standard SI notation and widely accepted physics conventions.\n",
        }.get(curriculum, "")

        return base + difficulty_fragment + curriculum_fragment

    def get_fact_check_prompt_fragment(self) -> str:
        return (
            "Verify the following for every physics scene:\n"
            "1) All formulas match standard physics notation and are dimensionally consistent.\n"
            "2) Apply dimensional analysis to confirm unit correctness.\n"
            "3) Numerical constants match NIST-accepted values "
            "(e.g., g = 9.81 m/s², c = 2.998 × 10⁸ m/s, h = 6.626 × 10⁻³⁴ J·s).\n"
            "4) All vector quantities specify direction explicitly.\n"
            "5) No violation of conservation laws (energy, momentum, angular momentum, charge).\n"
            "Flag any equation where units do not balance."
      )

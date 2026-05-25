# products/edu_video/backend/layer2_orchestrator/agents/subject_profiles/economics_profile.py
"""Economics subject profile — graph-first, model-assumption-explicit."""

from layer1_input.schemas import CurriculumEnum, DifficultyEnum, SubjectEnum
from layer2_orchestrator.agents.subject_profiles.base_profile import (
    BaseSubjectProfile,
    register_profile,
)

__all__ = ["EconomicsProfile"]


@register_profile(SubjectEnum.economics)
class EconomicsProfile(BaseSubjectProfile):
    """
    Profile for economics content.
    Prioritizes graph renderer for supply/demand and macroeconomic charts.
    Enforces model assumptions, axis labels, and causal vs. correlational clarity.
    """

    @property
    def subject(self) -> SubjectEnum:
        return SubjectEnum.economics

    @property
    def display_name(self) -> str:
        return "Economics"

    @property
    def renderer_preference(self) -> list[str]:
        return ["graph", "diagram", "lottie"]

    @property
    def validation_rules(self) -> list[str]:
        return [
            "check_economic_model_assumptions",
            "check_graph_axis_labels",
            "check_data_currency",
            "check_causal_vs_correlation",
            "check_market_structure",
        ]

    @property
    def visual_style(self) -> dict:
        return {
            "color_palette": ["#8B5CF6", "#4C1D95", "#EDE9FE", "#1F2937"],
            "layout": "graph_with_analysis",
            "font_emphasis": "data_labels",
            "animation_speed": "analytical",
        }

    @property
    def scene_structure_template(self) -> list[dict]:
        return [
            {"scene_role": "hook", "content_focus": "economic_real_world_scenario", "suggested_duration_seconds": 30},
            {"scene_role": "model_intro", "content_focus": "assumptions_and_framework", "suggested_duration_seconds": 45},
            {"scene_role": "graph_construction", "content_focus": "supply_demand_or_model_diagram", "suggested_duration_seconds": 60},
            {"scene_role": "analysis", "content_focus": "shifts_equilibrium_effects", "suggested_duration_seconds": 60},
            {"scene_role": "policy_application", "content_focus": "government_or_market_response", "suggested_duration_seconds": 45},
            {"scene_role": "summary", "content_focus": "key_concepts_and_graph_reading", "suggested_duration_seconds": 30},
        ]

    def get_renderer_for_content(self, content_type: str) -> str:
        mapping = {
            "equation": "graph",
            "diagram": "diagram",
            "graph": "graph",
            "text": "lottie",
            "image": "flux_sdxl",
            "code": "code",
        }
        return mapping.get(content_type, "graph")

    def get_script_guidelines(
        self,
        difficulty: DifficultyEnum,
        curriculum: CurriculumEnum,
    ) -> str:
        base = (
            "You are narrating an economics lesson. Follow these guidelines:\n"
            "- State all model assumptions explicitly before beginning analysis.\n"
            "- Label every graph axis with both the variable name AND its unit or scale.\n"
            "- Distinguish clearly between short-run and long-run effects.\n"
            "- Use 'ceteris paribus' (all else equal) explicitly when holding variables constant.\n"
            "- Distinguish correlation from causation — never imply causality from data alone.\n"
        )

        difficulty_fragment = {
            DifficultyEnum.beginner: (
                "- Use everyday examples: supermarket pricing, household budgets.\n"
                "- Build graphs step-by-step, one curve at a time.\n"
                "- Avoid mathematical derivations; focus on graphical intuition.\n"
            ),
            DifficultyEnum.intermediate: (
                "- Introduce both graphical and algebraic representations of key models.\n"
                "- Apply models to real-world policy examples.\n"
            ),
            DifficultyEnum.advanced: (
                "- Engage with econometric reasoning and model limitations.\n"
                "- Discuss heterodox perspectives alongside mainstream models.\n"
                "- Reference empirical evidence for theoretical claims.\n"
            ),
        }.get(difficulty, "")

        curriculum_fragment = {
            CurriculumEnum.IB: "- Reference IB Economics SL/HL syllabus section numbers.\n",
            CurriculumEnum.Cambridge: "- Use Cambridge A-Level Economics 9708 framework and case study approach.\n",
            CurriculumEnum.AP: "- Align with AP Microeconomics or AP Macroeconomics curriculum framework.\n",
            CurriculumEnum.general: "- Use standard economic terminology as per mainstream economics textbooks.\n",
        }.get(curriculum, "")

        return base + difficulty_fragment + curriculum_fragment

    def get_fact_check_prompt_fragment(self) -> str:
        return (
            "Verify the following for every economics scene:\n"
            "1) Economic models are applied strictly within their stated assumptions.\n"
            "2) Graph relationships (curve slopes, shift directions) are economically correct.\n"
            "3) Causal claims are clearly distinguished from correlational observations.\n"
            "4) Policy effects described are consistent with mainstream economic theory.\n"
            "5) Any cited data (GDP growth rates, inflation ranges, unemployment figures) "
            "is plausible and approximately sourced.\n"
            "Flag any graph where the slope or shift direction contradicts standard economic theory."
        )

# products/edu_video/backend/layer2_orchestrator/agents/subject_profiles/history_profile.py
"""History subject profile — timeline-first, multi-perspective narrative."""

from layer1_input.schemas import CurriculumEnum, DifficultyEnum, SubjectEnum
from layer2_orchestrator.agents.subject_profiles.base_profile import (
    BaseSubjectProfile,
    register_profile,
)

__all__ = ["HistoryProfile"]


@register_profile(SubjectEnum.history)
class HistoryProfile(BaseSubjectProfile):
    """
    Profile for history content.
    Prioritizes timeline renderer for chronological events and flux_sdxl
    for historical imagery. Enforces date accuracy and historiographical balance.
    """

    @property
    def subject(self) -> SubjectEnum:
        return SubjectEnum.history

    @property
    def display_name(self) -> str:
        return "History"

    @property
    def renderer_preference(self) -> list[str]:
        return ["timeline", "flux_sdxl", "lottie"]

    @property
    def validation_rules(self) -> list[str]:
        return [
            "check_date_accuracy",
            "check_historical_causation",
            "check_source_attribution",
            "check_anachronism",
            "check_historiographical_balance",
        ]

    @property
    def visual_style(self) -> dict:
        return {
            "color_palette": ["#DC2626", "#7F1D1D", "#FEE2E2", "#1F2937"],
            "layout": "timeline_narrative",
            "font_emphasis": "serif_formal",
            "animation_speed": "measured",
        }

    @property
    def scene_structure_template(self) -> list[dict]:
        return [
            {"scene_role": "hook", "content_focus": "historical_mystery_or_impact_question", "suggested_duration_seconds": 30},
            {"scene_role": "context", "content_focus": "era_geography_society_background", "suggested_duration_seconds": 45},
            {"scene_role": "key_events", "content_focus": "chronological_narrative", "suggested_duration_seconds": 60},
            {"scene_role": "causes_and_effects", "content_focus": "causal_analysis", "suggested_duration_seconds": 60},
            {"scene_role": "historical_significance", "content_focus": "long_term_impact", "suggested_duration_seconds": 45},
            {"scene_role": "summary", "content_focus": "key_dates_figures_concepts", "suggested_duration_seconds": 30},
        ]

    def get_renderer_for_content(self, content_type: str) -> str:
        mapping = {
            "equation": "lottie",
            "diagram": "timeline",
            "graph": "diagram",
            "text": "lottie",
            "image": "flux_sdxl",
            "code": "lottie",
        }
        return mapping.get(content_type, "timeline")

    def get_script_guidelines(
        self,
        difficulty: DifficultyEnum,
        curriculum: CurriculumEnum,
    ) -> str:
        base = (
            "You are narrating a history lesson. Follow these guidelines:\n"
            "- Anchor every factual claim to a specific date, decade, century, or era.\n"
            "- Present multiple historical perspectives where scholarly debate exists — "
            "avoid presenting one interpretation as the singular truth.\n"
            "- Use primary source quotes sparingly (1-2 per video) and attribute them precisely.\n"
            "- Avoid presentism: contextualize past actions within their historical moment "
            "before applying modern moral frameworks.\n"
            "- Name key figures with their full name on first mention, then surname only.\n"
        )

        difficulty_fragment = {
            DifficultyEnum.beginner: (
                "- Focus on narrative and chronology; avoid historiographical debate.\n"
                "- Use story-based structure: 'First... then... finally...'\n"
                "- Limit the number of key figures to 3-4 per video.\n"
            ),
            DifficultyEnum.intermediate: (
                "- Introduce cause-and-effect relationships explicitly.\n"
                "- Distinguish short-term triggers from long-term causes.\n"
            ),
            DifficultyEnum.advanced: (
                "- Engage with historiographical debate: name and compare historians' interpretations.\n"
                "- Analyze primary sources critically.\n"
                "- Discuss counterfactuals where academically relevant.\n"
            ),
        }.get(difficulty, "")

        curriculum_fragment = {
            CurriculumEnum.IB: "- Reference IB History HL/SL prescribed subjects and optional themes.\n",
            CurriculumEnum.Cambridge: "- Use Cambridge A-Level History 9489 themes and source skills framework.\n",
            CurriculumEnum.AP: "- Align with AP World, US, or European History frameworks and HAPP skills.\n",
            CurriculumEnum.general: "- Use standard historical periodization and widely accepted scholarly consensus.\n",
        }.get(curriculum, "")

        return base + difficulty_fragment + curriculum_fragment

    def get_fact_check_prompt_fragment(self) -> str:
        return (
            "Verify the following for every history scene:\n"
            "1) All dates are accurate and cross-check against the established historical record.\n"
            "2) Causation claims are properly supported — avoid post hoc ergo propter hoc fallacy.\n"
            "3) No anachronistic references (no concepts, technologies, or terms used before their invention).\n"
            "4) Historical figures are correctly attributed to their role and time period.\n"
            "5) Multiple historiographical perspectives are acknowledged where scholarly debate exists.\n"
            "Flag any date that differs from the consensus historical record by more than 1 year."
        )

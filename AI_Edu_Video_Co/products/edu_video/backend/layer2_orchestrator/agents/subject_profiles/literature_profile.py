# products/edu_video/backend/layer2_orchestrator/agents/subject_profiles/literature_profile.py
"""Literature subject profile — text-and-mood-image, typographic emphasis."""

from layer1_input.schemas import CurriculumEnum, DifficultyEnum, SubjectEnum
from layer2_orchestrator.agents.subject_profiles.base_profile import (
    BaseSubjectProfile,
    register_profile,
)

__all__ = ["LiteratureProfile"]


@register_profile(SubjectEnum.literature)
class LiteratureProfile(BaseSubjectProfile):
    """
    Profile for literature content.
    Prioritizes lottie for animated typography, flux_sdxl for mood imagery,
    timeline for plot structure. Enforces attribution and interpretive balance.
    """

    @property
    def subject(self) -> SubjectEnum:
        return SubjectEnum.literature

    @property
    def display_name(self) -> str:
        return "Literature"

    @property
    def renderer_preference(self) -> list[str]:
        return ["lottie", "flux_sdxl", "timeline"]

    @property
    def validation_rules(self) -> list[str]:
        return [
            "check_literary_term_accuracy",
            "check_author_attribution",
            "check_publication_date",
            "check_cultural_context",
            "check_interpretation_balance",
        ]

    @property
    def visual_style(self) -> dict:
        return {
            "color_palette": ["#F97316", "#7C2D12", "#FFEDD5", "#1F2937"],
            "layout": "text_and_mood_image",
            "font_emphasis": "typographic",
            "animation_speed": "expressive",
        }

    @property
    def scene_structure_template(self) -> list[dict]:
        return [
            {"scene_role": "hook", "content_focus": "thematic_question_or_famous_quote", "suggested_duration_seconds": 30},
            {"scene_role": "author_and_context", "content_focus": "biography_historical_setting", "suggested_duration_seconds": 45},
            {"scene_role": "plot_or_structure", "content_focus": "narrative_arc_overview", "suggested_duration_seconds": 60},
            {"scene_role": "literary_devices", "content_focus": "technique_analysis_with_examples", "suggested_duration_seconds": 60},
            {"scene_role": "themes_and_interpretation", "content_focus": "meaning_and_critical_perspectives", "suggested_duration_seconds": 45},
            {"scene_role": "summary", "content_focus": "key_devices_themes_quotes", "suggested_duration_seconds": 30},
        ]

    def get_renderer_for_content(self, content_type: str) -> str:
        mapping = {
            "equation": "lottie",
            "diagram": "diagram",
            "graph": "diagram",
            "text": "lottie",
            "image": "flux_sdxl",
            "code": "lottie",
        }
        return mapping.get(content_type, "lottie")

    def get_script_guidelines(
        self,
        difficulty: DifficultyEnum,
        curriculum: CurriculumEnum,
    ) -> str:
        base = (
            "You are narrating a literature lesson. Follow these guidelines:\n"
            "- Attribute all quotes to the specific work and author: "
            "'In Chapter 3 of *Pride and Prejudice*, Austen writes...'\n"
            "- Define each literary term at the moment of first use with a one-sentence definition.\n"
            "- Present literary interpretation as interpretation, not fact: "
            "'One reading suggests...', 'Critics have argued...'\n"
            "- Use present tense when discussing the text itself: "
            "'Hamlet hesitates because...', not 'Hamlet hesitated...'\n"
            "- Balance close textual analysis with broader thematic discussion.\n"
        )

        difficulty_fragment = {
            DifficultyEnum.beginner: (
                "- Focus on plot summary and character identification before analysis.\n"
                "- Introduce no more than 3 literary terms per video.\n"
                "- Use relatable modern comparisons for classic texts.\n"
            ),
            DifficultyEnum.intermediate: (
                "- Balance plot comprehension with device analysis and thematic exploration.\n"
                "- Introduce at least two critical perspectives on the text.\n"
            ),
            DifficultyEnum.advanced: (
                "- Engage with named critical theories (feminist, Marxist, post-colonial, etc.).\n"
                "- Analyze authorial craft at the sentence and word level.\n"
                "- Reference secondary scholarly sources where relevant.\n"
            ),
        }.get(difficulty, "")

        curriculum_fragment = {
            CurriculumEnum.IB: "- Reference IB Language A: Literature or Language and Literature syllabus areas of exploration.\n",
            CurriculumEnum.Cambridge: "- Use Cambridge A-Level English Literature 9695 assessment objectives.\n",
            CurriculumEnum.AP: "- Align with AP Literature and Composition or AP Language and Composition framework.\n",
            CurriculumEnum.general: "- Use standard literary analysis conventions and terminology.\n",
        }.get(curriculum, "")

        return base + difficulty_fragment + curriculum_fragment

    def get_fact_check_prompt_fragment(self) -> str:
        return (
            "Verify the following for every literature scene:\n"
            "1) Literary terms are used accurately and defined correctly.\n"
            "2) All quotes are correctly attributed to the right author and work.\n"
            "3) Publication dates and biographical facts about authors are accurate.\n"
            "4) Cultural and historical context for the text is correctly represented.\n"
            "5) Interpretive claims are presented as interpretations, not as objective facts.\n"
            "Flag any quote that cannot be verified as appearing in the cited work."
             )

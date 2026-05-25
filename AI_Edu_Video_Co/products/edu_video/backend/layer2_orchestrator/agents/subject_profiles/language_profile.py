# products/edu_video/backend/layer2_orchestrator/agents/subject_profiles/language_profile.py
"""Language subject profile — dialog-first, grammar-accurate."""

from layer1_input.schemas import CurriculumEnum, DifficultyEnum, SubjectEnum
from layer2_orchestrator.agents.subject_profiles.base_profile import (
    BaseSubjectProfile,
    register_profile,
)

__all__ = ["LanguageProfile"]


@register_profile(SubjectEnum.language)
class LanguageProfile(BaseSubjectProfile):
    """
    Profile for language learning content.
    Prioritizes lottie for dialog animations and text display,
    flux_sdxl for cultural context imagery.
    """

    @property
    def subject(self) -> SubjectEnum:
        return SubjectEnum.language

    @property
    def display_name(self) -> str:
        return "Language"

    @property
    def renderer_preference(self) -> list[str]:
        return ["lottie", "flux_sdxl", "diagram"]

    @property
    def validation_rules(self) -> list[str]:
        return [
            "check_grammar_accuracy",
            "check_vocabulary_level",
            "check_phonetic_notation",
            "check_cultural_appropriateness",
            "check_dialect_consistency",
        ]

    @property
    def visual_style(self) -> dict:
        return {
            "color_palette": ["#EC4899", "#831843", "#FCE7F3", "#1F2937"],
            "layout": "dialog_and_text",
            "font_emphasis": "multilingual",
            "animation_speed": "conversational",
        }

    @property
    def scene_structure_template(self) -> list[dict]:
        return [
            {"scene_role": "hook", "content_focus": "communicative_situation_or_question", "suggested_duration_seconds": 30},
            {"scene_role": "vocabulary_intro", "content_focus": "key_words_with_pronunciation", "suggested_duration_seconds": 45},
            {"scene_role": "grammar_point", "content_focus": "rule_explanation_with_examples", "suggested_duration_seconds": 60},
            {"scene_role": "dialog_example", "content_focus": "natural_conversation_in_context", "suggested_duration_seconds": 60},
            {"scene_role": "cultural_context", "content_focus": "usage_norms_and_cultural_notes", "suggested_duration_seconds": 45},
            {"scene_role": "summary", "content_focus": "key_vocabulary_and_grammar_rules", "suggested_duration_seconds": 30},
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
            "You are narrating a language learning lesson. Follow these guidelines:\n"
            "- Present vocabulary in context first, then isolate and define the word.\n"
            "- Include phonetic transcription (IPA) for new vocabulary on first mention.\n"
            "- Model natural spoken language in dialog examples — avoid overly formal textbook sentences.\n"
            "- When introducing grammar rules, give the rule, then 3 examples "
            "(positive, negative, question form where applicable).\n"
            "- Acknowledge that language varies by dialect and register.\n"
        )

        difficulty_fragment = {
            DifficultyEnum.beginner: (
                "- Use the learner's native language (L1) for concept explanation where helpful.\n"
                "- Introduce no more than 10 new vocabulary items per video.\n"
                "- Focus on high-frequency words and survival phrases.\n"
                "- Speak slowly and repeat key phrases twice.\n"
            ),
            DifficultyEnum.intermediate: (
                "- Conduct lessons primarily in the target language.\n"
                "- Introduce idiomatic expressions alongside literal meanings.\n"
                "- Include authentic materials (real dialogs, news excerpts) as examples.\n"
            ),
            DifficultyEnum.advanced: (
                "- Conduct lessons entirely in the target language.\n"
                "- Discuss register, pragmatics, and sociolinguistic variation.\n"
                "- Introduce advanced grammar (subjunctive, complex conditionals) with full treatment.\n"
            ),
        }.get(difficulty, "")

        curriculum_fragment = {
            CurriculumEnum.IB: "- Reference IB Language B or Language ab initio syllabus themes and text types.\n",
            CurriculumEnum.Cambridge: "- Use Cambridge IGCSE or A-Level Language syllabus communicative functions.\n",
            CurriculumEnum.AP: "- Align with AP World Language and Culture framework (interpersonal, interpretive, presentational).\n",
            CurriculumEnum.general: "- Use CEFR level descriptors (A1-C2) as reference for vocabulary and grammar scope.\n",
        }.get(curriculum, "")

        return base + difficulty_fragment + curriculum_fragment

    def get_fact_check_prompt_fragment(self) -> str:
        return (
            "Verify the following for every language lesson scene:\n"
            "1) All grammar rules stated are correct for the target language and dialect.\n"
            "2) Vocabulary definitions are accurate and contemporary (not archaic).\n"
            "3) IPA phonetic transcriptions are correct for the target dialect.\n"
            "4) Cultural notes are sensitive, accurate, and not stereotyping.\n"
            "5) Example sentences are grammatically correct and natural-sounding for native speakers.\n"
            "Flag any grammar rule that contradicts the standard reference grammar for the target language."
      )

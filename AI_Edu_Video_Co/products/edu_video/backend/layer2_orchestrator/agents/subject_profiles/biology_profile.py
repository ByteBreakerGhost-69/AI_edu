# products/edu_video/backend/layer2_orchestrator/agents/subject_profiles/biology_profile.py
"""Biology subject profile — illustration-dominant, taxonomy-accurate."""

from layer1_input.schemas import CurriculumEnum, DifficultyEnum, SubjectEnum
from layer2_orchestrator.agents.subject_profiles.base_profile import (
    BaseSubjectProfile,
    register_profile,
)

__all__ = ["BiologyProfile"]


@register_profile(SubjectEnum.biology)
class BiologyProfile(BaseSubjectProfile):
    """
    Profile for biology content.
    Prioritizes flux_sdxl for biological illustrations, lottie for
    process animations. Enforces current taxonomy and evolutionary accuracy.
    """

    @property
    def subject(self) -> SubjectEnum:
        return SubjectEnum.biology

    @property
    def display_name(self) -> str:
        return "Biology"

    @property
    def renderer_preference(self) -> list[str]:
        return ["flux_sdxl", "lottie", "diagram"]

    @property
    def validation_rules(self) -> list[str]:
        return [
            "check_taxonomy_accuracy",
            "check_biological_terminology",
            "check_process_sequence",
            "check_anatomical_accuracy",
            "check_evolutionary_claims",
        ]

    @property
    def visual_style(self) -> dict:
        return {
            "color_palette": ["#22C55E", "#14532D", "#DCFCE7", "#1F2937"],
            "layout": "illustration_dominant",
            "font_emphasis": "scientific_italic",
            "animation_speed": "natural",
        }

    @property
    def scene_structure_template(self) -> list[dict]:
        return [
            {"scene_role": "hook", "content_focus": "biological_phenomenon_or_question", "suggested_duration_seconds": 30},
            {"scene_role": "organism_or_system_intro", "content_focus": "context_and_classification", "suggested_duration_seconds": 45},
            {"scene_role": "structure_explanation", "content_focus": "anatomy_or_molecular_structure", "suggested_duration_seconds": 60},
            {"scene_role": "process_walkthrough", "content_focus": "biological_process_steps", "suggested_duration_seconds": 60},
            {"scene_role": "ecological_or_clinical_relevance", "content_focus": "real_world_connection", "suggested_duration_seconds": 45},
            {"scene_role": "summary", "content_focus": "key_concepts_and_vocabulary", "suggested_duration_seconds": 30},
        ]

    def get_renderer_for_content(self, content_type: str) -> str:
        mapping = {
            "equation": "diagram",
            "diagram": "diagram",
            "graph": "diagram",
            "text": "lottie",
            "image": "flux_sdxl",
            "code": "code",
        }
        return mapping.get(content_type, "flux_sdxl")

    def get_script_guidelines(
        self,
        difficulty: DifficultyEnum,
        curriculum: CurriculumEnum,
    ) -> str:
        base = (
            "You are narrating a biology lesson. Follow these guidelines:\n"
            "- Use binomial nomenclature in italics for species on first mention "
            "(e.g., *Homo sapiens*), then use the common name.\n"
            "- Present biological processes as numbered sequential steps.\n"
            "- Connect cellular or molecular explanations up to the organism and ecosystem level.\n"
            "- Distinguish structure from function explicitly for every organelle or organ.\n"
            "- Use active, present-tense verbs for ongoing biological processes: "
            "'The ribosome reads...', 'Enzymes catalyze...'\n"
        )

        difficulty_fragment = {
            DifficultyEnum.beginner: (
                "- Avoid molecular detail; focus on cell and organism level.\n"
                "- Use analogies: 'The mitochondria acts like a battery...'\n"
                "- Introduce vocabulary with immediate simple definitions.\n"
            ),
            DifficultyEnum.intermediate: (
                "- Balance molecular and systems-level explanations.\n"
                "- Introduce key biochemical pathways without full mechanistic detail.\n"
            ),
            DifficultyEnum.advanced: (
                "- Include molecular mechanisms, gene regulation, and biochemical pathways.\n"
                "- Reference experimental evidence for key claims where appropriate.\n"
                "- Discuss evolutionary rationale for biological structures and processes.\n"
            ),
        }.get(difficulty, "")

        curriculum_fragment = {
            CurriculumEnum.IB: "- Reference IB Biology syllabus topics and HL extensions explicitly.\n",
            CurriculumEnum.Cambridge: "- Use Cambridge IGCSE Biology 0610 or A-Level Biology 9700 syllabus references.\n",
            CurriculumEnum.AP: "- Align with AP Biology curriculum frameworks (ENE, IST, EVO, SYI, etc.).\n",
            CurriculumEnum.general: "- Use standard biological terminology as per current scientific consensus.\n",
        }.get(curriculum, "")

        return base + difficulty_fragment + curriculum_fragment

    def get_fact_check_prompt_fragment(self) -> str:
        return (
            "Verify the following for every biology scene:\n"
            "1) Taxonomic classifications are current (check post-2020 reclassifications).\n"
            "2) Biological process sequences are in the correct canonical order "
            "(e.g., glycolysis → Krebs cycle → electron transport chain).\n"
            "3) Species names use correct binomial nomenclature.\n"
            "4) No Lamarckian evolutionary claims are made "
            "(evolution is by natural selection, not acquired characteristics).\n"
            "5) Cell biology facts reflect current consensus, not outdated textbook models "
            "(e.g., fluid mosaic model, not older lipid bilayer model alone).\n"
            "Flag any claim that contradicts post-2015 biological consensus."
  )

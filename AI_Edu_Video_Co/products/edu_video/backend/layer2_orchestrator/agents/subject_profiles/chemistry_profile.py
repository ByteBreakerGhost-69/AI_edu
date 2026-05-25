# products/edu_video/backend/layer2_orchestrator/agents/subject_profiles/chemistry_profile.py
"""Chemistry subject profile — reaction-centered, IUPAC-strict."""

from layer1_input.schemas import CurriculumEnum, DifficultyEnum, SubjectEnum
from layer2_orchestrator.agents.subject_profiles.base_profile import (
    BaseSubjectProfile,
    register_profile,
)

__all__ = ["ChemistryProfile"]


@register_profile(SubjectEnum.chemistry)
class ChemistryProfile(BaseSubjectProfile):
    """
    Profile for chemistry content.
    Prioritizes diagrams for molecular structures and reaction mechanisms.
    Enforces IUPAC naming, balanced equations, and oxidation state accuracy.
    """

    @property
    def subject(self) -> SubjectEnum:
        return SubjectEnum.chemistry

    @property
    def display_name(self) -> str:
        return "Chemistry"

    @property
    def renderer_preference(self) -> list[str]:
        return ["diagram", "lottie", "flux_sdxl"]

    @property
    def validation_rules(self) -> list[str]:
        return [
            "check_chemical_equation_balance",
            "check_oxidation_states",
            "check_electron_configuration",
            "check_iupac_naming",
            "check_stoichiometry",
        ]

    @property
    def visual_style(self) -> dict:
        return {
            "color_palette": ["#F59E0B", "#78350F", "#FEF3C7", "#1F2937"],
            "layout": "reaction_centered",
            "font_emphasis": "chemical_notation",
            "animation_speed": "moderate",
        }

    @property
    def scene_structure_template(self) -> list[dict]:
        return [
            {"scene_role": "hook", "content_focus": "real_world_chemistry_example", "suggested_duration_seconds": 30},
            {"scene_role": "concept_intro", "content_focus": "theory_or_principle", "suggested_duration_seconds": 45},
            {"scene_role": "molecular_visualization", "content_focus": "structure_or_reaction_mechanism", "suggested_duration_seconds": 60},
            {"scene_role": "equation_walkthrough", "content_focus": "balanced_reaction_steps", "suggested_duration_seconds": 60},
            {"scene_role": "lab_connection", "content_focus": "experimental_observation", "suggested_duration_seconds": 45},
            {"scene_role": "summary", "content_focus": "key_reactions_and_concepts", "suggested_duration_seconds": 30},
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
        return mapping.get(content_type, "diagram")

    def get_script_guidelines(
        self,
        difficulty: DifficultyEnum,
        curriculum: CurriculumEnum,
    ) -> str:
        base = (
            "You are narrating a chemistry lesson. Follow these guidelines:\n"
            "- Use IUPAC names alongside common names on first mention (e.g., 'ethanol, also called alcohol').\n"
            "- State whether each reaction is exothermic or endothermic when relevant.\n"
            "- Describe observable evidence: color changes, precipitate formation, gas evolution.\n"
            "- When balancing equations on screen, narrate each balancing step explicitly.\n"
            "- Connect molecular-level explanations to macroscopic observations.\n"
        )

        difficulty_fragment = {
            DifficultyEnum.beginner: (
                "- Avoid mechanism arrows; describe reactions as 'A reacts with B to form C'.\n"
                "- Use everyday analogies for chemical concepts (e.g., acids as sour substances).\n"
                "- Focus on observable phenomena rather than electron-level explanations.\n"
            ),
            DifficultyEnum.intermediate: (
                "- Introduce basic mechanism concepts (e.g., nucleophile, electrophile) with definitions.\n"
                "- Include both qualitative and quantitative (stoichiometric) treatments.\n"
            ),
            DifficultyEnum.advanced: (
                "- Use formal mechanism notation (curly arrows, transition states).\n"
                "- Discuss thermodynamic and kinetic factors (ΔG, activation energy).\n"
                "- Reference orbital theory where relevant (VSEPR, hybridization).\n"
            ),
        }.get(difficulty, "")

        curriculum_fragment = {
            CurriculumEnum.IB: "- Reference IB Chemistry data booklet and Topic numbers (e.g., Topic 4.1).\n",
            CurriculumEnum.Cambridge: "- Use Cambridge IGCSE Chemistry 0620 or A-Level Chemistry 9701 notation.\n",
            CurriculumEnum.AP: "- Align with AP Chemistry curriculum framework and Big Ideas.\n",
            CurriculumEnum.general: "- Use standard IUPAC notation and widely accepted chemistry conventions.\n",
        }.get(curriculum, "")

        return base + difficulty_fragment + curriculum_fragment

    def get_fact_check_prompt_fragment(self) -> str:
        return (
            "Verify the following for every chemistry scene:\n"
            "1) All chemical equations are balanced for both atoms and charge.\n"
            "2) Oxidation states are correctly assigned to each element.\n"
            "3) IUPAC nomenclature is correct and current.\n"
            "4) Stoichiometric ratios in calculations are accurate.\n"
            "5) No thermodynamically impossible reactions are presented "
            "(check ΔG or equilibrium direction where stated).\n"
            "Flag any unbalanced equation immediately."
    )

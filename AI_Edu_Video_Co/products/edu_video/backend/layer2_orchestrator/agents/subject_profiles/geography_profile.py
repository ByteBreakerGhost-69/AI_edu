# products/edu_video/backend/layer2_orchestrator/agents/subject_profiles/geography_profile.py
"""Geography subject profile — map-centered, current boundary-aware."""

from layer1_input.schemas import CurriculumEnum, DifficultyEnum, SubjectEnum
from layer2_orchestrator.agents.subject_profiles.base_profile import (
    BaseSubjectProfile,
    register_profile,
)

__all__ = ["GeographyProfile"]


@register_profile(SubjectEnum.geography)
class GeographyProfile(BaseSubjectProfile):
    """
    Profile for geography content.
    Prioritizes diagram renderer for maps and cross-sections,
    flux_sdxl for landscape and satellite imagery.
    """

    @property
    def subject(self) -> SubjectEnum:
        return SubjectEnum.geography

    @property
    def display_name(self) -> str:
        return "Geography"

    @property
    def renderer_preference(self) -> list[str]:
        return ["diagram", "flux_sdxl", "lottie"]

    @property
    def validation_rules(self) -> list[str]:
        return [
            "check_geographic_coordinates",
            "check_current_political_boundaries",
            "check_climate_data_accuracy",
            "check_demographic_statistics",
            "check_map_accuracy",
        ]

    @property
    def visual_style(self) -> dict:
        return {
            "color_palette": ["#0EA5E9", "#0C4A6E", "#E0F2FE", "#1F2937"],
            "layout": "map_centered",
            "font_emphasis": "geographic_labels",
            "animation_speed": "moderate",
        }

    @property
    def scene_structure_template(self) -> list[dict]:
        return [
            {"scene_role": "hook", "content_focus": "geographic_phenomenon_or_place", "suggested_duration_seconds": 30},
            {"scene_role": "location_context", "content_focus": "where_and_regional_setting", "suggested_duration_seconds": 45},
            {"scene_role": "physical_geography", "content_focus": "landforms_climate_ecosystem", "suggested_duration_seconds": 60},
            {"scene_role": "human_geography", "content_focus": "population_economy_culture", "suggested_duration_seconds": 60},
            {"scene_role": "geographic_issue", "content_focus": "environmental_or_developmental_challenge", "suggested_duration_seconds": 45},
            {"scene_role": "summary", "content_focus": "key_geographic_concepts", "suggested_duration_seconds": 30},
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
            "You are narrating a geography lesson. Follow these guidelines:\n"
            "- Always specify location in relation to known reference points "
            "(e.g., 'located in Southeast Asia, bordering the South China Sea').\n"
            "- Use current country names and borders; note if a name changed post-2010.\n"
            "- Clearly distinguish physical geography (landforms, climate) from human geography "
            "(population, economy, culture).\n"
            "- Reference data with approximate years: 'As of 2023, the population is...'\n"
            "- Explain geographic processes causally: 'Because warm air rises..., rainfall increases...'\n"
        )

        difficulty_fragment = {
            DifficultyEnum.beginner: (
                "- Focus on named places and physical features; avoid statistical analysis.\n"
                "- Use compass directions and relative location extensively.\n"
                "- Introduce one geographic concept per scene.\n"
            ),
            DifficultyEnum.intermediate: (
                "- Introduce both physical and human geographic dimensions of each topic.\n"
                "- Use case studies of specific countries or regions to illustrate concepts.\n"
            ),
            DifficultyEnum.advanced: (
                "- Engage with geographic theories (Demographic Transition Model, von Thünen, etc.).\n"
                "- Analyze spatial patterns using quantitative data.\n"
                "- Discuss geographic debates and contested interpretations.\n"
            ),
        }.get(difficulty, "")

        curriculum_fragment = {
            CurriculumEnum.IB: "- Reference IB Geography SL/HL optional themes and core units.\n",
            CurriculumEnum.Cambridge: "- Use Cambridge IGCSE Geography 0460 or A-Level Geography 9696 syllabus references.\n",
            CurriculumEnum.AP: "- Align with AP Human Geography or AP Environmental Science frameworks.\n",
            CurriculumEnum.general: "- Use standard geographic terminology and current political geography.\n",
        }.get(curriculum, "")

        return base + difficulty_fragment + curriculum_fragment

    def get_fact_check_prompt_fragment(self) -> str:
        return (
            "Verify the following for every geography scene:\n"
            "1) Country names, capitals, and political boundaries are current (post-2020 sources).\n"
            "2) Geographic coordinates and spatial locations are accurate.\n"
            "3) Climate and biome classifications match current scientific classification systems.\n"
            "4) All statistical data (population, GDP, area) cites an approximate reference year.\n"
            "5) Physical geographic processes are described correctly "
            "(plate tectonics, erosion cycles, hydrological cycle, etc.).\n"
            "Flag any country name or boundary that may have changed since 2010."
          )

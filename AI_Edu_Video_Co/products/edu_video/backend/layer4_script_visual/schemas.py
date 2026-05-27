# products/edu_video/backend/layer4_script_visual/schemas.py
"""
All Pydantic v2 schemas for Layer 4 (Script & Visual Generation).
No internal project imports beyond layer1 schemas — this is the base schema file.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from layer1_input.schemas import CurriculumEnum, DifficultyEnum, SubjectEnum

__all__ = [
    # Input schemas
    "SceneInput",
    "JobContext",
    # Intermediate schemas
    "AdaptedScene",
    "LocalizedScene",
    "RefinedScript",
    "TTSInstructions",
    # Output schemas
    "VisualSpec",
    "FinalScenePackage",
    "Layer4Result",
]


# --------------------------------------------------------------------------- #
# Input schemas (received from Layer 2 via video_worker)                      #
# --------------------------------------------------------------------------- #

class SceneInput(BaseModel):
    """One SceneData converted to Layer 4 input format."""
    model_config = ConfigDict(from_attributes=True)

    scene_index: int
    title: str
    narration_text: str
    visual_description: str
    renderer_type: str
    duration_seconds: float
    render_metadata: dict = Field(default_factory=dict)
    fact_checked: bool = False
    llm_cost_usd: float = 0.0


class JobContext(BaseModel):
    """Job-level metadata passed to all Layer 4 generators."""
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    user_id: str
    title: str
    subject: SubjectEnum
    curriculum: CurriculumEnum
    difficulty_level: DifficultyEnum
    language: str = "en"
    curriculum_standards: list[str] = Field(default_factory=list)
    learning_objectives: list[str] = Field(default_factory=list)
    total_scenes: int


# --------------------------------------------------------------------------- #
# Intermediate schemas (Layer 4 internal pipeline)                            #
# --------------------------------------------------------------------------- #

class AdaptedScene(BaseModel):
    """Output of DifficultyAdapter — vocabulary and complexity tuned."""
    model_config = ConfigDict(from_attributes=True)

    scene_index: int
    title: str
    narration_text: str
    visual_description: str
    renderer_type: str
    duration_seconds: float
    render_metadata: dict = Field(default_factory=dict)
    adaptation_notes: list[str] = Field(default_factory=list)
    readability_score: float = 0.0


class LocalizedScene(BaseModel):
    """Output of LanguageLocalizer — translated and culturally adapted."""
    model_config = ConfigDict(from_attributes=True)

    scene_index: int
    title: str
    narration_text: str
    visual_description: str
    renderer_type: str
    duration_seconds: float
    render_metadata: dict = Field(default_factory=dict)
    source_language: str = "en"
    target_language: str = "en"
    translation_notes: list[str] = Field(default_factory=list)
    untranslated_terms: list[str] = Field(default_factory=list)


class TTSInstructions(BaseModel):
    """Per-scene TTS delivery configuration."""
    speaking_rate: float = Field(default=1.0, ge=0.8, le=1.2)
    pitch: str = "medium"          # "low" | "medium" | "high"
    emphasis_words: list[str] = Field(default_factory=list)
    pause_after_sentences: list[int] = Field(default_factory=list)
    language_code: str = "en-US"   # BCP-47 TTS code


class RefinedScript(BaseModel):
    """Output of ScriptGenerator — final production-ready narration."""
    model_config = ConfigDict(from_attributes=True)

    scene_index: int
    title: str
    narration_text: str           # final polished narration (plain text)
    narration_ssml: str           # SSML-formatted for TTS
    hook_sentence: str            # first sentence — must be engaging
    key_terms: list[str] = Field(default_factory=list)
    estimated_word_count: int = 0
    estimated_duration_seconds: float = 0.0
    tts_instructions: TTSInstructions


# --------------------------------------------------------------------------- #
# Output schemas (consumed by Layer 5 Rendering)                              #
# --------------------------------------------------------------------------- #

class VisualSpec(BaseModel):
    """
    Renderer-ready visual specification for a single scene.
    Layer 5 consumes this directly — every field must be production-ready.
    """
    model_config = ConfigDict(from_attributes=True)

    renderer_type: str
    primary_content: str            # LaTeX / Mermaid diagram / code / image prompt
    secondary_content: Optional[str] = None
    color_palette: list[str] = Field(default_factory=list)
    dimensions: dict = Field(
        default_factory=lambda: {"width": 1920, "height": 1080}
    )
    animation_config: dict = Field(default_factory=dict)
    asset_references: list[str] = Field(default_factory=list)
    generation_prompt: Optional[str] = None   # for flux_sdxl / kling only


class FinalScenePackage(BaseModel):
    """
    PRIMARY OUTPUT of Layer 4.
    One package per scene — passed directly to Layer 5 rendering workers.
    """
    model_config = ConfigDict(from_attributes=True)

    scene_index: int
    title: str
    refined_script: RefinedScript
    visual_spec: VisualSpec
    renderer_type: str
    estimated_duration_seconds: float
    subject: str
    curriculum: str
    difficulty_level: str
    language: str
    metadata: dict = Field(default_factory=dict)


class Layer4Result(BaseModel):
    """
    Returned by each generator to the video_worker.
    Aggregates all scene packages and cost/error accounting.
    """
    job_id: str
    success: bool
    scene_packages: list[FinalScenePackage] = Field(default_factory=list)
    total_cost_usd: float = 0.0
    processing_time_seconds: float = 0.0
    errors: list[str] = Field(default_factory=list)

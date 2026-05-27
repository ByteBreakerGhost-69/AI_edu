# products/edu_video/backend/layer4_script_visual/script_generator.py
"""
ScriptGenerator: final LLM refinement pass before TTS.
Polishes narration for natural spoken delivery, generates SSML markup,
extracts key terms, and produces precise TTS instructions.
"""

import asyncio
import re

import structlog

from core.llm import llm_factory
from core.utils import safe_json_loads
from layer4_script_visual.difficulty_adapter import (
    _call_llm_json,
    _count_syllables,
    _estimate_duration,
)
from layer4_script_visual.language_localizer import (
    SUPPORTED_LANGUAGES,
    LanguageLocalizer,
)
from layer4_script_visual.schemas import (
    JobContext,
    LocalizedScene,
    RefinedScript,
    TTSInstructions,
)

__all__ = ["ScriptGenerator", "script_generator"]

logger = structlog.get_logger(__name__)

_REFINE_PROMPT_TOKENS = 500
_REFINE_COMPLETION_TOKENS = 400
_MAX_PARALLEL = 3

# --------------------------------------------------------------------------- #
# Configuration                                                                #
# --------------------------------------------------------------------------- #

SPOKEN_REPLACEMENTS: dict[str, str] = {
    "e.g.": "for example",
    "i.e.": "that is",
    "etc.": "and so on",
    "vs.": "versus",
    "≈":   "is approximately",
    "≠":   "is not equal to",
    "≤":   "is less than or equal to",
    "≥":   "is greater than or equal to",
    "∴":   "therefore",
    "∵":   "because",
    "→":   "which gives us",
    "⟹":  "which implies",
    "∈":   "is an element of",
    "∀":   "for all",
    "∃":   "there exists",
    "∞":   "infinity",
    "²":   " squared",
    "³":   " cubed",
    "√":   "the square root of",
    "±":   "plus or minus",
    "∑":   "the sum of",
    "∏":   "the product of",
    "∂":   "the partial derivative of",
    "∇":   "the gradient of",
}

_SPEAKING_RATE_BY_DIFFICULTY = {
    "beginner":     0.90,   # slightly slower for beginners
    "intermediate": 1.00,
    "advanced":     1.05,   # slightly faster — audience can keep up
}

_PITCH_BY_SCENE_ROLE = {
    "hook":          "high",
    "summary":       "medium",
    "default":       "medium",
}


# --------------------------------------------------------------------------- #
# ScriptGenerator                                                              #
# --------------------------------------------------------------------------- #

class ScriptGenerator:
    """
    Final script refinement pass before TTS rendering.
    Produces SSML-annotated narration ready for ElevenLabs or Google TTS.
    """

    def __init__(self) -> None:
        self.llm = llm_factory.get_llm().with_fallbacks(
            [llm_factory.get_llm("grok")]
        )
        self._localizer = LanguageLocalizer()
        self.log = structlog.get_logger(__name__)

    async def generate(
        self,
        scenes: list[LocalizedScene],
        job_context: JobContext,
    ) -> list[RefinedScript]:
        """
        Generate final refined scripts for all scenes concurrently.
        Returns RefinedScript list sorted by scene_index.
        """
        log = self.log.bind(
            job_id=job_context.job_id,
            subject=job_context.subject,
            language=job_context.language,
            scene_count=len(scenes),
        )
        log.info("script_generator.started")

        semaphore = asyncio.Semaphore(_MAX_PARALLEL)

        async def _refine_one(scene: LocalizedScene) -> RefinedScript:
            async with semaphore:
                return await self._refine_scene_script(scene, job_context)

        results = await asyncio.gather(
            *[_refine_one(s) for s in scenes],
            return_exceptions=True,
        )

        refined: list[RefinedScript] = []
        for scene, result in zip(scenes, results):
            if isinstance(result, Exception):
                log.error(
                    "script_generator.scene_failed",
                    scene_index=scene.scene_index,
                    error=str(result),
                )
                refined.append(_localized_to_fallback_script(scene, job_context))
            else:
                refined.append(result)

        refined.sort(key=lambda s: s.scene_index)
        log.info("script_generator.completed", refined_count=len(refined))
        return refined

    async def _refine_scene_script(
        self,
        scene: LocalizedScene,
        job_context: JobContext,
    ) -> RefinedScript:
        """
        Two-stage refinement for a single scene:
          1. Rule-based pre-processing (spoken form replacements, markdown strip)
          2. LLM polish + SSML generation
        """
        # ---- Stage 1: Rule-based pre-processing ------------------------- #
        text = scene.narration_text
        for written, spoken in SPOKEN_REPLACEMENTS.items():
            text = text.replace(written, spoken)

        # Remove markdown formatting
        text = re.sub(r"[*_#`]", "", text)
        # Collapse whitespace
        text = " ".join(text.split())

        tts_lang = self._localizer.get_tts_language_code(job_context.language)
        speaking_rate = _SPEAKING_RATE_BY_DIFFICULTY.get(
            job_context.difficulty_level.value, 1.0
        )

        # ---- Stage 2: LLM polish + SSML --------------------------------- #
        system_prompt = _build_script_system_prompt(job_context, tts_lang)
        user_prompt = _build_script_user_prompt(scene, text, job_context)

        result = await _call_llm_json(
            llm=self.llm,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            expected_keys=[
                "polished_narration",
                "narration_ssml",
                "hook_sentence",
                "key_terms",
                "emphasis_words",
                "pause_after_sentences",
            ],
            log=self.log.bind(
                job_id=job_context.job_id,
                scene_index=scene.scene_index,
            ),
        )

        polished = str(result.get("polished_narration") or text).strip()
        ssml = str(result.get("narration_ssml") or _basic_ssml(polished)).strip()
        hook = str(result.get("hook_sentence") or _extract_hook(polished)).strip()
        key_terms = _extract_string_list(result.get("key_terms"))[:5]
        emphasis_words = _extract_string_list(result.get("emphasis_words"))
        pause_indices = _extract_int_list(result.get("pause_after_sentences"))

        word_count = len(polished.split())
        duration = _estimate_duration(polished)

        tts_instructions = TTSInstructions(
            speaking_rate=speaking_rate,
            pitch=_PITCH_BY_SCENE_ROLE.get("default", "medium"),
            emphasis_words=emphasis_words,
            pause_after_sentences=pause_indices,
            language_code=tts_lang,
        )

        return RefinedScript(
            scene_index=scene.scene_index,
            title=scene.title,
            narration_text=polished,
            narration_ssml=ssml,
            hook_sentence=hook,
            key_terms=key_terms,
            estimated_word_count=word_count,
            estimated_duration_seconds=duration,
            tts_instructions=tts_instructions,
        )


# --------------------------------------------------------------------------- #
# Prompt builders                                                              #
# --------------------------------------------------------------------------- #

def _build_script_system_prompt(job_context: JobContext, tts_lang: str) -> str:
    return (
        "You are an expert educational scriptwriter specialising in "
        f"{job_context.subject.value} for TTS (text-to-speech) delivery.\n\n"
        "=== YOUR TASK ===\n"
        "Polish this narration for natural spoken delivery and add SSML markup.\n\n"
        "=== NARRATION RULES ===\n"
        "- Write for the ear, not the eye: avoid lists, use flowing sentences.\n"
        "- Start with the hook sentence — it must be engaging and scene-specific.\n"
        "- Remove any remaining written abbreviations.\n"
        "- Vary sentence length for natural rhythm.\n"
        "- Use active voice wherever possible.\n"
        f"- Difficulty: {job_context.difficulty_level.value} level.\n\n"
        "=== SSML RULES ===\n"
        f'- Wrap the full narration in <speak> tags.\n'
        '- After formula statements: <break time="800ms"/>\n'
        '- After definitions: <break time="600ms"/>\n'
        '- After step transitions ("Next,", "Now,"): <break time="400ms"/>\n'
        '- Key terms: <emphasis level="moderate">term</emphasis>\n'
        '- Formulas/equations: <prosody rate="slow">formula text</prosody>\n'
        f'- Language code: {tts_lang}\n\n'
        "=== OUTPUT FORMAT ===\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        '  "polished_narration": "final spoken narration (plain text)",\n'
        '  "narration_ssml": "<speak>SSML version</speak>",\n'
        '  "hook_sentence": "first sentence — most engaging",\n'
        '  "key_terms": ["term1", "term2", "term3"],\n'
        '  "emphasis_words": ["word1", "word2"],\n'
        '  "pause_after_sentences": [0, 2, 4]\n'
        "}"
    )


def _build_script_user_prompt(
    scene: LocalizedScene,
    preprocessed_text: str,
    job_context: JobContext,
) -> str:
    return (
        f"Scene {scene.scene_index + 1} of {job_context.total_scenes}: "
        f"'{scene.title}'\n\n"
        f"Pre-processed narration ({len(preprocessed_text.split())} words):\n"
        f"{preprocessed_text}\n\n"
        f"Learning objectives for this video:\n"
        + "\n".join(f"  - {o}" for o in job_context.learning_objectives[:3])
    )


# --------------------------------------------------------------------------- #
# SSML helpers                                                                 #
# --------------------------------------------------------------------------- #

def _basic_ssml(text: str) -> str:
    """Minimal SSML fallback when LLM doesn't return SSML."""
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<speak>{escaped}</speak>"


def _extract_hook(text: str) -> str:
    """Extract first sentence as hook fallback."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return sentences[0] if sentences else text[:100]


# --------------------------------------------------------------------------- #
# Fallback                                                                     #
# --------------------------------------------------------------------------- #

def _localized_to_fallback_script(
    scene: LocalizedScene,
    job_context: JobContext,
) -> RefinedScript:
    """Return minimal RefinedScript when LLM refinement fails entirely."""
    tts_lang = SUPPORTED_LANGUAGES.get(
        job_context.language, SUPPORTED_LANGUAGES["en"]
    )["tts_code"]

    text = scene.narration_text
    return RefinedScript(
        scene_index=scene.scene_index,
        title=scene.title,
        narration_text=text,
        narration_ssml=_basic_ssml(text),
        hook_sentence=_extract_hook(text),
        key_terms=[],
        estimated_word_count=len(text.split()),
        estimated_duration_seconds=_estimate_duration(text),
        tts_instructions=TTSInstructions(
            speaking_rate=1.0,
            pitch="medium",
            emphasis_words=[],
            pause_after_sentences=[],
            language_code=tts_lang,
        ),
    )


# --------------------------------------------------------------------------- #
# List coercers                                                                #
# --------------------------------------------------------------------------- #

def _extract_string_list(value) -> list[str]:
    if not value or not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if item and str(item).strip()]


def _extract_int_list(value) -> list[int]:
    if not value or not isinstance(value, list):
        return []
    result = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            pass
    return result


script_generator = ScriptGenerator()

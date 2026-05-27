# products/edu_video/backend/layer4_script_visual/difficulty_adapter.py
"""
DifficultyAdapter: fine-tunes Layer 2 draft narration to match the exact
difficulty level. Combines rule-based vocabulary substitution with LLM
refinement. Preserves all factual content — only changes explanation style.
"""

import asyncio
import re
from statistics import mean

import structlog

from core.llm import llm_factory
from core.utils import safe_json_loads, utcnow
from layer1_input.schemas import DifficultyEnum, SubjectEnum
from layer4_script_visual.schemas import AdaptedScene, SceneInput

__all__ = ["DifficultyAdapter", "difficulty_adapter"]

logger = structlog.get_logger(__name__)

_ADAPT_PROMPT_TOKENS = 400
_ADAPT_COMPLETION_TOKENS = 300
_CLAUDE_INPUT_COST = 0.000003
_CLAUDE_OUTPUT_COST = 0.000015
_MAX_PARALLEL = 4
_MAX_RETRIES = 2

# --------------------------------------------------------------------------- #
# Configuration                                                                #
# --------------------------------------------------------------------------- #

DIFFICULTY_PROFILES: dict[DifficultyEnum, dict] = {
    DifficultyEnum.beginner: {
        "max_sentence_words": 15,
        "vocabulary_level": "elementary",
        "explanation_style": "analogies_first",
        "formula_handling": "words_before_symbols",
        "assumed_knowledge": "none — define everything",
        "tone": "encouraging",
        "max_technical_terms_per_scene": 3,
        "requires_real_world_hook": True,
    },
    DifficultyEnum.intermediate: {
        "max_sentence_words": 22,
        "vocabulary_level": "academic",
        "explanation_style": "concept_then_example",
        "formula_handling": "symbol_with_brief_explanation",
        "assumed_knowledge": "prerequisites listed in the video description",
        "tone": "professional",
        "max_technical_terms_per_scene": 7,
        "requires_real_world_hook": False,
    },
    DifficultyEnum.advanced: {
        "max_sentence_words": 30,
        "vocabulary_level": "expert",
        "explanation_style": "direct_formal",
        "formula_handling": "symbols_primary",
        "assumed_knowledge": "all listed prerequisites",
        "tone": "academic",
        "max_technical_terms_per_scene": "unlimited",
        "requires_real_world_hook": False,
    },
}

VOCABULARY_SUBSTITUTIONS: dict[str, str] = {
    "demonstrate": "show",
    "utilize": "use",
    "commence": "start",
    "subsequently": "then",
    "aforementioned": "the above",
    "approximately": "about",
    "magnitude": "size",
    "perpendicular": "at a right angle (90°)",
    "proportional": "grows at the same rate as",
    "derivative": "rate of change",
    "integral": "accumulated total",
    "hypothesis": "educated guess",
    "phenomenon": "event or observation",
    "coefficient": "the number in front of a variable",
    "asymptote": "a line the graph gets very close to but never touches",
    "equidistant": "the same distance from",
    "perpendicular": "at a right angle to",
    "converge": "come together",
    "diverge": "move apart",
    "negate": "cancel out",
}


# --------------------------------------------------------------------------- #
# DifficultyAdapter                                                            #
# --------------------------------------------------------------------------- #

class DifficultyAdapter:
    """
    Adapts draft narration from Layer 2 for the target difficulty level.
    Runs rule-based substitution first (free), then LLM refinement.
    Processes scenes concurrently with a semaphore to limit LLM pressure.
    """

    def __init__(self) -> None:
        self.llm = llm_factory.get_llm().with_fallbacks(
            [llm_factory.get_llm("grok")]
        )
        self.log = structlog.get_logger(__name__)

    async def adapt(
        self,
        scenes: list[SceneInput],
        difficulty: DifficultyEnum,
        subject: SubjectEnum,
        job_id: str,
    ) -> list[AdaptedScene]:
        """
        Adapt all scenes to the target difficulty concurrently.
        Returns adapted scenes in original scene_index order.
        """
        log = self.log.bind(
            job_id=job_id,
            difficulty=difficulty,
            subject=subject,
            scene_count=len(scenes),
        )
        log.info("difficulty_adapter.started")

        semaphore = asyncio.Semaphore(_MAX_PARALLEL)

        async def _adapt_one(scene: SceneInput) -> AdaptedScene:
            async with semaphore:
                return await self._adapt_scene(scene, difficulty, subject, job_id)

        results = await asyncio.gather(
            *[_adapt_one(s) for s in scenes],
            return_exceptions=True,
        )

        adapted: list[AdaptedScene] = []
        for scene, result in zip(scenes, results):
            if isinstance(result, Exception):
                log.error(
                    "difficulty_adapter.scene_failed",
                    scene_index=scene.scene_index,
                    error=str(result),
                )
                # Fallback: wrap original as AdaptedScene unchanged
                adapted.append(_scene_input_to_adapted(scene, ["adaptation_failed_using_original"]))
            else:
                adapted.append(result)

        adapted.sort(key=lambda s: s.scene_index)
        log.info("difficulty_adapter.completed", adapted_count=len(adapted))
        return adapted

    async def _adapt_scene(
        self,
        scene: SceneInput,
        difficulty: DifficultyEnum,
        subject: SubjectEnum,
        job_id: str,
    ) -> AdaptedScene:
        """
        Two-stage adaptation for a single scene:
          1. Rule-based vocabulary substitution (free, fast)
          2. LLM refinement for tone, sentence structure, style
        """
        profile = DIFFICULTY_PROFILES[difficulty]

        # ---- Stage 1: Rule-based ---------------------------------------- #
        text = scene.narration_text
        applied_rules: list[str] = []

        if difficulty == DifficultyEnum.beginner:
            original_text = text
            for advanced, simple in VOCABULARY_SUBSTITUTIONS.items():
                text = re.sub(
                    r"\b" + re.escape(advanced) + r"\b",
                    simple,
                    text,
                    flags=re.IGNORECASE,
                )
            if text != original_text:
                applied_rules.append("Applied vocabulary simplification substitutions.")
            text = _enforce_sentence_length(text, profile["max_sentence_words"])
            if text != scene.narration_text:
                applied_rules.append("Split long sentences for beginner readability.")

        # ---- Stage 2: LLM refinement ------------------------------------ #
        hook_instruction = (
            "- MUST start with a relatable real-world analogy or hook example.\n"
            if profile["requires_real_world_hook"]
            else ""
        )

        system_prompt = (
            f"You are an expert educational content adaptor specialising in {subject.value}.\n"
            f"Rewrite this narration for {difficulty.value}-level students.\n\n"
            f"=== ADAPTATION RULES FOR {difficulty.value.upper()} ===\n"
            f"- Vocabulary level: {profile['vocabulary_level']}\n"
            f"- Explanation style: {profile['explanation_style']}\n"
            f"- Formula handling: {profile['formula_handling']}\n"
            f"- Tone: {profile['tone']}\n"
            f"- Max technical terms per scene: {profile['max_technical_terms_per_scene']}\n"
            f"- Assumed prior knowledge: {profile['assumed_knowledge']}\n"
            f"{hook_instruction}"
            "\n=== NON-NEGOTIABLE CONSTRAINTS ===\n"
            "- Preserve ALL factual content. Only change HOW it is explained.\n"
            "- Keep the same key concepts and learning objectives.\n"
            "- Target length: within 20% of original word count.\n"
            "- Do NOT add new facts not in the original.\n\n"
            "Return ONLY valid JSON:\n"
            "{\n"
            '  "adapted_narration": "rewritten narration text",\n'
            '  "adaptation_notes": ["change description and reason", ...],\n'
            '  "terms_simplified": ["term1", "term2"]\n'
            "}"
        )

        user_prompt = (
            f"Scene title: {scene.title}\n"
            f"Scene position: {scene.scene_index + 1} of video\n"
            f"Original narration ({len(scene.narration_text.split())} words):\n\n"
            f"{text}"
        )

        result = await _call_llm_json(
            llm=self.llm,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            expected_keys=["adapted_narration", "adaptation_notes"],
            log=self.log.bind(job_id=job_id, scene_index=scene.scene_index),
        )

        adapted_narration = str(result.get("adapted_narration") or text).strip()
        llm_notes = result.get("adaptation_notes") or []
        if not isinstance(llm_notes, list):
            llm_notes = []

        all_notes = applied_rules + [str(n) for n in llm_notes]
        readability = _flesch_kincaid_grade(adapted_narration)

        return AdaptedScene(
            scene_index=scene.scene_index,
            title=scene.title,
            narration_text=adapted_narration,
            visual_description=scene.visual_description,
            renderer_type=scene.renderer_type,
            duration_seconds=_estimate_duration(adapted_narration),
            render_metadata=scene.render_metadata,
            adaptation_notes=all_notes,
            readability_score=round(readability, 2),
        )


# --------------------------------------------------------------------------- #
# Pure helpers                                                                 #
# --------------------------------------------------------------------------- #

def _enforce_sentence_length(text: str, max_words: int) -> str:
    """
    Split sentences exceeding max_words at natural conjunction points.
    Only splits at: ', and', ', but', ', so', ', because', ', which'.
    Preserves sentences already within the limit.
    """
    split_patterns = [
        r",\s+and\b",
        r",\s+but\b",
        r",\s+so\b",
        r",\s+because\b",
        r",\s+which\b",
    ]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    result: list[str] = []

    for sentence in sentences:
        words = sentence.split()
        if len(words) <= max_words:
            result.append(sentence)
            continue

        # Try splitting at first matching conjunction
        split_sentence = sentence
        for pattern in split_patterns:
            parts = re.split(pattern, split_sentence, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2 and len(parts[0].split()) <= max_words:
                # Capitalise the second part
                second = parts[1].strip()
                second = second[0].upper() + second[1:] if second else second
                split_sentence = parts[0].strip() + ". " + second
                break

        result.append(split_sentence)

    return " ".join(result)


def _flesch_kincaid_grade(text: str) -> float:
    """
    Standard Flesch-Kincaid Grade Level formula.
    FK = 0.39 * (words/sentences) + 11.8 * (syllables/words) - 15.59
    """
    words = text.split()
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]

    if not words or not sentences:
        return 0.0

    syllables = sum(_count_syllables(w) for w in words)
    n_words = max(len(words), 1)
    n_sentences = max(len(sentences), 1)

    return round(
        0.39 * (n_words / n_sentences) + 11.8 * (syllables / n_words) - 15.59,
        2,
    )


def _count_syllables(word: str) -> int:
    vowels = "aeiouAEIOU"
    count = 0
    prev_vowel = False
    for char in word.strip(".,!?;:'\"()[]"):
        is_vowel = char in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    return max(1, count)


def _estimate_duration(text: str, wpm: float = 130.0) -> float:
    """Estimate audio duration from word count at 130 wpm + 5s buffer."""
    words = len(text.split())
    return round((words / wpm) * 60 + 5.0, 1)


def _scene_input_to_adapted(
    scene: SceneInput,
    notes: list[str],
) -> AdaptedScene:
    """Wrap an unchanged SceneInput as an AdaptedScene (fallback path)."""
    return AdaptedScene(
        scene_index=scene.scene_index,
        title=scene.title,
        narration_text=scene.narration_text,
        visual_description=scene.visual_description,
        renderer_type=scene.renderer_type,
        duration_seconds=scene.duration_seconds,
        render_metadata=scene.render_metadata,
        adaptation_notes=notes,
        readability_score=_flesch_kincaid_grade(scene.narration_text),
    )


async def _call_llm_json(
    llm,
    system_prompt: str,
    user_prompt: str,
    expected_keys: list[str],
    log,
    max_retries: int = _MAX_RETRIES,
) -> dict:
    """
    Shared LLM JSON caller for Layer 4 modules.
    Returns {key: None} for all expected_keys on total failure.
    """
    from langchain_core.messages import HumanMessage, SystemMessage  # noqa: PLC0415

    full_system = (
        system_prompt.rstrip()
        + "\n\nCRITICAL: Respond ONLY with valid JSON. "
        "No markdown fences. No prose. First character must be '{'."
    )
    current_user = user_prompt

    for attempt in range(1, max_retries + 1):
        try:
            response = await llm.ainvoke([
                SystemMessage(content=full_system),
                HumanMessage(content=current_user),
            ])
            raw = str(response.content).strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            parsed = safe_json_loads(raw)
            if parsed is not None:
                return parsed

            error_feedback = f"Response was not valid JSON. First 150 chars: {raw[:150]!r}"
            log.warning("layer4.llm_json_parse_failed", attempt=attempt)

        except Exception as exc:
            error_feedback = str(exc)[:200]
            log.error("layer4.llm_call_failed", attempt=attempt, error=error_feedback)

        if attempt < max_retries:
            current_user = (
                user_prompt
                + f"\n\n[PREVIOUS ATTEMPT FAILED: {error_feedback}]\n"
                "Return ONLY a valid JSON object starting with '{'."
            )

    return {k: None for k in expected_keys}


difficulty_adapter = DifficultyAdapter()

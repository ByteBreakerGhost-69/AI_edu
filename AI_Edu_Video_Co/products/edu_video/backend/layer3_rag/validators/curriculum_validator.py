# products/edu_video/backend/layer3_rag/validators/curriculum_validator.py
"""
CurriculumValidator: checks vocabulary level, curriculum standard alignment,
and readability calibration for the target difficulty.
"""

import json
from statistics import mean

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from core.llm import llm_factory
from core.utils import safe_json_loads
from layer1_input.schemas import CurriculumEnum, DifficultyEnum
from layer3_rag.validators.base_validator import (
    BaseValidator,
    ValidationIssue,
    ValidationReport,
    register_validator,
)

__all__ = ["CurriculumValidator"]

logger = structlog.get_logger(__name__)

_ADVANCED_VOCABULARY = [
    "epistemology", "stochastic", "heuristic", "asymptotic",
    "phenomenological", "hermeneutic", "ontological", "teleological",
    "axiomatically", "solipsistic",
]

_DIFFICULTY_THRESHOLDS: dict[str, dict[str, float]] = {
    "beginner":     {"max_avg_word_len": 5.5, "max_avg_sentence_len": 15.0},
    "intermediate": {"max_avg_word_len": 7.0, "max_avg_sentence_len": 22.0},
    "advanced":     {"max_avg_word_len": 9.0, "max_avg_sentence_len": 30.0},
}

_COVERAGE_THRESHOLD = 60  # % of standards that should be covered


@register_validator("curriculum")
class CurriculumValidator(BaseValidator):
    """
    Validates content against curriculum standards and difficulty calibration.
    Mix of rule-based (vocabulary, readability) and LLM (standard alignment).
    """

    @property
    def validator_name(self) -> str:
        return "curriculum_validator"

    async def validate(
        self,
        content: str,
        context: dict,
    ) -> ValidationReport:
        location = f"scene_{context.get('scene_index', 0)}.narration_text"
        difficulty = context.get("difficulty_level", "intermediate")
        issues: list[ValidationIssue] = []

        try:
            curriculum_str = context.get("curriculum", "general")
            try:
                curriculum = CurriculumEnum(curriculum_str)
            except ValueError:
                curriculum = CurriculumEnum.general

            # ---- Check 1: Advanced vocabulary at beginner level --------- #
            if difficulty == "beginner":
                for term in _ADVANCED_VOCABULARY:
                    if term in content.lower():
                        issues.append(self._warning(
                            code="advanced_vocabulary_beginner",
                            message=f"Advanced term '{term}' found in beginner-level content.",
                            location=location,
                            suggestion=f"Replace '{term}' with simpler terminology.",
                        ))

            # ---- Check 2: Curriculum standard coverage (LLM) ------------ #
            standards = context.get("curriculum_standards", [])
            if standards and curriculum != CurriculumEnum.general:
                coverage_issues = await self._check_standard_coverage(
                    content, standards, curriculum, difficulty, location
                )
                issues.extend(coverage_issues)

            # ---- Check 3: Readability / difficulty calibration ----------- #
            issues.extend(self._check_difficulty_calibration(
                content, difficulty, location
            ))

        except Exception as exc:
            logger.error("curriculum_validator.crash", error=str(exc))
            return self._crash_report(str(exc))

        return self._make_report(issues, confidence=0.8)

    async def _check_standard_coverage(
        self,
        content: str,
        standards: list[str],
        curriculum: CurriculumEnum,
        difficulty: str,
        location: str,
    ) -> list[ValidationIssue]:
        """LLM-based check: does content cover the stated curriculum standards?"""
        issues = []
        system = (
            f"You are a {curriculum.value} curriculum expert. "
            "Assess whether the educational content covers the stated learning standards. "
            "Respond ONLY as valid JSON: "
            '{"aligned": true, "coverage_percentage": 80, '
            '"missing_standards": [], "off_curriculum_content": []}'
        )
        user = (
            f"Learning standards to cover:\n{json.dumps(standards)}\n\n"
            f"Educational content:\n{content[:800]}"
        )

        try:
            llm = llm_factory.get_llm()
            response = await llm.ainvoke([
                SystemMessage(content=system),
                HumanMessage(content=user),
            ])
            raw = str(response.content).strip()
            parsed = safe_json_loads(raw)
            if parsed is None:
                cleaned = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                parsed = safe_json_loads(cleaned)

            if not parsed:
                return []

            coverage = int(parsed.get("coverage_percentage", 100))
            missing = parsed.get("missing_standards", [])

            if coverage < _COVERAGE_THRESHOLD:
                missing_preview = ", ".join(str(m) for m in missing[:3])
                issues.append(self._warning(
                    code="low_curriculum_coverage",
                    message=(
                        f"Content covers approximately {coverage}% of the stated "
                        f"curriculum standards."
                    ),
                    location=location,
                    suggestion=(
                        f"Address missing standards: {missing_preview}"
                        if missing_preview
                        else "Review content against all listed standards."
                    ),
                ))

        except Exception as exc:
            logger.warning("curriculum_validator.llm_coverage_check_failed", error=str(exc))

        return issues

    def _check_difficulty_calibration(
        self,
        content: str,
        difficulty: str,
        location: str,
    ) -> list[ValidationIssue]:
        """Rule-based readability check using average word and sentence length."""
        issues = []
        words = content.split()
        if not words:
            return []

        sentences = [s.strip() for s in content.split(".") if s.strip()]
        avg_word_len = mean(len(w.strip(".,!?;:")) for w in words)
        avg_sentence_len = mean(len(s.split()) for s in sentences) if sentences else 0

        thresholds = _DIFFICULTY_THRESHOLDS.get(difficulty, _DIFFICULTY_THRESHOLDS["intermediate"])

        if avg_word_len > thresholds["max_avg_word_len"]:
            issues.append(self._info(
                code="complexity_above_level",
                message=(
                    f"Average word length {avg_word_len:.1f} chars exceeds "
                    f"{difficulty} threshold ({thresholds['max_avg_word_len']})."
                ),
                location=location,
                suggestion="Consider simpler vocabulary for this difficulty level.",
            ))

        if avg_sentence_len > thresholds["max_avg_sentence_len"]:
            issues.append(self._info(
                code="sentence_length_above_level",
                message=(
                    f"Average sentence length {avg_sentence_len:.1f} words exceeds "
                    f"{difficulty} threshold ({thresholds['max_avg_sentence_len']})."
                ),
                location=location,
                suggestion="Break longer sentences into shorter ones.",
            ))

        return issues

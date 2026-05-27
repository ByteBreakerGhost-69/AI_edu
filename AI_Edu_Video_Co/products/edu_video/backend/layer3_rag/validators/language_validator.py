# products/edu_video/backend/layer3_rag/validators/language_validator.py
"""
LanguageValidator: readability, passive voice, vocabulary repetition,
and sentence fragment detection for educational narration text.
"""

import re
from collections import Counter

import structlog

from layer3_rag.validators.base_validator import (
    BaseValidator,
    ValidationIssue,
    ValidationReport,
    register_validator,
)

__all__ = ["LanguageValidator"]

logger = structlog.get_logger(__name__)

_PASSIVE_PATTERN = re.compile(
    r"\b(is|are|was|were|be|been|being)\s+\w+ed\b",
    re.IGNORECASE,
)
_PASSIVE_RATIO_THRESHOLD = 0.15
_REPETITION_COUNT_THRESHOLD = 4
_FRAGMENT_MAX_WORDS = 3

_STOP_WORDS: frozenset[str] = frozenset({
    "the","a","an","is","are","and","or","in","of","to","it",
    "this","that","was","for","on","with","as","at","by","from",
    "be","been","but","not","so","if","we","they","he","she","you",
    "can","will","has","have","had","do","did","does","its","our",
})

_FK_EXPECTED_GRADE: dict[str, tuple[int, int]] = {
    "beginner":     (4, 8),
    "intermediate": (8, 12),
    "advanced":     (12, 16),
}


@register_validator("language")
class LanguageValidator(BaseValidator):
    """
    Validates educational narration text for readability, passive voice,
    vocabulary repetition, and sentence fragments.
    English-only for readability and passive checks.
    """

    @property
    def validator_name(self) -> str:
        return "language_validator"

    async def validate(
        self,
        content: str,
        context: dict,
    ) -> ValidationReport:
        location = f"scene_{context.get('scene_index', 0)}.narration_text"
        language = context.get("language", "en")
        difficulty = context.get("difficulty_level", "intermediate")
        issues: list[ValidationIssue] = []

        try:
            if language == "en":
                issues.extend(self._check_readability(content, difficulty, location))
                issues.extend(self._check_passive_voice(content, location))
                issues.extend(self._check_sentence_fragments(content, location))

            issues.extend(self._check_repetitive_vocabulary(content, location))

        except Exception as exc:
            logger.error("language_validator.crash", error=str(exc))
            return self._crash_report(str(exc))

        return self._make_report(issues, confidence=0.80)

    def _check_readability(
        self,
        content: str,
        difficulty: str,
        location: str,
    ) -> list[ValidationIssue]:
        """Flesch-Kincaid Grade Level check."""
        words = content.split()
        sentences = [s.strip() for s in content.split(".") if s.strip()]

        if not words or not sentences:
            return []

        syllables = sum(_count_syllables(w) for w in words)
        n_words = max(len(words), 1)
        n_sentences = max(len(sentences), 1)

        fk_grade = (
            0.39 * (n_words / n_sentences)
            + 11.8 * (syllables / n_words)
            - 15.59
        )

        min_g, max_g = _FK_EXPECTED_GRADE.get(difficulty, (8, 12))
        issues = []

        if fk_grade < min_g:
            issues.append(self._info(
                code="content_below_level",
                message=(
                    f"Flesch-Kincaid grade {fk_grade:.1f} is below the expected "
                    f"range ({min_g}–{max_g}) for {difficulty} level."
                ),
                location=location,
                suggestion="Consider more subject-specific vocabulary to match the difficulty level.",
            ))
        elif fk_grade > max_g:
            issues.append(self._warning(
                code="content_above_level",
                message=(
                    f"Flesch-Kincaid grade {fk_grade:.1f} exceeds the expected "
                    f"range ({min_g}–{max_g}) for {difficulty} level."
                ),
                location=location,
                suggestion="Simplify sentence structure or vocabulary to match the difficulty level.",
            ))

        return issues

    def _check_passive_voice(
        self,
        content: str,
        location: str,
    ) -> list[ValidationIssue]:
        """Flag excessive passive voice usage (>15% of words)."""
        passive_count = len(_PASSIVE_PATTERN.findall(content))
        word_count = max(len(content.split()), 1)
        ratio = passive_count / word_count

        if ratio > _PASSIVE_RATIO_THRESHOLD:
            return [self._info(
                code="excessive_passive_voice",
                message=(
                    f"Passive voice constructions detected in {ratio:.0%} of words "
                    f"({passive_count} instances). Educational narration is clearer in active voice."
                ),
                location=location,
                suggestion=(
                    "Rewrite passive constructions as active: "
                    "'The formula is used' → 'We use the formula'."
                ),
            )]
        return []

    def _check_repetitive_vocabulary(
        self,
        content: str,
        location: str,
    ) -> list[ValidationIssue]:
        """Flag non-stop-words used more than _REPETITION_COUNT_THRESHOLD times."""
        words = [
            w.lower().strip(".,!?;:'\"()[]") for w in content.split()
        ]
        freq = Counter(w for w in words if w not in _STOP_WORDS and len(w) > 3)
        issues = []

        for word, count in freq.items():
            if count > _REPETITION_COUNT_THRESHOLD:
                issues.append(self._info(
                    code="repetitive_vocabulary",
                    message=(
                        f"'{word}' appears {count} times. "
                        "Repetition may reduce engagement."
                    ),
                    location=location,
                    suggestion=f"Consider synonyms or pronouns to vary '{word}'.",
                ))

        return issues

    def _check_sentence_fragments(
        self,
        content: str,
        location: str,
    ) -> list[ValidationIssue]:
        """Flag very short sentence-like units that may be fragments."""
        sentences = content.split(".")
        issues = []

        for i, sent in enumerate(sentences):
            words = sent.strip().split()
            if 1 <= len(words) <= _FRAGMENT_MAX_WORDS:
                has_verb_hint = any(
                    w.lower().endswith(("s", "ed", "ing", "is", "are", "was"))
                    for w in words
                )
                if not has_verb_hint:
                    issues.append(self._warning(
                        code="possible_sentence_fragment",
                        message=(
                            f"Possible sentence fragment: '{sent.strip()}'"
                        ),
                        location=f"sentence_{i}.{location}",
                        suggestion="Expand into a complete sentence with subject and verb.",
                    ))

        return issues


def _count_syllables(word: str) -> int:
    """
    Approximate syllable count by counting vowel groups.
    Returns minimum 1 for any non-empty word.
    """
    vowels = "aeiouAEIOU"
    count = 0
    prev_vowel = False
    for char in word.strip(".,!?;:'\"()[]"):
        is_vowel = char in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    return max(1, count)

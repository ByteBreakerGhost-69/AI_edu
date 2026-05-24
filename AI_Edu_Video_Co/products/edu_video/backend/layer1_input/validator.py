# products/edu_video/backend/layer1_input/validator.py
"""
Job input validator: runs all validation rules, collects errors and warnings,
and returns sanitized input text. Never raises — always returns ValidationResult.
"""

import re
import unicodedata
from html.parser import HTMLParser
from typing import TYPE_CHECKING

import structlog

from layer1_input.schemas import (
    DifficultyEnum,
    ParsedImageContent,
    SubjectEnum,
    ValidationError,
    ValidationResult,
    VideoJobRequest,
)

if TYPE_CHECKING:
    from models.user import User

__all__ = [
    "JobValidator",
    "job_validator",
]

logger = structlog.get_logger(__name__)

# --- Constants ---

SUPPORTED_LANGUAGES = {"en", "id", "es", "fr", "de", "zh", "ar", "ja", "pt", "ko"}

_PROFANITY_PATTERNS = [
    r"\bfuck\b", r"\bshit\b", r"\basshole\b", r"\bbitch\b",
    r"\bcunt\b", r"\bdick\b", r"\bpussy\b", r"\bbastard\b",
    r"\bdamn\b", r"\bbollocks\b",
]

_OUT_OF_SCOPE_PATTERNS = [
    r"\bbuy now\b", r"\bclick here\b", r"\bsubscribe\b",
    r"\bdiscount\b", r"\boffer\b", r"\bpromo\b",
    r"\bfree shipping\b", r"\blimited time\b", r"\bact now\b",
]

_GCS_URL_PREFIX = "https://storage.googleapis.com/"

_COMPILED_PROFANITY = [
    re.compile(p, re.IGNORECASE) for p in _PROFANITY_PATTERNS
]
_COMPILED_OOS = [
    re.compile(p, re.IGNORECASE) for p in _OUT_OF_SCOPE_PATTERNS
]


# --- HTML stripper ---

class _HTMLStripper(HTMLParser):
    """Minimal HTML-tag stripper that preserves text content."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def _strip_html(text: str) -> str:
    stripper = _HTMLStripper()
    stripper.feed(text)
    return stripper.get_text()


def _sanitize_text(text: str) -> str:
    """Strip HTML, normalize unicode (NFKC), collapse whitespace."""
    cleaned = _strip_html(text)
    cleaned = unicodedata.normalize("NFKC", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _detect_language(text: str) -> str | None:
    """
    Attempt language detection using langdetect.
    Returns BCP-47 base code or None if detection fails/uncertain.
    """
    try:
        from langdetect import DetectorFactory, detect, detect_langs  # type: ignore

        DetectorFactory.seed = 42  # deterministic
        langs = detect_langs(text[:500])
        if langs and langs[0].prob >= 0.80:
            return str(detect(text[:500]))
        return None  # uncertain
    except Exception:
        return None


# --- Validator ---

class JobValidator:
    """
    Validates a VideoJobRequest before it enters the pipeline.
    Runs all rules, collects ALL errors (not fail-fast), and returns ValidationResult.
    """

    async def validate_job_input(
        self,
        request: VideoJobRequest,
        user: "User",
        parsed_image: ParsedImageContent | None = None,
    ) -> ValidationResult:
        """
        Run all validation rules against the request.

        Args:
            request: The incoming VideoJobRequest.
            user: Authenticated user (used for future role-based rule extensions).
            parsed_image: Pre-parsed image content if input_image_url was provided.

        Returns:
            ValidationResult with is_valid=True only if no ValidationErrors were found.
            Warnings are informational and do not block.
        """
        errors: list[ValidationError] = []
        warnings: list[str] = []
        sanitized: str | None = None

        # --- Text validations ---
        input_text = request.input_text
        input_image_url = request.input_image_url

        if input_text is None and input_image_url is None:
            errors.append(ValidationError(
                field="input",
                code="no_input",
                message="At least one of input_text or input_image_url must be provided.",
            ))

        if input_text is not None:
            sanitized = _sanitize_text(input_text)

            if len(sanitized) < 20:
                errors.append(ValidationError(
                    field="input_text",
                    code="too_short",
                    message="Input text must be at least 20 characters after sanitization.",
                ))

            if len(sanitized) > 5000:
                errors.append(ValidationError(
                    field="input_text",
                    code="too_long",
                    message="Input text must not exceed 5000 characters.",
                ))

            # Profanity check
            for pattern in _COMPILED_PROFANITY:
                if pattern.search(sanitized):
                    errors.append(ValidationError(
                        field="input_text",
                        code="profanity",
                        message="Input contains inappropriate content.",
                    ))
                    break

            # Out-of-scope check
            for pattern in _COMPILED_OOS:
                if pattern.search(sanitized):
                    errors.append(ValidationError(
                        field="input_text",
                        code="out_of_scope",
                        message=(
                            "Input appears to contain non-educational/promotional content."
                        ),
                    ))
                    break

            # Language detection
            detected_lang = _detect_language(sanitized)
            if detected_lang is not None:
                base_lang = detected_lang.split("-")[0].lower()
                request_lang = request.language.split("-")[0].lower()
                if base_lang not in SUPPORTED_LANGUAGES:
                    errors.append(ValidationError(
                        field="language",
                        code="unsupported_language",
                        message=(
                            f"Detected language '{detected_lang}' is not supported. "
                            f"Supported: {sorted(SUPPORTED_LANGUAGES)}"
                        ),
                    ))
                elif base_lang != request_lang:
                    warnings.append(
                        f"Detected language '{detected_lang}' may not match "
                        f"requested language '{request.language}'."
                    )
            else:
                warnings.append(
                    "Language detection was inconclusive. "
                    "Proceeding with requested language."
                )

        # --- Image validations ---
        if input_image_url is not None:
            if not input_image_url.startswith(_GCS_URL_PREFIX):
                errors.append(ValidationError(
                    field="input_image_url",
                    code="invalid_image_url",
                    message=(
                        "Image URL must be a valid GCS URL starting with "
                        f"'{_GCS_URL_PREFIX}'."
                    ),
                ))

            if parsed_image is not None:
                if parsed_image.confidence < 0.3:
                    warnings.append(
                        "Image was parsed with low confidence. "
                        "Content accuracy may be reduced."
                    )
                if parsed_image.image_type == "mixed" and input_text is None:
                    warnings.append(
                        "Mixed image type detected without supplementary text input. "
                        "Output quality may be reduced."
                    )

        # --- Subject / curriculum validations ---
        if (
            request.subject == SubjectEnum.computer_science
            and request.difficulty_level == DifficultyEnum.beginner
        ):
            warnings.append(
                "Beginner-level computer science content may have limited "
                "curriculum coverage."
            )

        is_valid = len(errors) == 0

        logger.info(
            "validator.result",
            is_valid=is_valid,
            error_count=len(errors),
            warning_count=len(warnings),
        )

        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            sanitized_input=sanitized,
        )


job_validator = JobValidator()

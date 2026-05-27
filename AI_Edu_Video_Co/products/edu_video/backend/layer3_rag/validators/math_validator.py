# products/edu_video/backend/layer3_rag/validators/math_validator.py
"""
MathValidator: regex and eval-based checks for mathematical content.
No LLM calls — pure programmatic validation.
"""

import re
from operator import add, mul, sub, truediv

import structlog

from layer3_rag.validators.base_validator import (
    BaseValidator,
    ValidationIssue,
    ValidationReport,
    register_validator,
)

__all__ = ["MathValidator"]

logger = structlog.get_logger(__name__)

_LOCATION_PREFIX = "narration_text"

# Regex patterns
_SINGLE_DOLLAR = re.compile(r"(?<!\$)\$(?!\$)")
_DOUBLE_DOLLAR = re.compile(r"\$\$")
_DIVISION_BY_ZERO = re.compile(r"[÷/]\s*0\b|mod\s+0\b", re.IGNORECASE)
_UNDEFINED_VAR_CONTEXT = re.compile(
    r"\b(let\s+[a-z]\s*=|where\s+[a-z]\s+is|[a-z]\s*∈|define\s+[a-z])\b",
    re.IGNORECASE,
)
_SIMPLE_ARITHMETIC = re.compile(
    r"(\d[\d\s]*)"
    r"\s*([+\-×÷\*\/])\s*"
    r"(\d[\d\s]*)"
    r"\s*=\s*"
    r"(\d[\d\s]*)"
)
_NOTATION_FUNCTION = re.compile(r"\bf\(x\)\b")
_NOTATION_PROSE = re.compile(r"\bf\s+of\s+x\b", re.IGNORECASE)


@register_validator("math")
class MathValidator(BaseValidator):
    """
    Validates mathematical content for:
    - Unmatched LaTeX delimiters
    - Division by zero patterns
    - Inconsistent notation (f(x) vs f of x)
    - Incorrect simple arithmetic
    - Missing units in applied contexts
    """

    @property
    def validator_name(self) -> str:
        return "math_validator"

    async def validate(
        self,
        content: str,
        context: dict,
    ) -> ValidationReport:
        location = f"scene_{context.get('scene_index', 0)}.{_LOCATION_PREFIX}"
        issues: list[ValidationIssue] = []

        try:
            issues.extend(self._check_latex_delimiters(content, location))
            issues.extend(self._check_division_by_zero(content, location))
            issues.extend(self._check_inconsistent_notation(content, location))
            issues.extend(self._check_arithmetic(content, location))
            issues.extend(self._check_missing_units(content, context, location))
        except Exception as exc:
            logger.error("math_validator.crash", error=str(exc))
            return self._crash_report(str(exc))

        return self._make_report(issues, confidence=0.9)

    def _check_latex_delimiters(
        self, content: str, location: str
    ) -> list[ValidationIssue]:
        issues = []
        single_count = len(_SINGLE_DOLLAR.findall(content))
        double_count = len(_DOUBLE_DOLLAR.findall(content))

        if single_count % 2 != 0:
            issues.append(self._error(
                code="unmatched_latex_delimiter",
                message=f"Odd number of single $ delimiters ({single_count}). LaTeX may not render.",
                location=location,
                suggestion="Ensure every opening $ has a matching closing $.",
            ))
        if double_count % 2 != 0:
            issues.append(self._error(
                code="unmatched_latex_delimiter",
                message=f"Odd number of $$ delimiters ({double_count}). Display math block unclosed.",
                location=location,
                suggestion="Ensure every $$ opening has a matching $$ closing.",
            ))
        return issues

    def _check_division_by_zero(
        self, content: str, location: str
    ) -> list[ValidationIssue]:
        if _DIVISION_BY_ZERO.search(content):
            return [self._warning(
                code="division_by_zero_risk",
                message="Possible division by zero pattern detected.",
                location=location,
                suggestion=(
                    "If intentional (e.g., discussing undefined expressions), "
                    "add explicit clarification."
                ),
            )]
        return []

    def _check_inconsistent_notation(
        self, content: str, location: str
    ) -> list[ValidationIssue]:
        has_functional = bool(_NOTATION_FUNCTION.search(content))
        has_prose = bool(_NOTATION_PROSE.search(content))
        if has_functional and has_prose:
            return [self._warning(
                code="inconsistent_notation",
                message="Mixed notation: 'f(x)' and 'f of x' used in the same scene.",
                location=location,
                suggestion="Standardise to one notation style throughout the scene.",
            )]
        return []

    def _check_arithmetic(
        self, content: str, location: str
    ) -> list[ValidationIssue]:
        issues = []
        _OP_MAP = {"+": add, "-": sub, "×": mul, "*": mul, "÷": truediv, "/": truediv}

        for match in _SIMPLE_ARITHMETIC.finditer(content):
            try:
                a = float(match.group(1).replace(" ", ""))
                op_char = match.group(2)
                b = float(match.group(3).replace(" ", ""))
                stated = float(match.group(4).replace(" ", ""))
                op_fn = _OP_MAP.get(op_char)
                if op_fn is None:
                    continue
                if b == 0 and op_char in ("÷", "/"):
                    continue  # skip division by zero — caught separately
                actual = op_fn(a, b)
                if abs(actual - stated) > 0.001:
                    issues.append(self._error(
                        code="incorrect_arithmetic",
                        message=(
                            f"Arithmetic error: {a} {op_char} {b} = {stated} "
                            f"(correct answer: {actual})"
                        ),
                        location=location,
                        suggestion=f"Correct the result to {actual}.",
                    ))
            except (ValueError, ZeroDivisionError):
                continue

        return issues

    def _check_missing_units(
        self, content: str, context: dict, location: str
    ) -> list[ValidationIssue]:
        if context.get("subject") not in ("physics", "chemistry"):
            return []

        # Detect bare numeric answers without units
        # Pattern: number at end of sentence without SI unit following
        _BARE_NUMBER_END = re.compile(r"\b\d+\.?\d*\s*[.!?]")
        _HAS_UNIT = re.compile(
            r"\b\d+\.?\d*\s*"
            r"(m|kg|s|A|K|mol|J|W|Pa|N|Hz|°C|°F|L|mL|cm|km|g|ms)\b"
        )

        bare_matches = _BARE_NUMBER_END.findall(content)
        unit_matches = _HAS_UNIT.findall(content)

        if bare_matches and not unit_matches:
            return [self._warning(
                code="missing_units",
                message="Numeric values found without apparent SI units in an applied science context.",
                location=location,
                suggestion="Attach appropriate SI units to all numerical answers.",
            )]
        return []

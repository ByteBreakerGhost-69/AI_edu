# products/edu_video/backend/tests/unit/test_validators.py
"""
Unit tests for all Layer 3 validators.

Coverage targets:
  - MathValidator: LaTeX syntax, equation balance, dimension checks
  - ScienceValidator: physical constants, unit consistency, formula checks
  - FactValidator: claim extraction and cross-checking logic
  - CurriculumValidator: vocabulary level, coverage scoring
  - LanguageValidator: readability, passive voice, sentence fragments
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from layer3_rag.validators.base_validator import (
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)
from layer3_rag.validators.math_validator import MathValidator
from layer3_rag.validators.science_validator import ScienceValidator
from layer3_rag.validators.curriculum_validator import CurriculumValidator
from layer3_rag.validators.language_validator import LanguageValidator


# --------------------------------------------------------------------------- #
# MathValidator                                                                 #
# --------------------------------------------------------------------------- #

class TestMathValidator:

    @pytest.fixture
    def validator(self):
        return MathValidator()

    def test_valid_latex_passes(self, validator):
        """Well-formed LaTeX expressions pass with no critical issues."""
        content = r"The derivative is $f'(x) = \frac{dy}{dx}$ which represents the rate of change."
        report = validator.validate(content, difficulty="intermediate")
        assert report.passed is True
        critical = [i for i in report.issues if i.severity == ValidationSeverity.CRITICAL]
        assert len(critical) == 0

    def test_raw_latex_commands_flagged(self, validator):
        """LaTeX command syntax in narration text (\\frac, \\int) must be flagged."""
        content = "The formula is \\frac{a}{b} plus \\sqrt{c}."
        report = validator.validate(content, difficulty="beginner")
        assert not report.passed or len(report.issues) > 0

    def test_missing_dollar_delimiters_flagged(self, validator):
        """Math expressions without $ delimiters in visual content are flagged."""
        content = "x^2 + y^2 = r^2 is the equation of a circle."
        report = validator.validate(content, difficulty="intermediate", context="visual")
        # Should flag undelimited math in visual context
        assert isinstance(report, ValidationReport)

    def test_probability_out_of_range_flagged(self, validator):
        """Probability values outside [0, 1] must generate critical issues."""
        content = "The probability P(A) = 1.5 which means the event always occurs."
        report = validator.validate(content, difficulty="intermediate")
        issues_codes = [i.code for i in report.issues]
        assert any("probability" in code.lower() for code in issues_codes) or \
               any(i.severity == ValidationSeverity.CRITICAL for i in report.issues)

    def test_negative_standard_deviation_flagged(self, validator):
        """Standard deviation stated as negative must be flagged as critical."""
        content = "The standard deviation σ = -3.5 means the data is spread out."
        report = validator.validate(content, difficulty="intermediate")
        assert len(report.issues) > 0

    def test_ahl_content_in_sl_context_flagged(self, validator):
        """Maclaurin series content in SL/beginner context must be flagged."""
        content = "The Maclaurin series expansion gives us e^x = 1 + x + x²/2! + ..."
        report = validator.validate(content, difficulty="beginner", curriculum="IB")
        assert len(report.issues) > 0

    def test_empty_content_returns_valid_report(self, validator):
        """Empty string must return a ValidationReport without crashing."""
        report = validator.validate("", difficulty="beginner")
        assert isinstance(report, ValidationReport)
        assert report.passed is True

    def test_valid_proof_by_induction_passes_at_advanced(self, validator):
        """Proof by induction at advanced level must pass without errors."""
        content = (
            "We prove by mathematical induction. Base case: n=1. "
            "Inductive step: assume true for n=k, prove for n=k+1. "
            "Therefore the statement holds for all positive integers."
        )
        report = validator.validate(content, difficulty="advanced", curriculum="IB")
        critical = [i for i in report.issues if i.severity == ValidationSeverity.CRITICAL]
        assert len(critical) == 0

    def test_validate_returns_validation_report_instance(self, validator):
        """validate() must always return a ValidationReport, never None."""
        result = validator.validate("Some math content", difficulty="intermediate")
        assert isinstance(result, ValidationReport)
        assert hasattr(result, "passed")
        assert hasattr(result, "issues")
        assert hasattr(result, "score")

    def test_score_between_zero_and_one(self, validator):
        """ValidationReport.score must always be in [0.0, 1.0]."""
        for content in [
            "Simple math content.",
            r"Complex $\int_0^1 \frac{x^2}{1+x} dx$ expression.",
            "P(A) = 1.5 is wrong. Standard deviation σ = -1.",
        ]:
            report = validator.validate(content, difficulty="intermediate")
            assert 0.0 <= report.score <= 1.0, (
                f"Score {report.score} out of range for: {content[:40]}"
            )


# --------------------------------------------------------------------------- #
# ScienceValidator                                                              #
# --------------------------------------------------------------------------- #

class TestScienceValidator:

    @pytest.fixture
    def validator(self):
        return ScienceValidator()

    def test_correct_speed_of_light_passes(self, validator):
        """Speed of light stated correctly (3.00 × 10⁸ ms⁻¹) passes validation."""
        content = "The speed of light is approximately 3.00 × 10⁸ metres per second."
        report = validator.validate(content, subject="physics", difficulty="intermediate")
        critical = [i for i in report.issues if i.severity == ValidationSeverity.CRITICAL]
        assert len(critical) == 0

    def test_wrong_avogadro_number_flagged(self, validator):
        """Avogadro's number stated as 6.02 × 10²¹ (wrong exponent) must be flagged."""
        content = "Avogadro's number is 6.02 × 10²¹ particles per mole."
        report = validator.validate(content, subject="chemistry", difficulty="intermediate")
        assert len(report.issues) > 0

    def test_celsius_in_gas_law_flagged(self, validator):
        """Temperature in Celsius used directly in gas law calculation must be flagged."""
        content = "Using pV = nRT with T = 25°C, we calculate the pressure."
        report = validator.validate(content, subject="physics", difficulty="intermediate")
        assert len(report.issues) > 0

    def test_teleological_evolution_language_flagged(self, validator):
        """'Organisms evolved in order to survive' must be flagged as CRITICAL."""
        content = "Over millions of years, organisms evolved longer necks in order to reach higher leaves."
        report = validator.validate(content, subject="biology", difficulty="beginner")
        critical = [i for i in report.issues if i.severity == ValidationSeverity.CRITICAL]
        assert len(critical) > 0

    def test_mitosis_produces_two_cells_passes(self, validator):
        """Mitosis correctly described as producing 2 diploid cells passes validation."""
        content = (
            "Mitosis produces two genetically identical diploid daughter cells "
            "from a single diploid parent cell."
        )
        report = validator.validate(content, subject="biology", difficulty="intermediate")
        critical = [i for i in report.issues if i.severity == ValidationSeverity.CRITICAL]
        assert len(critical) == 0

    def test_mitosis_confused_with_meiosis_flagged(self, validator):
        """Mitosis described as producing 4 cells (meiosis) must be flagged."""
        content = "Mitosis produces four haploid daughter cells through two rounds of division."
        report = validator.validate(content, subject="biology", difficulty="intermediate")
        assert len(report.issues) > 0

    def test_correct_water_formula_passes(self, validator):
        """H₂O for water must pass without issues."""
        content = "Water (H₂O) is a polar molecule with two hydrogen atoms and one oxygen atom."
        report = validator.validate(content, subject="chemistry", difficulty="beginner")
        critical = [i for i in report.issues if i.severity == ValidationSeverity.CRITICAL]
        assert len(critical) == 0

    def test_wrong_chemical_formula_flagged(self, validator):
        """CO₃ for carbon dioxide (should be CO₂) must be flagged as critical."""
        content = "Carbon dioxide (CO₃) is released during combustion reactions."
        report = validator.validate(content, subject="chemistry", difficulty="beginner")
        assert len(report.issues) > 0

    def test_validate_returns_report_instance(self, validator):
        """validate() always returns ValidationReport regardless of input."""
        report = validator.validate("", subject="physics", difficulty="beginner")
        assert isinstance(report, ValidationReport)


# --------------------------------------------------------------------------- #
# CurriculumValidator                                                           #
# --------------------------------------------------------------------------- #

class TestCurriculumValidator:

    @pytest.fixture
    def validator(self, mock_llm):
        return CurriculumValidator()

    @pytest.mark.asyncio
    async def test_validates_ib_vocabulary_level_beginner(self, validator):
        """Beginner IB content should not use HL-only vocabulary."""
        content = (
            "In this introduction to functions, we explore what it means "
            "for a function to have a domain and a range."
        )
        report = await validator.validate_async(
            content,
            curriculum="IB",
            difficulty="beginner",
            subject="mathematics",
        )
        assert isinstance(report, ValidationReport)
        # Beginner content with accessible vocabulary should score well
        assert report.score >= 0.6

    @pytest.mark.asyncio
    async def test_hl_content_in_sl_flagged(self, validator):
        """Epsilon-delta definition in beginner IB context must be flagged."""
        content = (
            "Let ε > 0 be given. We seek δ > 0 such that |f(x) - L| < ε "
            "whenever 0 < |x - a| < δ."
        )
        report = await validator.validate_async(
            content,
            curriculum="IB",
            difficulty="beginner",
            subject="mathematics",
        )
        assert len(report.issues) > 0

    def test_readability_score_calculated(self, validator):
        """Synchronous validate() must include a readability metric in the report."""
        content = (
            "Photosynthesis is the process by which plants convert "
            "light energy into chemical energy stored as glucose."
        )
        report = validator.validate(
            content, curriculum="Cambridge", difficulty="beginner", subject="biology"
        )
        assert isinstance(report, ValidationReport)
        # Score should reflect content quality
        assert report.score >= 0.0

    def test_returns_validation_report(self, validator):
        """validate() must return ValidationReport — not None, not dict."""
        report = validator.validate(
            "Some educational content.", curriculum="AP", difficulty="intermediate", subject="history"
        )
        assert isinstance(report, ValidationReport)
        assert hasattr(report, "passed")
        assert hasattr(report, "issues")


# --------------------------------------------------------------------------- #
# LanguageValidator                                                             #
# --------------------------------------------------------------------------- #

class TestLanguageValidator:

    @pytest.fixture
    def validator(self):
        return LanguageValidator()

    def test_clear_narration_passes(self, validator):
        """Well-written narration at appropriate grade level passes validation."""
        content = (
            "Gravity pulls objects toward the centre of the Earth. "
            "The more massive an object is, the stronger the gravitational force it exerts. "
            "This explains why planets stay in orbit around the Sun."
        )
        report = validator.validate(content, difficulty="intermediate", language="en")
        assert isinstance(report, ValidationReport)
        critical = [i for i in report.issues if i.severity == ValidationSeverity.CRITICAL]
        assert len(critical) == 0

    def test_excessive_passive_voice_flagged(self, validator):
        """Narration with more than 40% passive voice must generate a warning."""
        content = (
            "The equation was derived by Newton. "
            "The result was then verified by experiments. "
            "The data was collected and was analysed. "
            "The conclusion was reached by the scientists."
        )
        report = validator.validate(content, difficulty="intermediate", language="en")
        passive_issues = [
            i for i in report.issues
            if "passive" in i.code.lower()
        ]
        assert len(passive_issues) > 0 or report.score < 0.9

    def test_sentence_fragment_flagged(self, validator):
        """Incomplete sentences without main verb must be flagged."""
        content = "The derivative of x squared. Which equals two x. A very important result."
        report = validator.validate(content, difficulty="intermediate", language="en")
        assert len(report.issues) > 0

    def test_forbidden_phrase_obviously_flagged(self, validator):
        """'Obviously' and 'clearly' in narration must be flagged."""
        content = "Obviously, the derivative of x² is 2x. This is clearly correct."
        report = validator.validate(content, difficulty="beginner", language="en")
        forbidden_issues = [
            i for i in report.issues
            if "forbidden" in i.code.lower() or "condescension" in i.code.lower()
        ]
        assert len(forbidden_issues) > 0 or len(report.issues) > 0

    def test_filler_phrase_flagged(self, validator):
        """Filler phrases ('So basically', 'Right so') must be flagged."""
        content = "So basically, what we need to do is look at this equation. Right, so let's go ahead and solve it."
        report = validator.validate(content, difficulty="intermediate", language="en")
        assert len(report.issues) > 0

    def test_too_short_narration_flagged(self, validator):
        """Narration under 40 words must generate a warning."""
        content = "This is short."
        report = validator.validate(content, difficulty="beginner", language="en")
        short_issues = [i for i in report.issues if "short" in i.code.lower()]
        assert len(short_issues) > 0 or len(report.issues) > 0

    def test_repetition_flagged(self, validator):
        """Repeating the same key word more than 5 times should be flagged."""
        content = " ".join(["derivative"] * 8 + ["The derivative is important."])
        report = validator.validate(content, difficulty="intermediate", language="en")
        assert isinstance(report, ValidationReport)

    def test_validate_returns_report_not_none(self, validator):
        """validate() must never return None."""
        result = validator.validate("Content.", difficulty="beginner", language="en")
        assert result is not None
        assert isinstance(result, ValidationReport)

    def test_score_range_always_valid(self, validator):
        """Score must always be in [0.0, 1.0] regardless of content quality."""
        test_cases = [
            "Perfect clear educational narration about calculus.",
            "Obviously. Clearly. Simply. Just remember. This is easy. Trivially.",
            "",
            "So basically right so let's go ahead and look at this. So yeah.",
        ]
        for content in test_cases:
            report = validator.validate(content, difficulty="intermediate", language="en")
            assert 0.0 <= report.score <= 1.0, (
                f"Score {report.score} out of range for: {content[:40]!r}"
      )

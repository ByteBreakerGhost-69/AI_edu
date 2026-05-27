# products/edu_video/backend/layer3_rag/validators/science_validator.py
"""
ScienceValidator: covers physics constants, SI units, chemistry equation
balance, and biology taxonomy/terminology checks.
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

__all__ = ["ScienceValidator"]

logger = structlog.get_logger(__name__)

# Physics constants — acceptable textual representations
_PHYSICAL_CONSTANTS: dict[str, tuple[str, ...]] = {
    "speed of light": ("3×10⁸", "3×10^8", "299792458", "3 × 10^8", "3.0×10^8"),
    "gravitational acceleration": ("9.81", "9.8", "10", "g = 9.81", "g = 9.8"),
    "planck constant": ("6.626×10⁻³⁴", "6.63×10^-34", "6.626 × 10^-34"),
    "boltzmann constant": ("1.38×10⁻²³", "1.381×10^-23"),
    "avogadro": ("6.022×10²³", "6.02×10^23", "6.022 × 10^23"),
    "electron charge": ("1.6×10⁻¹⁹", "1.602×10^-19"),
}

_NON_SI_UNITS = re.compile(
    r"\b(feet|foot|ft\b|pounds|lbs?\b|miles?\b|Fahrenheit|°F|gallons?|inches?|yards?|ounces?)\b",
    re.IGNORECASE,
)

# All 118 element symbols
_ELEMENT_SYMBOLS: frozenset[str] = frozenset({
    "H","He","Li","Be","B","C","N","O","F","Ne","Na","Mg","Al","Si","P","S",
    "Cl","Ar","K","Ca","Sc","Ti","V","Cr","Mn","Fe","Co","Ni","Cu","Zn","Ga",
    "Ge","As","Se","Br","Kr","Rb","Sr","Y","Zr","Nb","Mo","Tc","Ru","Rh","Pd",
    "Ag","Cd","In","Sn","Sb","Te","I","Xe","Cs","Ba","La","Ce","Pr","Nd","Pm",
    "Sm","Eu","Gd","Tb","Dy","Ho","Er","Tm","Yb","Lu","Hf","Ta","W","Re","Os",
    "Ir","Pt","Au","Hg","Tl","Pb","Bi","Po","At","Rn","Fr","Ra","Ac","Th","Pa",
    "U","Np","Pu","Am","Cm","Bk","Cf","Es","Fm","Md","No","Lr","Rf","Db","Sg",
    "Bh","Hs","Mt","Ds","Rg","Cn","Nh","Fl","Mc","Lv","Ts","Og",
})

_CHEMICAL_FORMULA = re.compile(r"\b([A-Z][a-z]?)(\d*)\b")
_REACTION_PATTERN = re.compile(
    r"([A-Z][A-Za-z0-9₀-₉⁰-⁹\s\+]+)\s*[→⟶⇌=]\s*([A-Z][A-Za-z0-9₀-₉⁰-⁹\s\+]+)"
)

_DEPRECATED_BIO_TERMS: dict[str, str] = {
    "junk dna": "non-coding DNA",
    "survival of the fittest": "natural selection",
    "mitochondria is": "mitochondria are",
    "simple cell": "prokaryotic cell",
}

_BINOMIAL_PATTERN = re.compile(r"\b([A-Z][a-z]+\s[a-z]+)\b")


@register_validator("science")
class ScienceValidator(BaseValidator):
    """
    Multi-domain science validator covering physics, chemistry, and biology.
    Routes checks based on context["subject"].
    """

    @property
    def validator_name(self) -> str:
        return "science_validator"

    async def validate(
        self,
        content: str,
        context: dict,
    ) -> ValidationReport:
        location = f"scene_{context.get('scene_index', 0)}.narration_text"
        subject = context.get("subject", "").lower()
        issues: list[ValidationIssue] = []

        try:
            if subject == "physics":
                issues.extend(self._check_physics(content, location))
            elif subject == "chemistry":
                issues.extend(self._check_chemistry(content, location))
            elif subject == "biology":
                issues.extend(self._check_biology(content, location))
            else:
                # Generic science — run all checks leniently
                issues.extend(self._check_physics(content, location))
                issues.extend(self._check_chemistry(content, location))

        except Exception as exc:
            logger.error("science_validator.crash", error=str(exc))
            return self._crash_report(str(exc))

        return self._make_report(issues, confidence=0.85)

    def _check_physics(
        self, content: str, location: str
    ) -> list[ValidationIssue]:
        issues = []
        content_lower = content.lower()

        # Physical constant checks
        for constant_name, valid_values in _PHYSICAL_CONSTANTS.items():
            if constant_name in content_lower:
                if not any(v.lower() in content_lower for v in valid_values):
                    issues.append(self._warning(
                        code="incorrect_physical_constant",
                        message=(
                            f"'{constant_name}' is mentioned but no recognized "
                            f"value found. Expected one of: {valid_values[:2]}"
                        ),
                        location=location,
                        suggestion=f"Use the accepted value: {valid_values[0]}",
                    ))

        # Non-SI unit check
        if _NON_SI_UNITS.search(content):
            issues.append(self._warning(
                code="non_si_unit",
                message="Non-SI unit detected in physics content.",
                location=location,
                suggestion=(
                    "Convert to SI units (m, kg, s, K, etc.) unless explicitly "
                    "discussing unit conversion."
                ),
            ))

        return issues

    def _check_chemistry(
        self, content: str, location: str
    ) -> list[ValidationIssue]:
        issues = []

        # Unknown element symbols
        formula_matches = _CHEMICAL_FORMULA.findall(content)
        for symbol, _ in formula_matches:
            if len(symbol) >= 2 and symbol not in _ELEMENT_SYMBOLS:
                # Only flag multi-char symbols — single letters could be variables
                issues.append(self._error(
                    code="unknown_element_symbol",
                    message=f"'{symbol}' is not a recognized element symbol.",
                    location=location,
                    suggestion="Check the element symbol against the periodic table.",
                ))

        # Simple equation balance (regex approximation)
        for match in _REACTION_PATTERN.finditer(content):
            lhs, rhs = match.group(1), match.group(2)
            lhs_atoms = _count_atoms(lhs)
            rhs_atoms = _count_atoms(rhs)
            unbalanced = {
                el for el in lhs_atoms
                if lhs_atoms.get(el, 0) != rhs_atoms.get(el, 0)
            }
            if unbalanced:
                issues.append(self._warning(
                    code="possibly_unbalanced_equation",
                    message=(
                        f"Possible imbalance for element(s): {', '.join(sorted(unbalanced))}. "
                        "(Note: this check uses regex approximation)"
                    ),
                    location=location,
                    suggestion="Verify atom counts on both sides of the reaction arrow.",
                ))

        return issues

    def _check_biology(
        self, content: str, location: str
    ) -> list[ValidationIssue]:
        issues = []
        content_lower = content.lower()

        # Deprecated terminology
        for deprecated, preferred in _DEPRECATED_BIO_TERMS.items():
            if deprecated in content_lower:
                issues.append(self._warning(
                    code="deprecated_biological_term",
                    message=f"Deprecated term '{deprecated}' detected.",
                    location=location,
                    suggestion=f"Replace with '{preferred}'.",
                ))

        # Binomial nomenclature check (species names should be Genus species)
        binomial_matches = _BINOMIAL_PATTERN.findall(content)
        for candidate in binomial_matches:
            parts = candidate.split()
            if len(parts) == 2:
                genus, species = parts
                if not (genus[0].isupper() and species.islower()):
                    issues.append(self._warning(
                        code="incorrect_species_naming",
                        message=(
                            f"'{candidate}' may not follow binomial nomenclature. "
                            "Genus should be capitalised, species lowercase."
                        ),
                        location=location,
                        suggestion=f"Format as '{genus.capitalize()} {species.lower()}'.",
                    ))

        return issues


def _count_atoms(formula_side: str) -> dict[str, int]:
    """Approximate atom count from a formula string (e.g. '2H₂O + O₂')."""
    counts: dict[str, int] = {}
    # Normalise subscripts
    normalised = formula_side
    subscript_map = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
    normalised = normalised.translate(subscript_map)

    for symbol, num_str in _CHEMICAL_FORMULA.findall(normalised):
        if symbol in _ELEMENT_SYMBOLS:
            count = int(num_str) if num_str else 1
            counts[symbol] = counts.get(symbol, 0) + count
    return counts

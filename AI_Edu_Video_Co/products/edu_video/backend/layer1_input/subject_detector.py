# products/edu_video/backend/layer1_input/subject_detector.py
"""
Subject detector: keyword-based fast path + LLM fallback.
Determines the educational subject of user input without LLM cost when possible.
"""

import re
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from core.cost_tracker import CostTracker
from core.llm import llm_factory
from core.utils import safe_json_loads
from layer1_input.schemas import ParsedImageContent, SubjectDetectionResult, SubjectEnum

__all__ = [
    "SubjectDetector",
    "subject_detector",
    "SUBJECT_KEYWORDS",
]

logger = structlog.get_logger(__name__)

# --- Keyword map: 15+ keywords per subject ---

SUBJECT_KEYWORDS: dict[SubjectEnum, list[str]] = {
    SubjectEnum.mathematics: [
        "equation", "derivative", "integral", "matrix", "theorem", "proof",
        "calculus", "algebra", "geometry", "polynomial", "function", "vector",
        "probability", "statistics", "differential", "logarithm", "trigonometry",
        "eigenvalue", "determinant", "sequence",
    ],
    SubjectEnum.physics: [
        "force", "velocity", "acceleration", "momentum", "energy", "wave",
        "quantum", "relativity", "thermodynamics", "circuit", "magnetic",
        "electric", "gravity", "entropy", "photon", "refraction", "oscillation",
        "pressure", "torque", "nuclear",
    ],
    SubjectEnum.chemistry: [
        "molecule", "reaction", "element", "compound", "bond", "acid", "base",
        "oxidation", "reduction", "catalyst", "polymer", "ionic", "covalent",
        "periodic", "mole", "electrolysis", "titration", "valence", "isomer",
        "solubility",
    ],
    SubjectEnum.biology: [
        "cell", "DNA", "protein", "enzyme", "evolution", "organism", "genome",
        "photosynthesis", "mitosis", "chromosome", "species", "ecosystem",
        "metabolism", "neuron", "hormone", "respiration", "meiosis", "allele",
        "mutation", "antibody",
    ],
    SubjectEnum.history: [
        "century", "empire", "revolution", "civilization", "war", "treaty",
        "dynasty", "colonization", "independence", "reform", "monarchy",
        "republic", "ancient", "medieval", "historical", "conquest", "parliament",
        "nationalism", "feudalism", "renaissance",
    ],
    SubjectEnum.geography: [
        "continent", "climate", "topography", "latitude", "longitude", "biome",
        "erosion", "tectonic", "population", "urban", "migration", "watershed",
        "peninsula", "monsoon", "cartography", "glacier", "delta", "plateau",
        "savanna", "urbanization",
    ],
    SubjectEnum.economics: [
        "GDP", "inflation", "supply", "demand", "market", "capital", "trade",
        "fiscal", "monetary", "recession", "elasticity", "monopoly", "utility",
        "equilibrium", "macroeconomics", "microeconomics", "tariff", "subsidy",
        "opportunity cost", "externality",
    ],
    SubjectEnum.literature: [
        "narrative", "metaphor", "protagonist", "theme", "symbolism", "genre",
        "stanza", "rhetoric", "allegory", "irony", "syntax", "prose", "verse",
        "characterization", "motif", "foreshadowing", "soliloquy", "bildungsroman",
        "diction", "denouement",
    ],
    SubjectEnum.computer_science: [
        "algorithm", "function", "variable", "loop", "recursion", "array",
        "database", "network", "complexity", "binary", "compiler", "class",
        "inheritance", "sorting", "bitwise", "pointer", "runtime", "heuristic",
        "encapsulation", "abstraction",
    ],
    SubjectEnum.language: [
        "grammar", "vocabulary", "conjugation", "syntax", "phoneme", "morpheme",
        "tense", "clause", "preposition", "bilingual", "fluency", "dialect",
        "idiom", "translation", "pragmatics", "lexicon", "suffix", "accent",
        "discourse", "intonation",
    ],
}

_KEYWORD_FAST_PATH_MIN_HITS = 3
_KEYWORD_FAST_PATH_MIN_GAP = 2

_SYSTEM_PROMPT = (
    "You are an expert educational content classifier. "
    "Given a text snippet, identify the primary academic subject. "
    "Respond ONLY with valid JSON — no markdown, no preamble."
)

_USER_PROMPT_TEMPLATE = (
    "Classify the educational subject of the following text.\n\n"
    "Text: {text}\n\n"
    "Valid subjects: mathematics, physics, chemistry, biology, history, "
    "geography, economics, literature, computer_science, language\n\n"
    "Respond ONLY as JSON: "
    '{{\"detected_subject\": \"<subject>\", \"confidence\": <0.0-1.0>, '
    '"alternative_subjects\": [\"<subject2>\", \"<subject3>\"], '
    '"reasoning\": \"<one sentence>\"}}'
)


class SubjectDetector:
    """
    Detects the educational subject of user input.
    Uses keyword scoring as a fast path; falls back to Claude if inconclusive.
    """

    async def detect_subject(
        self,
        text: str,
        parsed_image: ParsedImageContent | None = None,
        job_id: str = "",
        cost_tracker: CostTracker | None = None,
    ) -> SubjectDetectionResult:
        """
        Detect subject from text (+ parsed image text if available).

        Returns SubjectDetectionResult with confidence, alternatives, and reasoning.
        Never raises — falls back to mathematics on unrecoverable errors.
        """
        log = logger.bind(job_id=job_id)

        combined_text = text or ""
        if parsed_image and parsed_image.extracted_text:
            combined_text = f"{combined_text}\n{parsed_image.extracted_text}".strip()

        # Fast path: keyword scoring
        fast_result = self._keyword_detect(combined_text)
        if fast_result is not None:
            log.info(
                "subject_detector.detected",
                method="keyword",
                subject=fast_result.detected_subject,
                confidence=fast_result.confidence,
            )
            return fast_result

        # Fallback: LLM
        log.info("subject_detector.falling_back_to_llm")
        return await self._llm_detect(combined_text, job_id, log, cost_tracker)

    def _keyword_detect(self, text: str) -> SubjectDetectionResult | None:
        """
        Score each subject by keyword hits using word-boundary regex.
        Returns a result only if top score clears both thresholds.
        """
        text_lower = text.lower()
        scores: dict[SubjectEnum, int] = {}

        for subject, keywords in SUBJECT_KEYWORDS.items():
            hits = 0
            for kw in keywords:
                pattern = r"\b" + re.escape(kw.lower()) + r"\b"
                if re.search(pattern, text_lower):
                    hits += 1
            scores[subject] = hits

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_subject, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0

        if top_score < _KEYWORD_FAST_PATH_MIN_HITS:
            return None
        if (top_score - second_score) < _KEYWORD_FAST_PATH_MIN_GAP:
            return None

        alternatives = [s for s, _ in ranked[1:3]]
        return SubjectDetectionResult(
            detected_subject=top_subject,
            confidence=0.85,
            alternative_subjects=alternatives,
            reasoning=f"Keyword match: {top_score} hits for {top_subject.value}.",
        )

    async def _llm_detect(
        self,
        text: str,
        job_id: str,
        log: Any,
        cost_tracker: CostTracker | None,
    ) -> SubjectDetectionResult:
        """Call Claude to classify subject. Falls back to mathematics on error."""
        snippet = text[:500]
        llm = llm_factory.get_llm("claude")
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(
                content=_USER_PROMPT_TEMPLATE.format(text=snippet)
            ),
        ]

        try:
            response = await llm.ainvoke(messages)
            raw = str(response.content)
            parsed = safe_json_loads(raw)
            if parsed is None:
                cleaned = raw.strip().removeprefix("```json").removesuffix("```").strip()
                parsed = safe_json_loads(cleaned)

            if parsed is None:
                raise ValueError("LLM returned non-JSON response")

            detected_raw = parsed.get("detected_subject", "mathematics").lower()
            valid_values = {s.value for s in SubjectEnum}
            detected = (
                SubjectEnum(detected_raw)
                if detected_raw in valid_values
                else SubjectEnum.mathematics
            )

            alternatives_raw = parsed.get("alternative_subjects", [])
            alternatives = [
                SubjectEnum(a.lower())
                for a in alternatives_raw
                if isinstance(a, str) and a.lower() in valid_values
            ][:2]

            result = SubjectDetectionResult(
                detected_subject=detected,
                confidence=float(parsed.get("confidence", 0.6)),
                alternative_subjects=alternatives,
                reasoning=str(parsed.get("reasoning", "LLM classification.")),
            )

            log.info(
                "subject_detector.detected",
                method="llm",
                subject=result.detected_subject,
                confidence=result.confidence,
            )
            return result

        except Exception as exc:
            log.error("subject_detector.llm_failed", error=str(exc))
            return SubjectDetectionResult(
                detected_subject=SubjectEnum.mathematics,
                confidence=0.3,
                alternative_subjects=[],
                reasoning="LLM detection failed; defaulted to mathematics.",
            )


subject_detector = SubjectDetector()

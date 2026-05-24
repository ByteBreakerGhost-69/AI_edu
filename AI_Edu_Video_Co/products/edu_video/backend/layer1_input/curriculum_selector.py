# products/edu_video/backend/layer1_input/curriculum_selector.py
"""
Curriculum selector: signal-based fast path + LLM fallback.
Chooses the most appropriate curriculum framework for a given subject and input.
"""

from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from core.cost_tracker import CostTracker
from core.llm import llm_factory
from core.utils import safe_json_loads
from layer1_input.schemas import CurriculumEnum, CurriculumSelectionResult, SubjectEnum

__all__ = [
    "CurriculumSelector",
    "curriculum_selector",
    "CURRICULUM_SIGNALS",
]

logger = structlog.get_logger(__name__)

# --- Signal keywords per curriculum ---

CURRICULUM_SIGNALS: dict[CurriculumEnum, list[str]] = {
    CurriculumEnum.IB: [
        "IB", "International Baccalaureate", "TOK", "CAS", "extended essay",
        "HL", "SL", "IB Diploma", "Theory of Knowledge", "Higher Level",
        "Standard Level",
    ],
    CurriculumEnum.Cambridge: [
        "IGCSE", "A-Level", "O-Level", "Cambridge", "AS Level",
        "Cambridge International", "CAIE", "A2", "AS-Level",
        "Cambridge Assessment",
    ],
    CurriculumEnum.AP: [
        "AP ", "Advanced Placement", "College Board", "AP Exam",
        "AP course", "AP credit", "AP Calculus", "AP Physics",
        "AP Chemistry", "AP Biology",
    ],
}

# Languages that bias toward general unless an explicit curriculum signal is found
_GENERAL_BIAS_LANGUAGES = {"id", "ms"}

_SYSTEM_PROMPT = (
    "You are an expert in international educational curricula. "
    "Given a subject and a short text, determine the most appropriate curriculum framework. "
    "Respond ONLY with valid JSON — no markdown, no preamble."
)

_USER_PROMPT_TEMPLATE = (
    "Subject: {subject}\n"
    "Language: {language}\n"
    "Text snippet: {text}\n\n"
    "Which curriculum framework best fits this content?\n"
    "Options: IB, Cambridge, AP, general\n\n"
    "Consider: terminology used, level of study, geographic context, and phrasing.\n\n"
    "Respond ONLY as JSON:\n"
    '{{"selected_curriculum": "<IB|Cambridge|AP|general>", '
    '"reasoning": "<one sentence>", '
    '"key_standards": ["<standard1>", "<standard2>", "<standard3>"]}}'
)

# Fallback standards when LLM is not called
_DEFAULT_STANDARDS: dict[tuple[SubjectEnum, CurriculumEnum], list[str]] = {
    (SubjectEnum.mathematics, CurriculumEnum.IB): [
        "IB Math HL Topic 1 – Number & Algebra",
        "IB Math HL Topic 5 – Calculus",
        "IB Math HL Topic 3 – Geometry & Trigonometry",
    ],
    (SubjectEnum.mathematics, CurriculumEnum.Cambridge): [
        "Cambridge A-Level Mathematics 9709 – Pure Mathematics",
        "Cambridge A-Level Mathematics 9709 – Mechanics",
        "Cambridge A-Level Mathematics 9709 – Statistics",
    ],
    (SubjectEnum.mathematics, CurriculumEnum.AP): [
        "AP Calculus AB – FUN-3 (Antiderivatives)",
        "AP Calculus BC – LIM-1 (Limits)",
        "AP Statistics – UNC-1 (Probability)",
    ],
}


class CurriculumSelector:
    """
    Selects an appropriate curriculum framework.
    Uses explicit signal detection first; LLM only when inconclusive.
    """

    async def select_curriculum(
        self,
        subject: SubjectEnum,
        text: str,
        language: str = "en",
        job_id: str = "",
        cost_tracker: CostTracker | None = None,
    ) -> CurriculumSelectionResult:
        """
        Select curriculum from signals in text, language bias, or LLM fallback.

        Never raises — returns 'general' with low-confidence reasoning on error.
        """
        log = logger.bind(job_id=job_id, subject=subject)

        # 1. Explicit curriculum signal detection
        signal_result = self._signal_detect(text, log)
        if signal_result is not None:
            standards = self._get_standards(subject, signal_result.selected_curriculum)
            return CurriculumSelectionResult(
                selected_curriculum=signal_result.selected_curriculum,
                reasoning=signal_result.reasoning,
                key_standards=standards,
            )

        # 2. Language bias: Indonesian/Malay → general
        lang_base = language.split("-")[0].lower()
        if lang_base in _GENERAL_BIAS_LANGUAGES:
            log.info(
                "curriculum_selector.selected",
                method="language_bias",
                curriculum="general",
                language=language,
            )
            return CurriculumSelectionResult(
                selected_curriculum=CurriculumEnum.general,
                reasoning=(
                    f"Language '{language}' suggests local/general curriculum "
                    "with no explicit international curriculum signal detected."
                ),
                key_standards=["General educational standards apply."],
            )

        # 3. LLM fallback
        return await self._llm_select(subject, text, language, job_id, log, cost_tracker)

    def _signal_detect(
        self, text: str, log: Any
    ) -> CurriculumSelectionResult | None:
        """
        Scan text for curriculum keyword signals (case-insensitive substring match).
        Returns result with confidence=0.95 if found.
        """
        for curriculum, signals in CURRICULUM_SIGNALS.items():
            for signal in signals:
                if signal.lower() in text.lower():
                    log.info(
                        "curriculum_selector.selected",
                        method="signal",
                        curriculum=curriculum,
                        matched_signal=signal,
                    )
                    return CurriculumSelectionResult(
                        selected_curriculum=curriculum,
                        reasoning=f"Explicit curriculum signal detected: '{signal}'.",
                        key_standards=[],  # will be filled by caller
                    )
        return None

    async def _llm_select(
        self,
        subject: SubjectEnum,
        text: str,
        language: str,
        job_id: str,
        log: Any,
        cost_tracker: CostTracker | None,
    ) -> CurriculumSelectionResult:
        """Call Claude to select curriculum. Falls back to 'general' on error."""
        snippet = text[:300]
        llm = llm_factory.get_llm("claude")
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(
                content=_USER_PROMPT_TEMPLATE.format(
                    subject=subject.value,
                    language=language,
                    text=snippet,
                )
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
                raise ValueError("LLM returned non-JSON for curriculum selection")

            raw_curriculum = parsed.get("selected_curriculum", "general")
            valid_curricula = {c.value for c in CurriculumEnum}
            selected = (
                CurriculumEnum(raw_curriculum)
                if raw_curriculum in valid_curricula
                else CurriculumEnum.general
            )

            raw_standards = parsed.get("key_standards", [])
            standards = [str(s) for s in raw_standards if isinstance(s, str)][:5]
            if not standards:
                standards = self._get_standards(subject, selected)

            log.info(
                "curriculum_selector.selected",
                method="llm",
                curriculum=selected,
            )
            return CurriculumSelectionResult(
                selected_curriculum=selected,
                reasoning=str(parsed.get("reasoning", "LLM curriculum selection.")),
                key_standards=standards,
            )

        except Exception as exc:
            log.error("curriculum_selector.llm_failed", error=str(exc))
            return CurriculumSelectionResult(
                selected_curriculum=CurriculumEnum.general,
                reasoning="Curriculum selection failed; defaulted to general.",
                key_standards=["General educational standards apply."],
            )

    def _get_standards(
        self, subject: SubjectEnum, curriculum: CurriculumEnum
    ) -> list[str]:
        """Return pre-defined standards for known subject/curriculum combos."""
        key = (subject, curriculum)
        return _DEFAULT_STANDARDS.get(
            key, [f"{curriculum.value} {subject.value} standards apply."]
        )


curriculum_selector = CurriculumSelector()

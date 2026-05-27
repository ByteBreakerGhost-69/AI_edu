# products/edu_video/backend/layer3_rag/validators/fact_validator.py
"""
FactValidator: cross-checks factual claims against the RAG knowledge base.
The only validator that makes async external calls (RAGService + LLM).
"""

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from core.llm import llm_factory
from core.utils import safe_json_loads
from layer1_input.schemas import CurriculumEnum, SubjectEnum
from layer3_rag.validators.base_validator import (
    BaseValidator,
    ValidationIssue,
    ValidationReport,
    register_validator,
)

__all__ = ["FactValidator"]

logger = structlog.get_logger(__name__)

_MAX_CLAIMS_PER_VALIDATION = 5
_UNVERIFIED_CONFIDENCE_THRESHOLD = 0.3
_CLAIM_EXTRACT_PROMPT_TOKENS = 200
_CLAIM_EXTRACT_COMPLETION_TOKENS = 150
_CONTRADICTION_PROMPT_TOKENS = 100
_CONTRADICTION_COMPLETION_TOKENS = 20


@register_validator("fact")
class FactValidator(BaseValidator):
    """
    Extracts factual claims from content via LLM, then cross-checks
    each claim against the RAG knowledge base for contradictions.

    Lazy-imports RAGService to avoid circular imports at module load.
    """

    @property
    def validator_name(self) -> str:
        return "fact_validator"

    async def validate(
        self,
        content: str,
        context: dict,
    ) -> ValidationReport:
        location = f"scene_{context.get('scene_index', 0)}.narration_text"
        issues: list[ValidationIssue] = []

        try:
            # ---- Step 1: Extract claims --------------------------------- #
            claims = await self._extract_claims(content)

            if not claims:
                return self._make_report([], confidence=0.5)

            # ---- Step 2: Cross-check each claim ------------------------- #
            checked_confidences: list[float] = []

            from layer3_rag.rag_service import rag_service  # noqa: PLC0415

            subject_str = context.get("subject", "mathematics")
            curriculum_str = context.get("curriculum", "general")
            job_id = context.get("job_id", "")

            try:
                subject = SubjectEnum(subject_str)
            except ValueError:
                subject = SubjectEnum.mathematics
            try:
                curriculum = CurriculumEnum(curriculum_str)
            except ValueError:
                curriculum = CurriculumEnum.general

            for claim_obj in claims[:_MAX_CLAIMS_PER_VALIDATION]:
                claim_text = claim_obj.get("claim", "")
                if not claim_text:
                    continue

                try:
                    rag_result = await rag_service.query_for_fact_check(
                        claim=claim_text,
                        subject=subject,
                        curriculum=curriculum,
                        job_id=job_id,
                    )
                    checked_confidences.append(rag_result.confidence)

                    if rag_result.confidence < _UNVERIFIED_CONFIDENCE_THRESHOLD:
                        issues.append(self._warning(
                            code="unverified_claim",
                            message=f"Could not verify: '{claim_text[:120]}'",
                            location=location,
                            suggestion="Cross-check this claim against an authoritative source.",
                        ))
                    else:
                        contradiction = await self._check_contradiction(
                            claim=claim_text,
                            rag_answer=rag_result.synthesized_answer,
                        )
                        if contradiction:
                            issues.append(self._error(
                                code="factual_contradiction",
                                message=(
                                    f"Claim may contradict knowledge base: "
                                    f"'{claim_text[:120]}'"
                                ),
                                location=location,
                                suggestion=(
                                    f"Knowledge base suggests: "
                                    f"{rag_result.synthesized_answer[:200]}"
                                ),
                            ))

                except Exception as exc:
                    logger.warning(
                        "fact_validator.claim_check_failed",
                        claim=claim_text[:60],
                        error=str(exc),
                    )
                    # Skip this claim — don't flag as error
                    continue

            avg_confidence = (
                sum(checked_confidences) / len(checked_confidences)
                if checked_confidences
                else 0.5
            )
            return self._make_report(issues, confidence=avg_confidence)

        except Exception as exc:
            logger.error("fact_validator.crash", error=str(exc))
            return self._crash_report(str(exc))

    async def _extract_claims(self, content: str) -> list[dict]:
        """
        Use Claude to extract specific verifiable factual claims from content.
        Returns list of {claim, type} dicts.
        """
        system = (
            "Extract specific factual claims from this educational text. "
            "Focus only on verifiable facts: dates, numbers, scientific facts, "
            "historical events, named formulas, and physical constants. "
            "Ignore opinions, pedagogical style choices, and general explanations. "
            "Return ONLY valid JSON: "
            '{"claims": [{"claim": "...", "type": "date|number|scientific_fact|historical_event|formula"}]}'
        )
        user = content[:1000]

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
            if parsed and isinstance(parsed.get("claims"), list):
                return parsed["claims"]
        except Exception as exc:
            logger.warning("fact_validator.claim_extraction_failed", error=str(exc))

        return []

    async def _check_contradiction(
        self,
        claim: str,
        rag_answer: str,
    ) -> bool:
        """
        Ask Claude: does rag_answer contradict claim?
        Returns True if contradiction detected. Fails safe (returns False).
        """
        system = (
            "You are a fact-checking assistant. "
            "Does Text B contradict Claim A? "
            "A contradiction means Text B states the opposite or an incompatible fact. "
            "Mere absence of the claim in Text B is NOT a contradiction. "
            "Answer ONLY with one word: yes or no."
        )
        user = f"Claim A: {claim}\n\nText B: {rag_answer[:400]}"

        try:
            llm = llm_factory.get_llm()
            response = await llm.ainvoke([
                SystemMessage(content=system),
                HumanMessage(content=user),
            ])
            answer = str(response.content).strip().lower()
            return answer.startswith("yes")
        except Exception as exc:
            logger.warning("fact_validator.contradiction_check_failed", error=str(exc))
            return False

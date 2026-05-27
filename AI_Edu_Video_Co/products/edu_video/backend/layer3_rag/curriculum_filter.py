# products/edu_video/backend/layer3_rag/curriculum_filter.py
"""
CurriculumFilter: boosts chunks aligned with the target curriculum and
penalizes chunks from competing frameworks. Pure logic — no LLM calls.
"""

import structlog

from layer1_input.schemas import CurriculumEnum, SubjectEnum
from layer3_rag.rag_service import RetrievedChunk

__all__ = ["CurriculumFilter", "curriculum_filter"]

logger = structlog.get_logger(__name__)

_SCORE_FLOOR = 0.0
_SCORE_CAP = 1.0
_BOOST_PER_TERM = 0.05
_PENALTY_PER_TERM = 0.15
_MIN_SCORE_THRESHOLD = 0.10

_BOOST_TERMS: dict[CurriculumEnum, list[str]] = {
    CurriculumEnum.IB: [
        "IB", "International Baccalaureate", "HL", "SL",
        "TOK", "IB Diploma", "IBDP", "Theory of Knowledge",
    ],
    CurriculumEnum.Cambridge: [
        "Cambridge", "IGCSE", "A-Level", "AS Level",
        "O-Level", "CAIE", "Cambridge International",
    ],
    CurriculumEnum.AP: [
        "AP ", "Advanced Placement", "College Board",
        "AP Exam", "AP course", "AP credit",
    ],
    CurriculumEnum.general: [],
}

_EXCLUDE_TERMS: dict[CurriculumEnum, list[str]] = {
    CurriculumEnum.IB: ["Common Core", "GCSE", "SAT prep", "CAIE"],
    CurriculumEnum.Cambridge: ["IB Diploma", "AP Exam", "Common Core", "IBDP"],
    CurriculumEnum.AP: ["IGCSE", "IB Diploma", "GCSE", "CAIE"],
    CurriculumEnum.general: [],
}


class CurriculumFilter:
    """
    Adjusts chunk relevance_score based on curriculum alignment signals.
    Chunks that drop below _MIN_SCORE_THRESHOLD are removed entirely.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(self.__class__.__name__)

    def filter(
        self,
        chunks: list[RetrievedChunk],
        curriculum: CurriculumEnum,
        subject: SubjectEnum,
    ) -> list[RetrievedChunk]:
        """
        Boost/penalise chunks by curriculum signal, remove below-threshold chunks.
        Returns list sorted by adjusted relevance_score descending.
        """
        if not chunks:
            return []

        boost_terms = _BOOST_TERMS.get(curriculum, [])
        exclude_terms = _EXCLUDE_TERMS.get(curriculum, [])

        adjusted: list[RetrievedChunk] = []
        for chunk in chunks:
            content_lower = chunk.content.lower()
            score = chunk.relevance_score

            for term in boost_terms:
                if term.lower() in content_lower:
                    score += _BOOST_PER_TERM

            for term in exclude_terms:
                if term.lower() in content_lower:
                    score -= _PENALTY_PER_TERM

            score = round(min(max(score, _SCORE_FLOOR), _SCORE_CAP), 4)

            if score >= _MIN_SCORE_THRESHOLD:
                adjusted.append(
                    chunk.model_copy(update={"relevance_score": score})
                )

        result = sorted(adjusted, key=lambda c: c.relevance_score, reverse=True)
        self.log.info(
            "curriculum_filter.complete",
            input_count=len(chunks),
            output_count=len(result),
            curriculum=curriculum,
        )
        return result

    def get_curriculum_metadata_filter(
        self, curriculum: CurriculumEnum
    ) -> dict:
        """Return Qdrant payload filter dict for curriculum field."""
        if curriculum == CurriculumEnum.general:
            return {}
        return {"curriculum": curriculum.value}


curriculum_filter = CurriculumFilter()

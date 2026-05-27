# products/edu_video/backend/layer3_rag/query_expander.py
"""
QueryExpander: expands a single query into multiple variants to improve
retrieval recall. Combines rule-based curriculum prefix injection with
LLM semantic expansion.
"""

import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from core.llm import llm_factory
from core.utils import safe_json_loads
from layer1_input.schemas import CurriculumEnum, SubjectEnum

__all__ = ["QueryExpander"]

logger = structlog.get_logger(__name__)

_CURRICULUM_PREFIXES: dict[CurriculumEnum, str] = {
    CurriculumEnum.IB: "IB Diploma Programme",
    CurriculumEnum.Cambridge: "Cambridge A-Level",
    CurriculumEnum.AP: "Advanced Placement",
    CurriculumEnum.general: "",
}

_EXPAND_PROMPT_TOKENS = 150
_EXPAND_COMPLETION_TOKENS = 100


class QueryExpander:
    """
    Generates N query variants for hybrid retrieval.

    Tier 1 (free): curriculum-prefixed variant
    Tier 2 (LLM): semantic alternatives via Claude
    Deduplication preserves order so original query is always first.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(self.__class__.__name__)

    async def expand(
        self,
        query: str,
        subject: SubjectEnum,
        curriculum: CurriculumEnum,
        n_variants: int = 3,
    ) -> list[str]:
        """
        Expand query into up to n_variants unique variants.
        Always includes the original query as the first element.
        Falls back to [query, prefixed_query] on LLM failure.
        """
        log = self.log.bind(subject=subject, curriculum=curriculum)

        # ---- Tier 1: rule-based prefix ---------------------------------- #
        prefix = _CURRICULUM_PREFIXES.get(curriculum, "")
        if prefix:
            prefixed = f"{prefix} {subject.value} {query}".strip()
        else:
            prefixed = f"{subject.value} {query}".strip()

        # ---- Tier 2: LLM semantic expansion ----------------------------- #
        alternatives: list[str] = []
        n_needed = max(n_variants - 2, 1)  # original + prefixed already count for 2

        try:
            system = (
                f"Generate {n_needed} alternative phrasings of this educational query "
                f"for a {subject.value} {curriculum.value} course.\n"
                "Focus on: synonyms, more specific technical terms, related sub-concepts.\n"
                "Return ONLY a valid JSON array of strings. No explanation. No markdown."
            )
            user = f"Original query: {query}"

            llm = llm_factory.get_llm()
            response = await llm.ainvoke([
                SystemMessage(content=system),
                HumanMessage(content=user),
            ])
            raw = str(response.content).strip()

            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            parsed = json.loads(raw)
            if isinstance(parsed, list):
                alternatives = [
                    str(item).strip()
                    for item in parsed
                    if isinstance(item, str) and item.strip()
                ][:n_needed]

            log.info(
                "query_expander.llm_expanded",
                alternatives_count=len(alternatives),
            )

        except Exception as exc:
            log.warning("query_expander.llm_failed", error=str(exc))
            alternatives = []

        # ---- Combine + deduplicate (preserve order) --------------------- #
        all_queries = [query, prefixed] + alternatives
        seen: set[str] = set()
        unique: list[str] = []
        for q in all_queries:
            if q not in seen:
                seen.add(q)
                unique.append(q)

        result = unique[:n_variants]
        log.info("query_expander.complete", variants=len(result))
        return result

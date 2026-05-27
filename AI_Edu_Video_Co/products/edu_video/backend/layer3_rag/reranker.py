# products/edu_video/backend/layer3_rag/reranker.py
"""
Reranker: rescores retrieved chunks using LLM cross-encoder pattern.
Only invoked when chunk count exceeds top_k — short lists sorted by
relevance_score directly (no LLM cost).
"""

import asyncio

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from core.llm import llm_factory
from core.utils import safe_json_loads
from layer3_rag.rag_service import RetrievedChunk

__all__ = ["Reranker", "reranker"]

logger = structlog.get_logger(__name__)

_MAX_CHUNKS_TO_SCORE = 10
_CONTENT_PREVIEW_CHARS = 500
_LLM_WEIGHT = 0.6
_RETRIEVAL_WEIGHT = 0.4


class Reranker:
    """
    LLM-based reranker using parallel chunk scoring.
    Falls back to retrieval score ordering on any LLM failure.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(self.__class__.__name__)

    async def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        """
        Rerank chunks by combined LLM relevance + retrieval score.
        If len(chunks) <= top_k, skip LLM and sort by relevance_score.
        """
        if not chunks:
            return []

        if len(chunks) <= top_k:
            return sorted(chunks, key=lambda c: c.relevance_score, reverse=True)

        log = self.log.bind(chunks_in=len(chunks), top_k=top_k)
        log.info("reranker.started")

        candidates = chunks[:_MAX_CHUNKS_TO_SCORE]

        try:
            scored_pairs = await asyncio.gather(
                *[self._score_chunk(query, chunk) for chunk in candidates],
                return_exceptions=True,
            )

            results: list[tuple[RetrievedChunk, float]] = []
            for chunk, outcome in zip(candidates, scored_pairs):
                if isinstance(outcome, Exception):
                    log.warning(
                        "reranker.chunk_score_failed",
                        chunk_id=chunk.chunk_id,
                        error=str(outcome),
                    )
                    # Fall back to retrieval score for this chunk
                    combined = chunk.relevance_score
                else:
                    llm_score = float(outcome)
                    combined = (
                        _LLM_WEIGHT * llm_score
                        + _RETRIEVAL_WEIGHT * chunk.relevance_score
                    )
                results.append((chunk, combined))

            results.sort(key=lambda x: x[1], reverse=True)

            # Update relevance_score with combined score
            reranked = []
            for chunk, combined in results[:top_k]:
                updated = chunk.model_copy(
                    update={"relevance_score": round(min(combined, 1.0), 4)}
                )
                reranked.append(updated)

            log.info("reranker.completed", chunks_returned=len(reranked))
            return reranked

        except Exception as exc:
            log.warning("reranker.failed_falling_back", error=str(exc))
            return sorted(chunks, key=lambda c: c.relevance_score, reverse=True)[:top_k]

    async def _score_chunk(
        self,
        query: str,
        chunk: RetrievedChunk,
    ) -> float:
        """
        Score a single chunk's relevance to the query using Claude.
        Returns a normalised score in [0.0, 1.0].
        """
        system = (
            "Rate the relevance of this educational text chunk to the query. "
            "Score from 0 to 10 where:\n"
            "  10 = directly and precisely answers the query\n"
            "   5 = related but not directly relevant\n"
            "   0 = completely unrelated\n"
            "Consider: factual relevance, educational depth, specificity.\n"
            "Respond ONLY as JSON: "
            '{"score": <integer 0-10>, "reason": "<one sentence>"}'
        )
        user = (
            f"Query: {query}\n\n"
            f"Chunk: {chunk.content[:_CONTENT_PREVIEW_CHARS]}"
        )

        llm = llm_factory.get_llm()
        response = await llm.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=user),
        ])
        raw = str(response.content).strip()
        parsed = safe_json_loads(raw)

        if parsed is None:
            # Strip fences and retry parse
            cleaned = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            parsed = safe_json_loads(cleaned)

        if parsed is None:
            return chunk.relevance_score  # fallback

        raw_score = parsed.get("score", 0)
        try:
            return max(0.0, min(float(raw_score) / 10.0, 1.0))
        except (TypeError, ValueError):
            return chunk.relevance_score


reranker = Reranker()

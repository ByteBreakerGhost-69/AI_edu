# products/edu_video/backend/layer3_rag/rag_service.py
"""
RAGService: unified entry point for all RAG queries in the pipeline.
Orchestrates query expansion → hybrid retrieval → curriculum filter →
reranking → LLM synthesis → Redis cache.

Called by:
  fact_checker_agent  → query_for_fact_check()
  memory_agent        → query_for_memory()
  curriculum_agent    → query() directly
"""

import hashlib
import json
from statistics import mean

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict

from core.config import get_settings
from core.database import _redis_client
from core.llm import llm_factory
from core.utils import utcnow
from layer1_input.schemas import CurriculumEnum, DifficultyEnum, SubjectEnum
from layer3_rag.curriculum_filter import CurriculumFilter
from layer3_rag.query_expander import QueryExpander
from layer3_rag.reranker import Reranker
from layer3_rag.retriever import HybridRetriever

__all__ = [
    "RAGService",
    "RAGQuery",
    "RAGResult",
    "RetrievedChunk",
    "rag_service",
]

logger = structlog.get_logger(__name__)
settings = get_settings()

_CACHE_TTL_SECONDS = 3600
_SYNTHESIS_PROMPT_TOKENS = 600
_SYNTHESIS_COMPLETION_TOKENS = 300
_CLAUDE_INPUT_COST = 0.000003
_CLAUDE_OUTPUT_COST = 0.000015


# --------------------------------------------------------------------------- #
# Pydantic models                                                              #
# --------------------------------------------------------------------------- #

class RetrievedChunk(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_id: str
    content: str
    source: str
    subject: str
    curriculum: str
    relevance_score: float
    metadata: dict


class RAGQuery(BaseModel):
    query: str
    subject: SubjectEnum
    curriculum: CurriculumEnum
    difficulty_level: DifficultyEnum
    job_id: str
    top_k: int = 5
    use_cache: bool = True


class RAGResult(BaseModel):
    query: str
    retrieved_chunks: list[RetrievedChunk]
    synthesized_answer: str
    sources: list[str]
    confidence: float
    cost_usd: float
    cache_hit: bool


# --------------------------------------------------------------------------- #
# RAGService                                                                   #
# --------------------------------------------------------------------------- #

class RAGService:
    """
    Unified RAG entry point. All agents call this — never Qdrant directly.
    Caches results in Redis to avoid redundant LLM calls and Qdrant searches.
    """

    def __init__(self) -> None:
        self.query_expander = QueryExpander()
        self.retriever = HybridRetriever()
        self.reranker = Reranker()
        self.curriculum_filter = CurriculumFilter()
        self.log = structlog.get_logger(__name__)

    async def query(self, rag_query: RAGQuery) -> RAGResult:
        """
        Full RAG pipeline: expand → retrieve → filter → rerank → synthesize.
        Returns cached result if available and use_cache=True.
        """
        log = self.log.bind(
            job_id=rag_query.job_id,
            subject=rag_query.subject,
            curriculum=rag_query.curriculum,
        )
        log.info("rag_service.query_started", query_preview=rag_query.query[:80])

        # ---- Step 1: Cache check ---------------------------------------- #
        cache_key = _build_cache_key(rag_query)
        if rag_query.use_cache:
            cached = await _get_cached(cache_key, log)
            if cached is not None:
                return cached

        # ---- Step 2: Query expansion ------------------------------------ #
        try:
            expanded_queries = await self.query_expander.expand(
                query=rag_query.query,
                subject=rag_query.subject,
                curriculum=rag_query.curriculum,
                n_variants=3,
            )
        except Exception as exc:
            log.warning("rag_service.query_expansion_failed", error=str(exc))
            expanded_queries = [rag_query.query]

        # ---- Step 3: Hybrid retrieval ----------------------------------- #
        try:
            raw_chunks = await self.retriever.retrieve(
                queries=expanded_queries,
                subject=rag_query.subject,
                top_k=rag_query.top_k * 2,
            )
        except Exception as exc:
            log.warning("rag_service.retrieval_failed", error=str(exc))
            raw_chunks = []

        # ---- Guard: empty index ----------------------------------------- #
        if not raw_chunks:
            log.warning("rag_service.no_chunks_retrieved")
            return _empty_result(rag_query)

        # ---- Step 4: Curriculum filter ---------------------------------- #
        try:
            filtered_chunks = self.curriculum_filter.filter(
                chunks=raw_chunks,
                curriculum=rag_query.curriculum,
                subject=rag_query.subject,
            )
        except Exception as exc:
            log.warning("rag_service.filter_failed", error=str(exc))
            filtered_chunks = raw_chunks

        # ---- Step 5: Rerank -------------------------------------------- #
        try:
            reranked_chunks = await self.reranker.rerank(
                query=rag_query.query,
                chunks=filtered_chunks,
                top_k=rag_query.top_k,
            )
        except Exception as exc:
            log.warning("rag_service.rerank_failed", error=str(exc))
            reranked_chunks = sorted(
                filtered_chunks,
                key=lambda c: c.relevance_score,
                reverse=True,
            )[: rag_query.top_k]

        # ---- Step 6: LLM synthesis -------------------------------------- #
        synthesized_answer, synthesis_cost = await self._synthesize(
            query=rag_query.query,
            chunks=reranked_chunks,
            log=log,
        )

        # ---- Step 7: Build result + cache ------------------------------- #
        result = RAGResult(
            query=rag_query.query,
            retrieved_chunks=reranked_chunks,
            synthesized_answer=synthesized_answer,
            sources=list(dict.fromkeys(c.source for c in reranked_chunks)),
            confidence=_calculate_confidence(reranked_chunks),
            cost_usd=synthesis_cost,
            cache_hit=False,
        )

        await _set_cached(cache_key, result, log)

        log.info(
            "rag_service.query_completed",
            chunks_returned=len(reranked_chunks),
            confidence=result.confidence,
            cost_usd=synthesis_cost,
        )
        return result

    async def query_for_fact_check(
        self,
        claim: str,
        subject: SubjectEnum,
        curriculum: CurriculumEnum,
        job_id: str,
    ) -> RAGResult:
        """
        Simplified RAG query for fact_checker_agent.
        top_k=3, cache disabled (facts must always be fresh).
        """
        return await self.query(
            RAGQuery(
                query=claim,
                subject=subject,
                curriculum=curriculum,
                difficulty_level=DifficultyEnum.intermediate,
                job_id=job_id,
                top_k=3,
                use_cache=False,
            )
        )

    async def query_for_memory(
        self,
        job_context: dict,
        subject: SubjectEnum,
        job_id: str,
    ) -> RAGResult:
        """
        Query for similar past educational content.
        Constructs a composite query from job context fields.
        Cache enabled — memory queries are stable per subject/topic.
        """
        query_text = " ".join(
            filter(None, [
                job_context.get("title", ""),
                job_context.get("input_text", "")[:200],
                subject.value,
            ])
        ).strip()

        return await self.query(
            RAGQuery(
                query=query_text,
                subject=subject,
                curriculum=CurriculumEnum(
                    job_context.get("curriculum", "general")
                ),
                difficulty_level=DifficultyEnum(
                    job_context.get("difficulty_level", "intermediate")
                ),
                job_id=job_id,
                top_k=3,
                use_cache=True,
            )
        )

    async def _synthesize(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        log,
    ) -> tuple[str, float]:
        """
        Call Claude to synthesize a grounded answer from retrieved chunks.
        Returns (answer_text, cost_usd). Falls back to chunk concatenation on failure.
        """
        if not chunks:
            return "No relevant curriculum content found.", 0.0

        context_parts = []
        for i, chunk in enumerate(chunks[:5], 1):
            context_parts.append(f"[{i}] (Source: {chunk.source})\n{chunk.content}")
        context = "\n\n".join(context_parts)

        system = (
            "You are an educational content expert with access to curriculum materials. "
            "Using ONLY the provided context passages, answer the educational query accurately. "
            "If the context is insufficient to answer confidently, say so explicitly. "
            "Cite sources using [N] notation where N is the passage number. "
            "Respond in plain text, maximum 300 words. No markdown headers."
        )
        user = f"Query: {query}\n\nContext passages:\n{context}"

        try:
            llm = llm_factory.get_llm()
            response = await llm.ainvoke([
                SystemMessage(content=system),
                HumanMessage(content=user),
            ])
            answer = str(response.content).strip()
            cost = (
                _SYNTHESIS_PROMPT_TOKENS * _CLAUDE_INPUT_COST
                + _SYNTHESIS_COMPLETION_TOKENS * _CLAUDE_OUTPUT_COST
            )
            return answer, cost

        except Exception as exc:
            log.warning("rag_service.synthesis_failed", error=str(exc))
            # Fallback: return the most relevant chunk content
            return chunks[0].content[:500], 0.0


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _build_cache_key(rag_query: RAGQuery) -> str:
    """Stable MD5 cache key from query content — not job_id (jobs share queries)."""
    raw = f"{rag_query.query}|{rag_query.subject}|{rag_query.curriculum}|{rag_query.top_k}"
    digest = hashlib.md5(raw.encode()).hexdigest()
    return f"rag:cache:{digest}"


def _calculate_confidence(chunks: list[RetrievedChunk]) -> float:
    """
    Confidence based on mean relevance of top-3 chunks plus a
    chunk-count bonus (more supporting chunks = higher confidence).
    """
    if not chunks:
        return 0.0
    top3_scores = [c.relevance_score for c in chunks[:3]]
    avg_relevance = mean(top3_scores)
    chunk_count_bonus = min(len(chunks) / 5, 1.0) * 0.1
    return round(min(avg_relevance + chunk_count_bonus, 1.0), 4)


def _empty_result(rag_query: RAGQuery) -> RAGResult:
    return RAGResult(
        query=rag_query.query,
        retrieved_chunks=[],
        synthesized_answer=(
            "No curriculum content indexed yet. "
            "Run the ingestion pipeline before generating videos."
        ),
        sources=[],
        confidence=0.0,
        cost_usd=0.0,
        cache_hit=False,
    )


async def _get_cached(cache_key: str, log) -> RAGResult | None:
    try:
        if _redis_client is None:
            return None
        raw = await _redis_client.get(cache_key)
        if raw:
            log.info("rag_service.cache_hit", key=cache_key)
            data = json.loads(raw)
            data["cache_hit"] = True
            return RAGResult(**data)
    except Exception as exc:
        log.warning("rag_service.cache_get_failed", error=str(exc))
    return None


async def _set_cached(cache_key: str, result: RAGResult, log) -> None:
    try:
        if _redis_client is None:
            return
        await _redis_client.setex(
            cache_key,
            _CACHE_TTL_SECONDS,
            result.model_dump_json(),
        )
        log.debug("rag_service.cache_set", key=cache_key, ttl=_CACHE_TTL_SECONDS)
    except Exception as exc:
        log.warning("rag_service.cache_set_failed", error=str(exc))


rag_service = RAGService()

# products/edu_video/backend/layer3_rag/retriever.py
"""
HybridRetriever: combines dense vector search (Qdrant) with sparse
keyword search (BM25) via Reciprocal Rank Fusion.
"""

import time
from typing import Any

import structlog
from rank_bm25 import BM25Okapi

from core.llm import llm_factory
from core.qdrant import get_qdrant_client
from core.utils import generate_uuid
from layer1_input.schemas import SubjectEnum
from layer3_rag.rag_service import RetrievedChunk

__all__ = ["HybridRetriever", "hybrid_retriever"]

logger = structlog.get_logger(__name__)

_BM25_MIN_SCORE: float = 0.1
_BM25_CACHE_TTL_SECONDS: int = 3600
_BM25_MAX_CORPUS_SIZE: int = 1000
_RRF_K: int = 60


class _BM25CacheEntry:
    def __init__(self, index: BM25Okapi, corpus: list[dict]) -> None:
        self.index = index
        self.corpus = corpus  # list of {chunk_id, content, payload}
        self.built_at = time.time()

    def is_stale(self) -> bool:
        return (time.time() - self.built_at) > _BM25_CACHE_TTL_SECONDS


class HybridRetriever:
    """
    Retrieves chunks using dense (Qdrant) + sparse (BM25) search,
    fused with Reciprocal Rank Fusion for final ranking.
    """

    def __init__(self) -> None:
        self._bm25_cache: dict[str, _BM25CacheEntry] = {}
        self.log = structlog.get_logger(self.__class__.__name__)

    async def retrieve(
        self,
        queries: list[str],
        subject: SubjectEnum,
        top_k: int = 10,
    ) -> list[RetrievedChunk]:
        """
        Run hybrid retrieval across all query variants.
        Returns up to top_k deduplicated chunks ranked by RRF score.
        """
        log = self.log.bind(subject=subject, query_count=len(queries), top_k=top_k)
        log.info("retriever.started")

        # ---- Dense retrieval -------------------------------------------- #
        dense_results: list[tuple[str, float]] = []  # (chunk_id, score)
        dense_payload_map: dict[str, dict] = {}

        try:
            embedding_model = llm_factory.get_embedding_model()
            qdrant = get_qdrant_client()

            for query in queries:
                vector = await embedding_model.aembed_query(query)
                hits = await qdrant.search_vectors(
                    query_vector=vector,
                    top_k=top_k,
                    filter_payload={"subject": subject.value},
                )
                for hit in hits:
                    cid = str(hit.id)
                    score = float(hit.score)
                    # Keep best score per chunk_id
                    existing = next(
                        (s for cid2, s in dense_results if cid2 == cid), None
                    )
                    if existing is None:
                        dense_results.append((cid, score))
                        dense_payload_map[cid] = hit.payload or {}
                    elif score > existing:
                        dense_results = [
                            (c, s) if c != cid else (c, score)
                            for c, s in dense_results
                        ]

            dense_results.sort(key=lambda x: x[1], reverse=True)
            log.info("retriever.dense_complete", chunks=len(dense_results))

        except Exception as exc:
            log.warning("retriever.dense_failed", error=str(exc))

        # ---- Sparse retrieval (BM25) ------------------------------------ #
        sparse_results: list[tuple[str, float]] = []  # (chunk_id, bm25_score)

        try:
            cache_entry = await self._get_or_build_bm25(subject, log)
            if cache_entry is not None:
                for query in queries:
                    tokenized = query.lower().split()
                    scores = cache_entry.index.get_scores(tokenized)
                    for idx, score in enumerate(scores):
                        if score > _BM25_MIN_SCORE and idx < len(cache_entry.corpus):
                            cid = cache_entry.corpus[idx]["chunk_id"]
                            existing = next(
                                (s for c, s in sparse_results if c == cid), None
                            )
                            if existing is None:
                                sparse_results.append((cid, float(score)))
                                # Populate payload map if not already there
                                if cid not in dense_payload_map:
                                    dense_payload_map[cid] = cache_entry.corpus[idx].get(
                                        "payload", {}
                                    )
                            elif float(score) > existing:
                                sparse_results = [
                                    (c, s) if c != cid else (c, float(score))
                                    for c, s in sparse_results
                                ]

                sparse_results.sort(key=lambda x: x[1], reverse=True)
                log.info("retriever.sparse_complete", chunks=len(sparse_results))

        except Exception as exc:
            log.warning("retriever.sparse_failed", error=str(exc))

        # ---- RRF fusion ------------------------------------------------- #
        fused = _reciprocal_rank_fusion(dense_results, sparse_results, k=_RRF_K)
        fused_top = fused[:top_k]

        # ---- Build RetrievedChunk objects ------------------------------- #
        chunks: list[RetrievedChunk] = []
        for chunk_id, rrf_score in fused_top:
            payload = dense_payload_map.get(chunk_id, {})
            chunks.append(RetrievedChunk(
                chunk_id=chunk_id,
                content=str(payload.get("content", "")),
                source=str(payload.get("source", "unknown")),
                subject=str(payload.get("subject", subject.value)),
                curriculum=str(payload.get("curriculum", "general")),
                relevance_score=round(min(rrf_score, 1.0), 4),
                metadata=dict(payload.get("metadata", {})),
            ))

        log.info("retriever.complete", chunks_returned=len(chunks))
        return chunks

    async def _get_or_build_bm25(
        self,
        subject: SubjectEnum,
        log,
    ) -> _BM25CacheEntry | None:
        """
        Return cached BM25 index for subject, rebuilding if stale.
        Scrolls Qdrant for up to _BM25_MAX_CORPUS_SIZE chunks.
        Returns None if Qdrant is empty or scroll fails.
        """
        key = subject.value
        cached = self._bm25_cache.get(key)
        if cached and not cached.is_stale():
            return cached

        try:
            qdrant = get_qdrant_client()
            from core.config import get_settings  # noqa: PLC0415
            collection = get_settings().QDRANT_COLLECTION_NAME

            # Scroll Qdrant for corpus
            scroll_result = await qdrant._client.scroll(
                collection_name=collection,
                scroll_filter=None,
                limit=_BM25_MAX_CORPUS_SIZE,
                with_payload=True,
                with_vectors=False,
            )
            points = scroll_result[0]  # (points, next_page_offset)

            corpus_docs: list[dict] = []
            for point in points:
                payload = point.payload or {}
                if payload.get("subject") == subject.value:
                    corpus_docs.append({
                        "chunk_id": str(point.id),
                        "content": str(payload.get("content", "")),
                        "payload": payload,
                    })

            if not corpus_docs:
                log.info("retriever.bm25_empty_corpus", subject=subject.value)
                return None

            tokenized_corpus = [
                doc["content"].lower().split() for doc in corpus_docs
            ]
            index = BM25Okapi(tokenized_corpus)
            entry = _BM25CacheEntry(index=index, corpus=corpus_docs)
            self._bm25_cache[key] = entry

            log.info(
                "retriever.bm25_built",
                subject=subject.value,
                corpus_size=len(corpus_docs),
            )
            return entry

        except Exception as exc:
            log.warning("retriever.bm25_build_failed", error=str(exc))
            return None


# --------------------------------------------------------------------------- #
# RRF fusion                                                                   #
# --------------------------------------------------------------------------- #

def _reciprocal_rank_fusion(
    dense: list[tuple[str, float]],
    sparse: list[tuple[str, float]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """
    Reciprocal Rank Fusion: RRF(d) = Σ 1/(k + rank(d))
    Higher score = appeared near the top in multiple ranked lists.
    Returns list of (chunk_id, rrf_score) sorted descending.
    """
    rrf_scores: dict[str, float] = {}

    for rank, (chunk_id, _) in enumerate(dense, 1):
        rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + 1.0 / (k + rank)

    for rank, (chunk_id, _) in enumerate(sparse, 1):
        rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + 1.0 / (k + rank)

    # Normalise to [0, 1] range for consistency with relevance_score field
    if rrf_scores:
        max_score = max(rrf_scores.values())
        if max_score > 0:
            rrf_scores = {k: v / max_score for k, v in rrf_scores.items()}

    return sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)


hybrid_retriever = HybridRetriever()

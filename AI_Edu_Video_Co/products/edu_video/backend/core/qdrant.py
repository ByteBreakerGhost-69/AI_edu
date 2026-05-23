# products/edu_video/backend/core/qdrant.py
"""
Async Qdrant vector database client.
Singleton pattern — one client instance shared across the application.
"""

from typing import Any

import structlog
from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.http.models import (
    Distance,
    PointStruct,
    ScoredPoint,
    VectorParams,
)

from core.config import get_settings

__all__ = [
    "get_qdrant_client",
    "upsert_vectors",
    "search_vectors",
    "delete_vectors",
    "ensure_collection_exists",
]

logger = structlog.get_logger(__name__)
settings = get_settings()

_qdrant_client: AsyncQdrantClient | None = None


def get_qdrant_client() -> AsyncQdrantClient:
    """Return the singleton Qdrant async client. Initializes on first call."""
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = AsyncQdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            api_key=settings.QDRANT_API_KEY,
            timeout=30,
        )
        logger.info(
            "qdrant.client_initialized",
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
        )
    return _qdrant_client


async def ensure_collection_exists(vector_size: int) -> None:
    """
    Create the Qdrant collection if it doesn't already exist.
    Uses cosine distance for semantic similarity search.
    """
    client = get_qdrant_client()
    collection_name = settings.QDRANT_COLLECTION_NAME
    try:
        await client.get_collection(collection_name)
        logger.info("qdrant.collection_exists", collection=collection_name)
    except UnexpectedResponse:
        await client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=vector_size,
                distance=Distance.COSINE,
            ),
        )
        logger.info(
            "qdrant.collection_created",
            collection=collection_name,
            vector_size=vector_size,
        )


async def upsert_vectors(vectors: list[dict[str, Any]]) -> None:
    """
    Batch upsert vectors with payloads into the collection.

    Each dict must have keys: "id" (str), "vector" (list[float]), "payload" (dict).
    """
    client = get_qdrant_client()
    points = [
        PointStruct(
            id=v["id"],
            vector=v["vector"],
            payload=v.get("payload", {}),
        )
        for v in vectors
    ]
    try:
        await client.upsert(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            points=points,
            wait=True,
        )
        logger.info("qdrant.upserted", count=len(points))
    except Exception as exc:
        logger.error("qdrant.upsert_failed", error=str(exc), count=len(points))
        raise


async def search_vectors(
    query_vector: list[float],
    top_k: int = 5,
    filter_payload: dict[str, Any] | None = None,
) -> list[ScoredPoint]:
    """
    Semantic search against the collection.

    Args:
        query_vector: Embedding vector of the query.
        top_k: Number of top results to return.
        filter_payload: Optional Qdrant filter dict (e.g., {"curriculum": "IB"}).

    Returns:
        List of ScoredPoint objects ordered by descending similarity.
    """
    client = get_qdrant_client()
    qdrant_filter: models.Filter | None = None

    if filter_payload:
        conditions = [
            models.FieldCondition(
                key=k,
                match=models.MatchValue(value=v),
            )
            for k, v in filter_payload.items()
        ]
        qdrant_filter = models.Filter(must=conditions)

    try:
        results = await client.search(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            query_vector=query_vector,
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        )
        logger.info("qdrant.search_complete", top_k=top_k, results=len(results))
        return results
    except Exception as exc:
        logger.error("qdrant.search_failed", error=str(exc))
        raise


async def delete_vectors(ids: list[str]) -> None:
    """Delete vectors by their IDs from the collection."""
    client = get_qdrant_client()
    try:
        await client.delete(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            points_selector=models.PointIdsList(points=ids),
            wait=True,
        )
        logger.info("qdrant.deleted", count=len(ids))
    except Exception as exc:
        logger.error("qdrant.delete_failed", error=str(exc), ids=ids)
        raise

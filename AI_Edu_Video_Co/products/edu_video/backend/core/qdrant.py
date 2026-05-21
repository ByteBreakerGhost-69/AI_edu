"""
core/qdrant.py
Qdrant vector database client — singleton, collection management, and CRUD ops.
Embedding vectors are produced upstream (layer3_rag); this module is transport-only.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    CollectionInfo,
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointIdsList,
    PointStruct,
    Record,
    ScoredPoint,
    UpdateResult,
    VectorParams,
)

from core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton client
# ---------------------------------------------------------------------------

_qdrant_client: QdrantClient | None = None


def get_qdrant_client() -> QdrantClient:
    """
    Return the module-level singleton QdrantClient.
    Thread-safe for read-heavy workloads; not designed for multi-process sharing.
    Call close_qdrant() during app shutdown.
    """
    global _qdrant_client  # noqa: PLW0603

    if _qdrant_client is None:
        api_key: str | None = (
            settings.QDRANT_API_KEY.get_secret_value()
            if settings.QDRANT_API_KEY
            else None
        )
        try:
            _qdrant_client = QdrantClient(
                url=settings.qdrant_url,
                api_key=api_key,
                timeout=10,
                prefer_grpc=False,
            )
            # Lightweight connectivity check
            _qdrant_client.get_collections()
            logger.info("Qdrant client connected: %s", settings.qdrant_url)
        except Exception as exc:
            _qdrant_client = None
            logger.error("Failed to connect to Qdrant at %s: %s", settings.qdrant_url, exc)
            raise

    return _qdrant_client


def close_qdrant() -> None:
    """Close the Qdrant client and reset the singleton."""
    global _qdrant_client  # noqa: PLW0603

    if _qdrant_client is not None:
        try:
            _qdrant_client.close()
            logger.info("Qdrant client closed.")
        except Exception as exc:
            logger.warning("Error while closing Qdrant client: %s", exc)
        finally:
            _qdrant_client = None


# ---------------------------------------------------------------------------
# Collection management
# ---------------------------------------------------------------------------


def ensure_collection(
    collection_name: str | None = None,
    vector_size: int = 1536,
    distance: Distance = Distance.COSINE,
    on_disk_payload: bool = True,
) -> None:
    """
    Idempotently ensure a Qdrant collection exists with the given parameters.

    Args:
        collection_name: Target collection. Defaults to settings.QDRANT_COLLECTION_NAME.
        vector_size:     Dimensionality of embedding vectors (1536 = OpenAI ada-002 /
                         text-embedding-3-small; 768 = most sentence-transformers).
        distance:        Similarity metric — COSINE, DOT, EUCLID, or MANHATTAN.
        on_disk_payload: Store payload on disk to reduce RAM usage in production.
    """
    name = collection_name or settings.QDRANT_COLLECTION_NAME
    client = get_qdrant_client()

    try:
        existing = {c.name for c in client.get_collections().collections}
        if name in existing:
            logger.debug("Qdrant collection '%s' already exists — skipping creation.", name)
            return

        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=vector_size, distance=distance),
            on_disk_payload=on_disk_payload,
        )
        logger.info(
            "Qdrant collection '%s' created (size=%d, distance=%s).",
            name,
            vector_size,
            distance.value,
        )
    except UnexpectedResponse as exc:
        logger.error("Qdrant API error while ensuring collection '%s': %s", name, exc)
        raise
    except Exception as exc:
        logger.error("Unexpected error ensuring collection '%s': %s", name, exc)
        raise


def get_collection_info(collection_name: str | None = None) -> CollectionInfo:
    """
    Return metadata for a collection (vector count, config, status, etc.).

    Args:
        collection_name: Defaults to settings.QDRANT_COLLECTION_NAME.
    """
    name = collection_name or settings.QDRANT_COLLECTION_NAME
    client = get_qdrant_client()

    try:
        info = client.get_collection(collection_name=name)
        logger.debug(
            "Collection '%s' info: vectors_count=%s, status=%s",
            name,
            info.vectors_count,
            info.status,
        )
        return info
    except UnexpectedResponse as exc:
        logger.error("Failed to retrieve info for collection '%s': %s", name, exc)
        raise


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------


def upsert_points(
    points: list[PointStruct],
    collection_name: str | None = None,
    wait: bool = True,
) -> UpdateResult:
    """
    Upsert (insert or overwrite) a batch of points into the collection.

    Args:
        points:          List of PointStruct with id, vector, and payload.
        collection_name: Defaults to settings.QDRANT_COLLECTION_NAME.
        wait:            Block until the operation is indexed.

    Returns:
        UpdateResult with operation_id and status.
    """
    name = collection_name or settings.QDRANT_COLLECTION_NAME
    client = get_qdrant_client()

    if not points:
        logger.warning("upsert_points called with empty list — skipping.")
        return UpdateResult(operation_id=0, status=models.UpdateStatus.COMPLETED)

    try:
        result = client.upsert(collection_name=name, points=points, wait=wait)
        logger.debug("Upserted %d points into '%s'.", len(points), name)
        return result
    except UnexpectedResponse as exc:
        logger.error("Qdrant upsert failed for collection '%s': %s", name, exc)
        raise
    except Exception as exc:
        logger.error("Unexpected error during upsert into '%s': %s", name, exc)
        raise


def delete_points(
    ids: list[str | int],
    collection_name: str | None = None,
    wait: bool = True,
) -> UpdateResult:
    """
    Delete points by their IDs.

    Args:
        ids:             List of point IDs (str UUID or int).
        collection_name: Defaults to settings.QDRANT_COLLECTION_NAME.
        wait:            Block until the operation completes.
    """
    name = collection_name or settings.QDRANT_COLLECTION_NAME
    client = get_qdrant_client()

    if not ids:
        logger.warning("delete_points called with empty id list — skipping.")
        return UpdateResult(operation_id=0, status=models.UpdateStatus.COMPLETED)

    try:
        result = client.delete(
            collection_name=name,
            points_selector=PointIdsList(points=ids),  # type: ignore[arg-type]
            wait=wait,
        )
        logger.debug("Deleted %d points from '%s'.", len(ids), name)
        return result
    except UnexpectedResponse as exc:
        logger.error("Qdrant delete failed for collection '%s': %s", name, exc)
        raise
    except Exception as exc:
        logger.error("Unexpected error during delete from '%s': %s", name, exc)
        raise


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


def search(
    query_vector: list[float],
    collection_name: str | None = None,
    limit: int = 10,
    score_threshold: float | None = None,
    query_filter: Filter | None = None,
    with_payload: bool = True,
    with_vectors: bool = False,
) -> list[ScoredPoint]:
    """
    Nearest-neighbour vector search.

    Args:
        query_vector:    Embedding vector to search against.
        collection_name: Defaults to settings.QDRANT_COLLECTION_NAME.
        limit:           Maximum number of results to return.
        score_threshold: Minimum similarity score (0–1 for cosine).
        query_filter:    Optional metadata pre-filter (Qdrant Filter object).
        with_payload:    Include payload in results.
        with_vectors:    Include stored vectors in results (increases response size).

    Returns:
        List of ScoredPoint sorted by descending similarity.
    """
    name = collection_name or settings.QDRANT_COLLECTION_NAME
    client = get_qdrant_client()

    try:
        results = client.search(
            collection_name=name,
            query_vector=query_vector,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=query_filter,
            with_payload=with_payload,
            with_vectors=with_vectors,
        )
        logger.debug(
            "Vector search in '%s' returned %d results (limit=%d).",
            name,
            len(results),
            limit,
        )
        return results
    except UnexpectedResponse as exc:
        logger.error("Qdrant search failed for collection '%s': %s", name, exc)
        raise
    except Exception as exc:
        logger.error("Unexpected error during search in '%s': %s", name, exc)
        raise


def get_point(
    point_id: str | int,
    collection_name: str | None = None,
    with_vectors: bool = False,
) -> Optional[Record]:
    """
    Retrieve a single point by ID.

    Returns None if the point does not exist.

    Args:
        point_id:        Point UUID (str) or integer ID.
        collection_name: Defaults to settings.QDRANT_COLLECTION_NAME.
        with_vectors:    Include the stored vector in the response.
    """
    name = collection_name or settings.QDRANT_COLLECTION_NAME
    client = get_qdrant_client()

    try:
        results = client.retrieve(
            collection_name=name,
            ids=[point_id],  # type: ignore[list-item]
            with_payload=True,
            with_vectors=with_vectors,
        )
        if not results:
            logger.debug("Point '%s' not found in collection '%s'.", point_id, name)
            return None
        return results[0]
    except UnexpectedResponse as exc:
        logger.error(
            "Qdrant retrieve failed for point '%s' in '%s': %s", point_id, name, exc
        )
        raise
    except Exception as exc:
        logger.error(
            "Unexpected error retrieving point '%s' from '%s': %s", point_id, name, exc
        )
        raise


def scroll_points(
    collection_name: str | None = None,
    query_filter: Filter | None = None,
    limit: int = 100,
    offset: str | int | None = None,
    with_payload: bool = True,
    with_vectors: bool = False,
) -> tuple[list[Record], str | int | None]:
    """
    Paginate through all points in a collection (no vector query).

    Returns:
        Tuple of (records, next_page_offset).
        next_page_offset is None when the last page is reached.
    """
    name = collection_name or settings.QDRANT_COLLECTION_NAME
    client = get_qdrant_client()

    try:
        records, next_offset = client.scroll(
            collection_name=name,
            scroll_filter=query_filter,
            limit=limit,
            offset=offset,  # type: ignore[arg-type]
            with_payload=with_payload,
            with_vectors=with_vectors,
        )
        logger.debug(
            "Scrolled %d points from '%s' (next_offset=%s).",
            len(records),
            name,
            next_offset,
        )
        return records, next_offset
    except UnexpectedResponse as exc:
        logger.error("Qdrant scroll failed for collection '%s': %s", name, exc)
        raise
    except Exception as exc:
        logger.error("Unexpected error during scroll in '%s': %s", name, exc)
        raise


# ---------------------------------------------------------------------------
# Convenience filter builder (used by layer3_rag)
# ---------------------------------------------------------------------------


def build_filter(field: str, value: str | int | bool) -> Filter:
    """
    Build a simple equality Filter for a single payload field.

    Example::

        f = build_filter("job_id", "abc-123")
        results = search(vec, query_filter=f)
    """
    return Filter(
        must=[
            FieldCondition(
                key=field,
                match=MatchValue(value=value),
            )
        ]
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: list[str] = [
    # Client lifecycle
    "get_qdrant_client",
    "close_qdrant",
    # Collection management
    "ensure_collection",
    "get_collection_info",
    # Write
    "upsert_points",
    "delete_points",
    # Read
    "search",
    "get_point",
    "scroll_points",
    # Helpers
    "build_filter",
              ]


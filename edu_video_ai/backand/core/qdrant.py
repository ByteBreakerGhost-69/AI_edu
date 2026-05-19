"""
backend/core/qdrant.py

Manages the async Qdrant vector-database client and collection bootstrap.

Responsibilities:
  - Expose a lazily-initialised async QdrantClient singleton.
  - On startup, ensure the default collection exists with the correct
    vector size and distance metric; create it if absent.
  - Provide helper functions for collection management used by Layer 3 (RAG).
"""

import logging
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

from backend.core.config import settings

logger = logging.getLogger(__name__)

# ── Module-level singleton ────────────────────────────────────────────────────

_qdrant_client: AsyncQdrantClient | None = None


# ── Collection schema constants ───────────────────────────────────────────────

DISTANCE_METRIC = qmodels.Distance.COSINE

# Payload index definitions per domain partition
# Each science domain is stored in the same collection but filterable by
# the "domain" payload field — avoids collection-per-domain proliferation.
DEFAULT_PAYLOAD_INDEXES: list[tuple[str, qmodels.PayloadSchemaType]] = [
    ("domain", qmodels.PayloadSchemaType.KEYWORD),
    ("education_level", qmodels.PayloadSchemaType.KEYWORD),
    ("source_type", qmodels.PayloadSchemaType.KEYWORD),
    ("language", qmodels.PayloadSchemaType.KEYWORD),
]


# ── Lifecycle ─────────────────────────────────────────────────────────────────


async def init_qdrant_client() -> None:
    """
    Initialise the async Qdrant client and ensure the default collection exists.
    Call this during application startup.
    """
    global _qdrant_client

    logger.info("Initialising Qdrant async client at %s …", settings.qdrant_url)

    _qdrant_client = AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,   # None → no auth (local instance)
        timeout=30,
    )

    # Verify connectivity
    try:
        info = await _qdrant_client.get_collections()
        existing = {c.name for c in info.collections}
        logger.info(
            "Qdrant connection OK. Existing collections: %s",
            existing or "none",
        )
    except Exception as exc:
        raise RuntimeError(
            f"Cannot reach Qdrant at {settings.qdrant_url}: {exc}"
        ) from exc

    # Bootstrap default collection
    await ensure_collection(
        collection_name=settings.qdrant_default_collection,
        vector_size=settings.qdrant_vector_size,
    )


async def close_qdrant_client() -> None:
    """
    Close the Qdrant client gracefully.
    Call this during application shutdown.
    """
    global _qdrant_client
    if _qdrant_client is not None:
        await _qdrant_client.close()
        _qdrant_client = None
        logger.info("Qdrant client closed.")


# ── Public Accessors ──────────────────────────────────────────────────────────


def get_qdrant_client() -> AsyncQdrantClient:
    """
    Return the shared async Qdrant client.
    Raises RuntimeError if called before `init_qdrant_client()`.
    """
    if _qdrant_client is None:
        raise RuntimeError(
            "Qdrant client not initialised. "
            "Ensure `init_qdrant_client()` is called during app startup."
        )
    return _qdrant_client


# ── Collection Management ─────────────────────────────────────────────────────


async def ensure_collection(
    collection_name: str,
    vector_size: int,
    distance: qmodels.Distance = DISTANCE_METRIC,
    recreate: bool = False,
) -> None:
    """
    Check whether `collection_name` exists in Qdrant; create it if not.

    Args:
        collection_name: Target collection name.
        vector_size:     Embedding dimension (must match your embedding model).
        distance:        Distance metric (default COSINE).
        recreate:        If True, drop and recreate the collection.
                         DANGEROUS in production — use only in tests.
    """
    client = get_qdrant_client()

    if recreate:
        logger.warning(
            "Recreating collection '%s' — all existing vectors will be lost.",
            collection_name,
        )
        await client.recreate_collection(
            collection_name=collection_name,
            vectors_config=qmodels.VectorParams(
                size=vector_size,
                distance=distance,
            ),
        )
        await _create_payload_indexes(collection_name)
        return

    # Check existence
    try:
        await client.get_collection(collection_name=collection_name)
        logger.info("Qdrant collection '%s' already exists — skipping creation.", collection_name)
        return
    except (UnexpectedResponse, Exception) as exc:
        # qdrant-client raises an exception when the collection is not found
        if "Not found" not in str(exc) and "doesn't exist" not in str(exc):
            # Re-raise unexpected errors
            raise

    # Create
    logger.info(
        "Creating Qdrant collection '%s' (vector_size=%d, distance=%s) …",
        collection_name,
        vector_size,
        distance.value,
    )
    await client.create_collection(
        collection_name=collection_name,
        vectors_config=qmodels.VectorParams(
            size=vector_size,
            distance=distance,
        ),
        # Optimise for retrieval speed at the cost of slightly more RAM
        optimizers_config=qmodels.OptimizersConfigDiff(
            indexing_threshold=20_000,
        ),
        hnsw_config=qmodels.HnswConfigDiff(
            m=16,
            ef_construct=100,
            full_scan_threshold=10_000,
        ),
    )

    await _create_payload_indexes(collection_name)
    logger.info("Collection '%s' created successfully.", collection_name)


async def _create_payload_indexes(collection_name: str) -> None:
    """Create keyword payload indexes to enable fast domain-level filtering."""
    client = get_qdrant_client()
    for field_name, schema_type in DEFAULT_PAYLOAD_INDEXES:
        await client.create_payload_index(
            collection_name=collection_name,
            field_name=field_name,
            field_schema=schema_type,
        )
        logger.debug(
            "Payload index created: %s.%s (%s)",
            collection_name,
            field_name,
            schema_type.value,
        )


async def collection_info(collection_name: str) -> dict[str, Any]:
    """
    Return a concise summary of a collection's status.
    Useful for health-check endpoints.
    """
    client = get_qdrant_client()
    info = await client.get_collection(collection_name=collection_name)
    return {
        "name": collection_name,
        "vectors_count": info.vectors_count,
        "indexed_vectors_count": info.indexed_vectors_count,
        "status": info.status.value if info.status else "unknown",
        "vector_size": info.config.params.vectors.size,  # type: ignore[union-attr]
        "distance": info.config.params.vectors.distance.value,  # type: ignore[union-attr]
      }
      

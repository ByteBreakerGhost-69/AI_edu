# products/edu_video/backend/layer3_rag/ingestion/pipeline.py
"""
IngestionPipeline: orchestrates document ingestion from any source
into Qdrant with batched embedding generation.
"""

import asyncio
import time

import structlog
from pydantic import BaseModel, ConfigDict, Field

from core.llm import llm_factory
from core.qdrant import get_qdrant_client, upsert_vectors
from core.utils import chunk_list, generate_uuid, utcnow
from layer1_input.schemas import CurriculumEnum, DifficultyEnum, SubjectEnum

__all__ = [
    "IngestionPipeline",
    "IngestionSource",
    "IngestionResult",
    "ingestion_pipeline",
]

logger = structlog.get_logger(__name__)

_EMBED_BATCH_SIZE = 50
_UPSERT_BATCH_SIZE = 100
_MAX_CONCURRENT_INGESTIONS = 3


class IngestionSource(BaseModel):
    source_type: str  # "pdf" | "url" | "text" | "curriculum_doc"
    content: str
    subject: SubjectEnum
    curriculum: CurriculumEnum
    difficulty_level: DifficultyEnum = DifficultyEnum.intermediate
    source_name: str
    source_url: str | None = None
    metadata: dict = Field(default_factory=dict)


class IngestionResult(BaseModel):
    success: bool
    chunks_created: int
    vectors_upserted: int
    source_name: str
    error: str | None = None
    duration_seconds: float


class IngestionPipeline:
    """
    End-to-end document ingestion: chunk → embed → upsert to Qdrant.
    Idempotent: re-upserting the same chunk_id is safe (Qdrant upsert).
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(self.__class__.__name__)

    async def ingest(self, source: IngestionSource) -> IngestionResult:
        """
        Ingest a single source document.
        Routes to curriculum_ingestion or general chunker based on source_type.
        """
        log = self.log.bind(source_name=source.source_name, source_type=source.source_type)
        log.info("ingestion_pipeline.started")
        t0 = time.perf_counter()

        try:
            # ---- Step 1: Chunk ------------------------------------------ #
            if source.source_type == "curriculum_doc":
                from layer3_rag.ingestion.curriculum_ingestion import CurriculumIngestor  # noqa
                ingestor = CurriculumIngestor()
                chunks = await ingestor.ingest(source)
            else:
                from layer3_rag.ingestion.chunker import DocumentChunker  # noqa
                chunker = DocumentChunker()
                chunks = await chunker.chunk(source)

            if not chunks:
                log.warning("ingestion_pipeline.no_chunks_produced")
                return IngestionResult(
                    success=True,
                    chunks_created=0,
                    vectors_upserted=0,
                    source_name=source.source_name,
                    duration_seconds=time.perf_counter() - t0,
                )

            log.info("ingestion_pipeline.chunks_created", count=len(chunks))

            # ---- Step 2: Embed in batches of 50 ------------------------ #
            embedding_model = llm_factory.get_embedding_model()
            all_vectors: list[dict] = []

            for batch in chunk_list(chunks, _EMBED_BATCH_SIZE):
                texts = [c["content"] for c in batch]
                vectors = await embedding_model.aembed_documents(texts)
                for chunk, vector in zip(batch, vectors):
                    all_vectors.append({
                        "id": chunk["chunk_id"],
                        "vector": vector,
                        "payload": {
                            "content": chunk["content"],
                            "subject": source.subject.value,
                            "curriculum": source.curriculum.value,
                            "difficulty_level": source.difficulty_level.value,
                            "source": source.source_name,
                            "source_url": source.source_url,
                            "chunk_index": chunk["chunk_index"],
                            "metadata": {
                                **source.metadata,
                                **chunk.get("metadata", {}),
                            },
                        },
                    })

            log.info("ingestion_pipeline.embeddings_generated", count=len(all_vectors))

            # ---- Step 3: Upsert to Qdrant in batches of 100 ------------ #
            total_upserted = 0
            for batch in chunk_list(all_vectors, _UPSERT_BATCH_SIZE):
                await upsert_vectors(batch)
                total_upserted += len(batch)

            duration = round(time.perf_counter() - t0, 2)
            log.info(
                "ingestion_pipeline.completed",
                chunks=len(chunks),
                vectors=total_upserted,
                duration_seconds=duration,
            )

            return IngestionResult(
                success=True,
                chunks_created=len(chunks),
                vectors_upserted=total_upserted,
                source_name=source.source_name,
                duration_seconds=duration,
            )

        except Exception as exc:
            duration = round(time.perf_counter() - t0, 2)
            log.error("ingestion_pipeline.failed", error=str(exc))
            return IngestionResult(
                success=False,
                chunks_created=0,
                vectors_upserted=0,
                source_name=source.source_name,
                error=str(exc),
                duration_seconds=duration,
            )

    async def ingest_batch(
        self,
        sources: list[IngestionSource],
    ) -> list[IngestionResult]:
        """
        Ingest multiple sources concurrently (max _MAX_CONCURRENT_INGESTIONS at a time).
        """
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_INGESTIONS)

        async def _ingest_one(s: IngestionSource) -> IngestionResult:
            async with semaphore:
                return await self.ingest(s)

        return await asyncio.gather(*[_ingest_one(s) for s in sources])

    async def delete_source(self, source_name: str) -> int:
        """
        Delete all vectors where payload.source == source_name.
        Returns count of vectors deleted.
        """
        log = self.log.bind(source_name=source_name)
        try:
            from qdrant_client import models  # noqa: PLC0415
            qdrant = get_qdrant_client()
            from core.config import get_settings  # noqa: PLC0415
            collection = get_settings().QDRANT_COLLECTION_NAME

            result = await qdrant._client.delete(
                collection_name=collection,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="source",
                                match=models.MatchValue(value=source_name),
                            )
                        ]
                    )
                ),
                wait=True,
            )
            count = getattr(result, "deleted", 0) or 0
            log.info("ingestion_pipeline.source_deleted", count=count)
            return count
        except Exception as exc:
            log.error("ingestion_pipeline.delete_failed", error=str(exc))
            return 0


ingestion_pipeline = IngestionPipeline()

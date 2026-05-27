# products/edu_video/backend/layer3_rag/ingestion/curriculum_ingestion.py
"""
CurriculumIngestor: specialized ingestor for official curriculum documents.
Extracts structured standards via LLM and creates enriched chunks.
"""

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from core.llm import llm_factory
from core.utils import generate_uuid, safe_json_loads
from layer3_rag.ingestion.pipeline import IngestionSource

__all__ = ["CurriculumIngestor", "CurriculumStandard"]

logger = structlog.get_logger(__name__)

_WINDOW_SIZE = 2000
_WINDOW_OVERLAP = 200
_EXTRACT_PROMPT_TOKENS = 400
_EXTRACT_COMPLETION_TOKENS = 300


class CurriculumStandard(BaseModel):
    standard_id: str
    curriculum: str
    subject: str
    level: str
    topic: str
    subtopic: str
    keywords: list[str]
    difficulty_mapping: str


class CurriculumIngestor:
    """
    Processes official curriculum documents (IB guides, Cambridge syllabi,
    AP course descriptions) into two chunk types:
      1. Standards chunks — one per extracted standard (structured metadata)
      2. Base chunks — full-text sections for contextual retrieval
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(self.__class__.__name__)

    async def ingest(self, source: IngestionSource) -> list[dict]:
        """
        Extract curriculum standards + create base chunks.
        Returns combined list of chunk dicts for embedding.
        """
        log = self.log.bind(
            source_name=source.source_name,
            curriculum=source.curriculum,
            subject=source.subject,
        )
        log.info("curriculum_ingestor.started")

        # ---- Step 1: Extract standards via LLM -------------------------- #
        raw_standards = await self._extract_standards(source.content, source, log)

        # ---- Step 2: Deduplicate by standard_id ------------------------- #
        seen_ids: set[str] = set()
        deduped: list[dict] = []
        for std in raw_standards:
            sid = std.get("standard_id", generate_uuid())
            if sid not in seen_ids:
                seen_ids.add(sid)
                deduped.append(std)

        log.info(
            "curriculum_ingestor.standards_extracted",
            total=len(raw_standards),
            unique=len(deduped),
        )

        # ---- Step 3: Build standards chunks ----------------------------- #
        standard_chunks: list[dict] = []
        for i, std in enumerate(deduped):
            keywords = std.get("keywords", [])
            content = (
                f"{std.get('topic', '')}: {std.get('subtopic', '')}\n"
                f"Keywords: {', '.join(keywords)}"
            ).strip()

            standard_chunks.append({
                "chunk_id": generate_uuid(),
                "content": content,
                "chunk_index": i,
                "total_chunks": len(deduped),
                "metadata": {
                    "standard_id": std.get("standard_id", ""),
                    "curriculum": source.curriculum.value,
                    "subject": source.subject.value,
                    "level": std.get("level", ""),
                    "topic": std.get("topic", ""),
                    "is_curriculum_standard": True,
                    "keywords": keywords,
                    "difficulty_mapping": std.get("difficulty_mapping", "intermediate"),
                },
            })

        # ---- Step 4: Build full-text base chunks ------------------------ #
        from layer3_rag.ingestion.chunker import DocumentChunker  # noqa: PLC0415
        chunker = DocumentChunker()
        base_source = source.model_copy(update={"source_type": "pdf"})
        base_raw = await chunker.chunk(base_source)

        for chunk in base_raw:
            chunk.setdefault("metadata", {})
            chunk["metadata"]["is_curriculum_standard"] = False

        combined = standard_chunks + base_raw
        log.info(
            "curriculum_ingestor.complete",
            standard_chunks=len(standard_chunks),
            base_chunks=len(base_raw),
            total=len(combined),
        )
        return combined

    async def _extract_standards(
        self,
        content: str,
        source: IngestionSource,
        log,
    ) -> list[dict]:
        """
        Slide a window over the document and extract standards in each window.
        Returns deduplicated list of standard dicts.
        """
        system = (
            "You are an expert at parsing official educational curriculum documents. "
            f"Extract all learning standards from this {source.curriculum.value} "
            f"{source.subject.value} document section.\n\n"
            "For each standard found, return:\n"
            "  standard_id: unique code (e.g. 'IB-MATH-HL-1.1', 'AP-CALC-FUN-3')\n"
            "  level: 'HL'/'SL'/'A-Level'/'AS'/'AP' etc.\n"
            "  topic: broad topic name\n"
            "  subtopic: specific standard description\n"
            "  keywords: list of 3-8 relevant search keywords\n"
            "  difficulty_mapping: 'beginner'|'intermediate'|'advanced'\n\n"
            "Return ONLY valid JSON: "
            '{"standards": [{"standard_id":"...","level":"...","topic":"...",'
            '"subtopic":"...","keywords":[...],"difficulty_mapping":"..."}]}\n'
            "Return empty standards array if no structured standards found."
        )

        all_standards: list[dict] = []
        windows = list(_sliding_windows(content, _WINDOW_SIZE, _WINDOW_OVERLAP))

        for i, window in enumerate(windows):
            try:
                llm = llm_factory.get_llm()
                response = await llm.ainvoke([
                    SystemMessage(content=system),
                    HumanMessage(content=window),
                ])
                raw = str(response.content).strip()
                parsed = safe_json_loads(raw)
                if parsed is None:
                    cleaned = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                    parsed = safe_json_loads(cleaned)

                if parsed and isinstance(parsed.get("standards"), list):
                    # Inject curriculum/subject not always present in LLM output
                    for std in parsed["standards"]:
                        std.setdefault("curriculum", source.curriculum.value)
                        std.setdefault("subject", source.subject.value)
                    all_standards.extend(parsed["standards"])

            except Exception as exc:
                log.warning(
                    "curriculum_ingestor.window_extraction_failed",
                    window_index=i,
                    error=str(exc),
                )
                continue

        return all_standards


def _sliding_windows(
    text: str,
    window_size: int,
    overlap: int,
) -> list[str]:
    """Yield overlapping text windows of window_size chars."""
    windows = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + window_size, text_len)
        windows.append(text[start:end])
        if end >= text_len:
            break
        start = end - overlap
    return windows

# products/edu_video/backend/layer3_rag/ingestion/chunker.py
"""
DocumentChunker: splits raw documents into RAG-optimal chunks using
strategy selection based on source_type.
"""

import re
import unicodedata

import httpx
import structlog
from pydantic import BaseModel

from core.utils import generate_uuid
from layer3_rag.ingestion.pipeline import IngestionSource

__all__ = ["DocumentChunker", "DocumentChunk", "document_chunker"]

logger = structlog.get_logger(__name__)

_SLIDING_CHUNK_SIZE = 800
_SLIDING_OVERLAP = 150
_PARAGRAPH_MAX_CHUNK = 1000
_PARAGRAPH_MIN_MERGE = 100
_SECTION_MAX_CHARS = 1200

_PAGE_HEADER_FOOTER = re.compile(
    r"(?m)^(?:Page\s+\d+\s+of\s+\d+|^\d+\s*$|^-\s*\d+\s*-$)",
    re.IGNORECASE,
)
_SECTION_HEADER = re.compile(
    r"(?m)^(?:[A-Z][A-Z\s]{3,}$|.+:$|#{1,3}\s+.+|(?:\d+\.)+\d*\s+\w+)"
)


class DocumentChunk(BaseModel):
    chunk_id: str
    content: str
    chunk_index: int
    total_chunks: int
    char_count: int
    metadata: dict


class DocumentChunker:
    """
    Routes documents to the appropriate chunking strategy and returns
    a list of chunk dicts ready for embedding.
    """

    def __init__(self) -> None:
        self.log = structlog.get_logger(self.__class__.__name__)

    async def chunk(self, source: IngestionSource) -> list[dict]:
        """
        Chunk source content using strategy appropriate for source_type.
        Returns list of dicts (not DocumentChunk objects) for pipeline compatibility.
        """
        log = self.log.bind(source_name=source.source_name, source_type=source.source_type)

        content = source.content

        if source.source_type == "url":
            content = await self._fetch_url(source.content, log)

        content = self._clean_text(content)

        if source.source_type == "pdf":
            raw_chunks = self._chunk_by_section(content)
        elif source.source_type == "url":
            raw_chunks = self._chunk_by_paragraph(content)
        else:
            raw_chunks = self._chunk_by_sliding_window(content)

        # Patch total_chunks after generation
        total = len(raw_chunks)
        result = []
        for i, chunk in enumerate(raw_chunks):
            d = chunk.model_dump()
            d["total_chunks"] = total
            result.append(d)

        log.info("chunker.complete", strategy=source.source_type, chunks=len(result))
        return result

    def _chunk_by_sliding_window(
        self,
        text: str,
        chunk_size: int = _SLIDING_CHUNK_SIZE,
        overlap: int = _SLIDING_OVERLAP,
    ) -> list[DocumentChunk]:
        """Split text into overlapping windows, breaking at sentence boundaries."""
        chunks = []
        start = 0
        idx = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + chunk_size, text_len)

            # Find sentence boundary near end
            if end < text_len:
                boundary = text.rfind(".", start, end)
                if boundary > start + chunk_size // 2:
                    end = boundary + 1

            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(DocumentChunk(
                    chunk_id=generate_uuid(),
                    content=chunk_text,
                    chunk_index=idx,
                    total_chunks=0,  # patched later
                    char_count=len(chunk_text),
                    metadata={},
                ))
                idx += 1

            start = end - overlap if end < text_len else text_len

        return chunks

    def _chunk_by_paragraph(
        self,
        text: str,
        max_chunk_size: int = _PARAGRAPH_MAX_CHUNK,
    ) -> list[DocumentChunk]:
        """Split at double newlines, merging short paragraphs, splitting large ones."""
        paragraphs = re.split(r"\n{2,}", text)
        merged: list[str] = []
        buffer = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(para) < _PARAGRAPH_MIN_MERGE:
                buffer = (buffer + " " + para).strip()
            else:
                if buffer:
                    merged.append(buffer)
                    buffer = ""
                merged.append(para)

        if buffer:
            merged.append(buffer)

        chunks = []
        idx = 0
        for para in merged:
            if len(para) > max_chunk_size:
                sub_chunks = self._chunk_by_sliding_window(para)
                for sc in sub_chunks:
                    sc = sc.model_copy(update={"chunk_index": idx})
                    chunks.append(sc)
                    idx += 1
            else:
                chunks.append(DocumentChunk(
                    chunk_id=generate_uuid(),
                    content=para,
                    chunk_index=idx,
                    total_chunks=0,
                    char_count=len(para),
                    metadata={"type": "paragraph"},
                ))
                idx += 1

        return chunks

    def _chunk_by_section(self, text: str) -> list[DocumentChunk]:
        """Split at detected section headers, sub-chunking large sections."""
        lines = text.split("\n")
        sections: list[tuple[str, str]] = []  # (title, body)
        current_title = "Introduction"
        current_body: list[str] = []

        for line in lines:
            if _SECTION_HEADER.match(line.strip()) and len(line.strip()) < 100:
                if current_body:
                    sections.append((current_title, "\n".join(current_body).strip()))
                current_title = line.strip()
                current_body = []
            else:
                current_body.append(line)

        if current_body:
            sections.append((current_title, "\n".join(current_body).strip()))

        chunks = []
        idx = 0
        for title, body in sections:
            if not body:
                continue
            if len(body) > _SECTION_MAX_CHARS:
                sub_chunks = self._chunk_by_sliding_window(body)
                for sc in sub_chunks:
                    sc = sc.model_copy(update={
                        "chunk_index": idx,
                        "metadata": {"section": title},
                    })
                    chunks.append(sc)
                    idx += 1
            else:
                chunks.append(DocumentChunk(
                    chunk_id=generate_uuid(),
                    content=f"{title}\n{body}",
                    chunk_index=idx,
                    total_chunks=0,
                    char_count=len(body),
                    metadata={"section": title},
                ))
                idx += 1

        return chunks

    def _clean_text(self, text: str) -> str:
        """Remove page artifacts, normalize unicode, collapse whitespace."""
        text = _PAGE_HEADER_FOOTER.sub("", text)
        text = unicodedata.normalize("NFKC", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    async def _fetch_url(self, url: str, log) -> str:
        """Fetch URL content as plain text. Returns empty string on failure."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.text
        except Exception as exc:
            log.warning("chunker.url_fetch_failed", url=url, error=str(exc))
            return ""


document_chunker = DocumentChunker()

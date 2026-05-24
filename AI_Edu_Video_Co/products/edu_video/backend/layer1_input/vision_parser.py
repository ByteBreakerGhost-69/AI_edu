# products/edu_video/backend/layer1_input/vision_parser.py
"""
Vision parser: downloads an image from GCS, sends it to Claude vision,
and extracts structured educational content.
"""

import base64
import json
from typing import Any

import httpx
import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from core.config import get_settings
from core.cost_tracker import CostTracker
from core.llm import llm_factory
from core.utils import safe_json_loads
from layer1_input.schemas import ParsedImageContent, SubjectEnum

__all__ = [
    "VisionParser",
    "VisionParserError",
    "ImageTooLargeError",
    "ImageDownloadError",
    "vision_parser",
]

logger = structlog.get_logger(__name__)
settings = get_settings()

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB

_SYSTEM_PROMPT = (
    "You are analyzing an educational image. "
    "Extract all text, identify the educational subject, and classify the image type. "
    "Always respond with valid JSON only — no markdown, no preamble."
)

_USER_PROMPT = (
    "Extract the following from this educational image:\n"
    "1) All readable text (verbatim where possible)\n"
    "2) The educational subject\n"
    "3) Image type — choose exactly one: "
    "textbook_page / handwritten_notes / diagram / equation / mixed\n"
    "4) Your confidence from 0.0 to 1.0\n"
    "5) Any additional context that would help a teacher understand this material\n\n"
    "Respond ONLY as JSON with keys: "
    "extracted_text, detected_subject, image_type, confidence, additional_context"
)

_VALID_SUBJECTS = {s.value for s in SubjectEnum}
_VALID_IMAGE_TYPES = {"textbook_page", "handwritten_notes", "diagram", "equation", "mixed"}


# --- Exceptions ---

class VisionParserError(Exception):
    def __init__(self, message: str, job_id: str = "") -> None:
        super().__init__(message)
        self.job_id = job_id


class ImageTooLargeError(VisionParserError):
    pass


class ImageDownloadError(VisionParserError):
    pass


# --- Parser ---

class VisionParser:
    """Downloads an image and uses Claude vision to extract educational content."""

    async def parse_image_content(
        self,
        image_url: str,
        job_id: str,
        cost_tracker: CostTracker | None = None,
    ) -> ParsedImageContent:
        """
        Download image from GCS URL, analyse with Claude vision, return ParsedImageContent.

        Args:
            image_url: GCS HTTPS URL for the image.
            job_id: Used for cost tracking and structured logging.
            cost_tracker: Optional CostTracker instance. If None, cost is not recorded.

        Raises:
            ImageTooLargeError: Image exceeds 10 MB.
            ImageDownloadError: HTTP error downloading the image.
            VisionParserError: JSON parse failure after retry.
        """
        log = logger.bind(job_id=job_id, image_url="[masked]")
        log.info("vision_parser.download_start")

        image_bytes = await self._download_image(image_url, job_id)
        image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

        # Detect media type from URL suffix (Claude requires it)
        media_type = self._infer_media_type(image_url)

        raw_response = await self._call_claude_vision(image_b64, media_type, job_id, log)

        # Track cost regardless of parse outcome
        if cost_tracker:
            try:
                await cost_tracker.record_llm_cost(
                    user_id="system",
                    job_id=job_id,
                    provider="claude",
                    tokens=0,  # token count comes from TokenUsageCallback separately
                    cost_usd=0.0,
                )
            except Exception as exc:
                log.warning("vision_parser.cost_track_failed", error=str(exc))

        result = self._parse_response(raw_response, job_id, log)
        log.info(
            "vision_parser.complete",
            image_type=result.image_type,
            confidence=result.confidence,
            subject=result.detected_subject,
        )
        return result

    async def _download_image(self, image_url: str, job_id: str) -> bytes:
        """Stream-download image, enforcing 10 MB limit."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("GET", image_url) as response:
                    response.raise_for_status()
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        total += len(chunk)
                        if total > MAX_IMAGE_BYTES:
                            raise ImageTooLargeError(
                                f"Image exceeds 10 MB limit ({total} bytes).",
                                job_id=job_id,
                            )
                        chunks.append(chunk)
                    return b"".join(chunks)
        except ImageTooLargeError:
            raise
        except httpx.HTTPStatusError as exc:
            raise ImageDownloadError(
                f"HTTP {exc.response.status_code} downloading image.",
                job_id=job_id,
            ) from exc
        except httpx.RequestError as exc:
            raise ImageDownloadError(
                f"Network error downloading image: {exc}",
                job_id=job_id,
            ) from exc

    async def _call_claude_vision(
        self,
        image_b64: str,
        media_type: str,
        job_id: str,
        log: Any,
    ) -> str:
        """Send base64 image to Claude and return raw text response."""
        llm = llm_factory.get_llm("claude")

        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(
                content=[
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_b64}"
                        },
                    },
                    {"type": "text", "text": _USER_PROMPT},
                ]
            ),
        ]

        try:
            response = await llm.ainvoke(messages)
            return str(response.content)
        except Exception as exc:
            log.error("vision_parser.llm_call_failed", error=str(exc))
            raise VisionParserError(
                f"Claude vision call failed: {exc}", job_id=job_id
            ) from exc

    def _parse_response(
        self, raw: str, job_id: str, log: Any
    ) -> ParsedImageContent:
        """
        Parse Claude's JSON response into ParsedImageContent.
        Retries once with a stricter format reminder if initial parse fails.
        """
        parsed = safe_json_loads(raw)
        if parsed is None:
            log.warning("vision_parser.json_parse_failed_first_attempt")
            # Strip possible markdown fences and retry
            cleaned = raw.strip().removeprefix("```json").removesuffix("```").strip()
            parsed = safe_json_loads(cleaned)

        if parsed is None:
            raise VisionParserError(
                "Failed to parse Claude vision response as JSON after retry.",
                job_id=job_id,
            )

        # Coerce subject to enum or None
        raw_subject = parsed.get("detected_subject")
        detected_subject = None
        if isinstance(raw_subject, str) and raw_subject.lower() in _VALID_SUBJECTS:
            detected_subject = SubjectEnum(raw_subject.lower())

        # Coerce image_type
        raw_image_type = parsed.get("image_type", "mixed")
        image_type = (
            raw_image_type if raw_image_type in _VALID_IMAGE_TYPES else "mixed"
        )

        return ParsedImageContent(
            extracted_text=str(parsed.get("extracted_text", "")),
            detected_subject=detected_subject,
            image_type=image_type,
            confidence=float(parsed.get("confidence", 0.5)),
            additional_context=parsed.get("additional_context"),
        )

    @staticmethod
    def _infer_media_type(url: str) -> str:
        """Infer MIME type from URL suffix. Defaults to image/jpeg."""
        lower = url.lower().split("?")[0]
        if lower.endswith(".png"):
            return "image/png"
        if lower.endswith(".gif"):
            return "image/gif"
        if lower.endswith(".webp"):
            return "image/webp"
        return "image/jpeg"


vision_parser = VisionParser()

# products/edu_video/backend/core/llm.py
"""
LLM factory with Claude (primary) and Grok (fallback) providers.
Includes per-job token usage tracking via Redis.
"""

import json
from typing import Any
from uuid import uuid4

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import LLMResult
from langchain_groq import ChatGroq
from langchain_openai import OpenAIEmbeddings
from redis.asyncio import Redis

from core.config import get_settings

__all__ = [
    "LLMFactory",
    "TokenUsageCallback",
    "llm_factory",
]

logger = structlog.get_logger(__name__)
settings = get_settings()

# Approximate cost per 1K tokens (USD) — update as pricing changes
_COST_PER_1K: dict[str, dict[str, float]] = {
    "claude": {"input": 0.003, "output": 0.015},   # claude-opus-4-5
    "grok":   {"input": 0.0005, "output": 0.0008}, # llama3-70b
}


class TokenUsageCallback(BaseCallbackHandler):
    """
    LangChain callback that records prompt/completion tokens and estimated
    cost to Redis under key cost:{job_id}:llm_usage with TTL=86400s.
    """

    def __init__(self, job_id: str, provider: str, redis_client: Redis) -> None:
        super().__init__()
        self.job_id = job_id
        self.provider = provider
        self.redis = redis_client
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_tokens: int = 0
        self.cost_usd: float = 0.0

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Extract token usage from LLM response and persist to Redis."""
        usage = {}
        if response.llm_output:
            usage = response.llm_output.get("usage", {}) or response.llm_output.get(
                "token_usage", {}
            )

        self.prompt_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0))
        self.completion_tokens = usage.get(
            "output_tokens", usage.get("completion_tokens", 0)
        )
        self.total_tokens = self.prompt_tokens + self.completion_tokens

        rates = _COST_PER_1K.get(self.provider, _COST_PER_1K["claude"])
        self.cost_usd = (self.prompt_tokens / 1000 * rates["input"]) + (
            self.completion_tokens / 1000 * rates["output"]
        )

        import asyncio

        asyncio.create_task(self._persist())

    async def _persist(self) -> None:
        """Write usage record to Redis asynchronously."""
        key = f"cost:{self.job_id}:llm_usage"
        payload = json.dumps(
            {
                "provider": self.provider,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
                "cost_usd": self.cost_usd,
            }
        )
        try:
            await self.redis.set(key, payload, ex=86400)
            logger.info(
                "llm.usage_recorded",
                job_id=self.job_id,
                provider=self.provider,
                total_tokens=self.total_tokens,
                cost_usd=self.cost_usd,
            )
        except Exception as exc:
            logger.error("llm.usage_persist_failed", job_id=self.job_id, error=str(exc))


class LLMFactory:
    """
    Factory for instantiating LLM clients.
    Manages provider selection, fallback chains, and embedding model.
    """

    def get_llm(self, provider: str | None = None) -> BaseChatModel:
        """
        Return a configured LLM for the given provider.
        Falls back to settings.DEFAULT_LLM_PROVIDER if provider is None.
        """
        resolved = provider or settings.DEFAULT_LLM_PROVIDER

        if resolved == "claude":
            return ChatAnthropic(
                model="claude-opus-4-5",
                api_key=settings.ANTHROPIC_API_KEY,
                max_tokens=4096,
                temperature=0.3,
            )
        elif resolved == "grok":
            return ChatGroq(
                model="llama3-70b-8192",
                api_key=settings.GROQ_API_KEY,
                temperature=0.3,
            )
        else:
            raise ValueError(f"Unknown LLM provider: {resolved!r}")

    def get_embedding_model(self) -> OpenAIEmbeddings:
        """
        Return embedding model instance.
        Uses OpenAI text-embedding-3-small (1536-dim).

        ⚠️  COST NOTE: Embeddings are charged per token. Batch your ingestion
        calls and cache embeddings in Qdrant — don't re-embed on every request.
        """
        return OpenAIEmbeddings(model="text-embedding-3-small")

    def with_fallback(
        self,
        primary_provider: str = "claude",
        fallback_provider: str = "grok",
    ) -> BaseChatModel:
        """
        Return primary LLM with automatic fallback to secondary on failure.
        Uses LangChain's native .with_fallbacks() mechanism.
        """
        primary = self.get_llm(primary_provider)
        fallback = self.get_llm(fallback_provider)
        logger.info(
            "llm.fallback_chain_built",
            primary=primary_provider,
            fallback=fallback_provider,
        )
        return primary.with_fallbacks([fallback])

    def get_llm_with_tracking(
        self,
        job_id: str,
        redis_client: Redis,
        provider: str | None = None,
    ) -> tuple[BaseChatModel, TokenUsageCallback]:
        """
        Return an LLM + attached TokenUsageCallback for cost tracking.
        Pass the callback in the LLM invoke call's config dict.
        """
        resolved = provider or settings.DEFAULT_LLM_PROVIDER
        callback = TokenUsageCallback(
            job_id=job_id,
            provider=resolved,
            redis_client=redis_client,
        )
        llm = self.get_llm(resolved)
        return llm, callback


llm_factory = LLMFactory()

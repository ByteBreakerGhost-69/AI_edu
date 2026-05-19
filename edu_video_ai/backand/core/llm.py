"""
backend/core/llm.py

LLMFactory — returns a configured LangChain chat model instance
based on a provider string. Centralises model selection and
API key injection so agents never import provider SDKs directly.

Supported providers:
  - "anthropic"  → ChatAnthropic  (claude-sonnet-4-5 by default)
  - "openai"     → ChatOpenAI     (gpt-4o by default)
  - "grok"       → ChatOpenAI     (OpenAI-compatible endpoint, xAI)

Adding a new provider: subclass BaseChatModel, register in _REGISTRY.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from backend.core.config import settings

logger = logging.getLogger(__name__)


# ── Provider enum ─────────────────────────────────────────────────────────────


class LLMProvider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GROK = "grok"


# ── Model configuration dataclass ─────────────────────────────────────────────


@dataclass
class ModelConfig:
    """
    Immutable specification for a provider + model combination.
    Agents can request a specific config for non-default models.
    """

    provider: LLMProvider
    model_name: str
    temperature: float = 0.3
    max_tokens: int = 4096
    extra_kwargs: dict[str, Any] = field(default_factory=dict)


# ── Pre-defined configs per role ──────────────────────────────────────────────
# These keep agent code declarative — agents reference a config name, not a
# raw model string. Adjust as billing/capability tradeoffs evolve.

CURRICULUM_AGENT_CONFIG = ModelConfig(
    provider=LLMProvider.ANTHROPIC,
    model_name=settings.anthropic_default_model,
    temperature=0.2,
    max_tokens=2048,
)

SCRIPT_AGENT_CONFIG = ModelConfig(
    provider=LLMProvider.ANTHROPIC,
    model_name=settings.anthropic_default_model,
    temperature=0.5,
    max_tokens=8192,
)

FACT_CHECKER_AGENT_CONFIG = ModelConfig(
    provider=LLMProvider.ANTHROPIC,
    model_name=settings.anthropic_default_model,
    temperature=0.0,   # deterministic for verification tasks
    max_tokens=2048,
)

VISUAL_ASSET_AGENT_CONFIG = ModelConfig(
    provider=LLMProvider.OPENAI,
    model_name=settings.openai_default_model if settings.openai_api_key else settings.anthropic_default_model,
    temperature=0.4,
    max_tokens=4096,
)


# ── Factory ───────────────────────────────────────────────────────────────────


class LLMFactory:
    """
    Instantiates and returns LangChain-compatible chat model objects.

    Usage:
        model = LLMFactory.build(LLMProvider.ANTHROPIC)
        model = LLMFactory.from_config(SCRIPT_AGENT_CONFIG)
        model = LLMFactory.build("anthropic", temperature=0.7)
    """

    @staticmethod
    def build(
        provider: LLMProvider | str,
        model_name: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        **extra_kwargs: Any,
    ) -> BaseChatModel:
        """
        Build and return a chat model for the given provider.

        Args:
            provider:    Provider identifier ("anthropic", "openai", "grok").
            model_name:  Override the default model for this provider.
            temperature: Sampling temperature (0.0 = deterministic).
            max_tokens:  Maximum tokens in the completion.
            **extra_kwargs: Passed directly to the underlying LangChain class.

        Returns:
            A configured BaseChatModel instance.

        Raises:
            ValueError: If the provider is unsupported or its API key is missing.
        """
        if isinstance(provider, str):
            try:
                provider = LLMProvider(provider.lower())
            except ValueError:
                supported = [p.value for p in LLMProvider]
                raise ValueError(
                    f"Unsupported LLM provider '{provider}'. "
                    f"Supported: {supported}"
                )

        builder = _BUILDER_MAP.get(provider)
        if builder is None:
            raise ValueError(f"No builder registered for provider '{provider}'.")

        model = builder(
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            **extra_kwargs,
        )
        logger.debug(
            "LLMFactory: built %s (model=%s, temp=%s)",
            provider.value,
            model_name or "<default>",
            temperature,
        )
        return model

    @staticmethod
    def from_config(config: ModelConfig) -> BaseChatModel:
        """
        Build a chat model directly from a ModelConfig dataclass.
        Prefer this in agent code for explicit, reviewable configuration.
        """
        return LLMFactory.build(
            provider=config.provider,
            model_name=config.model_name,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            **config.extra_kwargs,
        )


# ── Provider builder functions ────────────────────────────────────────────────


def _build_anthropic(
    model_name: str | None,
    temperature: float,
    max_tokens: int,
    **kwargs: Any,
) -> ChatAnthropic:
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set.")
    return ChatAnthropic(
        model=model_name or settings.anthropic_default_model,
        api_key=settings.anthropic_api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )


def _build_openai(
    model_name: str | None,
    temperature: float,
    max_tokens: int,
    **kwargs: Any,
) -> ChatOpenAI:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set.")
    return ChatOpenAI(
        model=model_name or settings.openai_default_model,
        api_key=settings.openai_api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )


def _build_grok(
    model_name: str | None,
    temperature: float,
    max_tokens: int,
    **kwargs: Any,
) -> ChatOpenAI:
    """
    Grok uses an OpenAI-compatible API, so we reuse ChatOpenAI
    and point it at xAI's base URL.
    """
    if not settings.grok_api_key:
        raise ValueError("GROK_API_KEY is not set.")
    return ChatOpenAI(
        model=model_name or settings.grok_default_model,
        api_key=settings.grok_api_key,
        base_url=settings.grok_base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )


# ── Internal dispatch map ─────────────────────────────────────────────────────

_BUILDER_MAP: dict[LLMProvider, Any] = {
    LLMProvider.ANTHROPIC: _build_anthropic,
    LLMProvider.OPENAI: _build_openai,
    LLMProvider.GROK: _build_grok,
}


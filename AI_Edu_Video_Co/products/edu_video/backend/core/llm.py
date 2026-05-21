"""
core/llm.py
LLM factory — unified async interface for Claude (Anthropic), OpenAI, and Grok.
Provider selection and credentials are driven by core.config.settings.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any, Union

import anthropic
import openai
import tiktoken
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from core.config import LLMProvider, settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type alias for unified client
# ---------------------------------------------------------------------------

LLMClient = Union[AsyncAnthropic, AsyncOpenAI]

# ---------------------------------------------------------------------------
# Module-level singleton cache
# ---------------------------------------------------------------------------

_llm_client: LLMClient | None = None


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


def get_llm_client() -> LLMClient:
    """
    Return a cached async LLM client for the configured provider.

    Initialises on first call; subsequent calls return the same instance.
    Thread-safe for read (asyncio single-threaded event loop).
    """
    global _llm_client  # noqa: PLW0603

    if _llm_client is not None:
        return _llm_client

    provider = settings.LLM_PROVIDER

    if provider == LLMProvider.CLAUDE:
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured.")
        _llm_client = AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY.get_secret_value(),
        )
        logger.info("LLM client initialised: Anthropic Claude (%s)", settings.ANTHROPIC_DEFAULT_MODEL)

    elif provider in (LLMProvider.OPENAI, LLMProvider.GROK):
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        _llm_client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY.get_secret_value(),
            base_url=settings.OPENAI_BASE_URL or None,  # None = official OpenAI endpoint
        )
        label = "Grok (xAI)" if provider == LLMProvider.GROK else "OpenAI"
        logger.info("LLM client initialised: %s (%s)", label, settings.OPENAI_DEFAULT_MODEL)

    else:
        raise RuntimeError(f"Unsupported LLM_PROVIDER: {provider}")

    return _llm_client


def reset_llm_client() -> None:
    """Reset the singleton (useful in tests or after config changes)."""
    global _llm_client  # noqa: PLW0603
    _llm_client = None
    logger.debug("LLM client singleton reset.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_default_model() -> str:
    """Return the default model name for the active provider."""
    if settings.LLM_PROVIDER == LLMProvider.CLAUDE:
        return settings.ANTHROPIC_DEFAULT_MODEL
    return settings.OPENAI_DEFAULT_MODEL


def get_default_max_tokens() -> int:
    """Return the default max_tokens for the active provider."""
    if settings.LLM_PROVIDER == LLMProvider.CLAUDE:
        return settings.ANTHROPIC_MAX_TOKENS
    return 4096


def _extract_system_and_messages(
    messages: list[dict[str, str]],
) -> tuple[str | None, list[dict[str, str]]]:
    """
    Anthropic requires system messages to be passed separately.
    Extract the first system message (if any) and return the rest.
    """
    system: str | None = None
    chat_messages: list[dict[str, str]] = []

    for msg in messages:
        if msg.get("role") == "system" and system is None:
            system = msg["content"]
        else:
            chat_messages.append(msg)

    return system, chat_messages


def count_tokens(text: str, model: str | None = None) -> int:
    """
    Estimate token count for a string using tiktoken.

    Falls back to cl100k_base encoding when the model is not recognised
    (which also gives a reasonable approximation for Claude).

    Args:
        text:  Input string to tokenise.
        model: Optional model name for encoding selection.

    Returns:
        Integer token count.
    """
    target_model = model or get_default_model()
    try:
        enc = tiktoken.encoding_for_model(target_model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


# ---------------------------------------------------------------------------
# Core completion — non-streaming
# ---------------------------------------------------------------------------


async def get_llm_response(
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    **kwargs: Any,
) -> str:
    """
    Send a chat completion request and return the assistant's reply as a string.

    Args:
        messages:    Conversation history as list of {"role": ..., "content": ...} dicts.
                     Roles: "system", "user", "assistant".
        model:       Model override. Defaults to provider's default model from config.
        temperature: Sampling temperature (0.0–1.0 for deterministic→creative).
        max_tokens:  Token limit for the response. Defaults to provider default.
        **kwargs:    Additional provider-specific parameters forwarded to the API.

    Returns:
        Assistant reply text (stripped).

    Raises:
        RuntimeError: On provider misconfiguration.
        anthropic.APIError / openai.APIError: Propagated after logging.
    """
    resolved_model = model or get_default_model()
    resolved_max_tokens = max_tokens or get_default_max_tokens()
    provider = settings.LLM_PROVIDER
    client = get_llm_client()

    logger.debug(
        "LLM request | provider=%s model=%s temperature=%s max_tokens=%d msgs=%d",
        provider.value,
        resolved_model,
        temperature,
        resolved_max_tokens,
        len(messages),
    )

    try:
        if provider == LLMProvider.CLAUDE:
            assert isinstance(client, AsyncAnthropic)
            system, chat_messages = _extract_system_and_messages(messages)

            create_kwargs: dict[str, Any] = dict(
                model=resolved_model,
                max_tokens=resolved_max_tokens,
                temperature=temperature,
                messages=chat_messages,
                **kwargs,
            )
            if system:
                create_kwargs["system"] = system

            response = await client.messages.create(**create_kwargs)
            content = response.content[0]
            if content.type != "text":
                raise RuntimeError(f"Unexpected Claude response block type: {content.type}")
            return content.text.strip()

        else:  # OPENAI or GROK
            assert isinstance(client, AsyncOpenAI)
            response = await client.chat.completions.create(
                model=resolved_model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=resolved_max_tokens,
                **kwargs,
            )
            text = response.choices[0].message.content or ""
            return text.strip()

    except anthropic.RateLimitError as exc:
        logger.error("Anthropic rate limit exceeded: %s", exc)
        raise
    except anthropic.APIStatusError as exc:
        logger.error("Anthropic API error (status=%s): %s", exc.status_code, exc.message)
        raise
    except anthropic.APIConnectionError as exc:
        logger.error("Anthropic connection error: %s", exc)
        raise
    except openai.RateLimitError as exc:
        logger.error("OpenAI/Grok rate limit exceeded: %s", exc)
        raise
    except openai.APIStatusError as exc:
        logger.error("OpenAI/Grok API error (status=%s): %s", exc.status_code, exc.message)
        raise
    except openai.APIConnectionError as exc:
        logger.error("OpenAI/Grok connection error: %s", exc)
        raise
    except Exception as exc:
        logger.error("Unexpected LLM error [%s]: %s", type(exc).__name__, exc)
        raise


# ---------------------------------------------------------------------------
# Streaming completion
# ---------------------------------------------------------------------------


async def get_llm_response_stream(
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    **kwargs: Any,
) -> AsyncGenerator[str, None]:
    """
    Stream the assistant's reply token-by-token.

    Yields incremental text chunks as they arrive from the provider.

    Args:
        messages:    Same format as get_llm_response.
        model:       Model override.
        temperature: Sampling temperature.
        max_tokens:  Token cap for the response.
        **kwargs:    Additional provider-specific parameters.

    Yields:
        str chunks of the assistant response.

    Raises:
        RuntimeError: On provider misconfiguration or unsupported streaming.
    """
    resolved_model = model or get_default_model()
    resolved_max_tokens = max_tokens or get_default_max_tokens()
    provider = settings.LLM_PROVIDER
    client = get_llm_client()

    logger.debug(
        "LLM stream request | provider=%s model=%s",
        provider.value,
        resolved_model,
    )

    try:
        if provider == LLMProvider.CLAUDE:
            assert isinstance(client, AsyncAnthropic)
            system, chat_messages = _extract_system_and_messages(messages)

            stream_kwargs: dict[str, Any] = dict(
                model=resolved_model,
                max_tokens=resolved_max_tokens,
                temperature=temperature,
                messages=chat_messages,
                **kwargs,
            )
            if system:
                stream_kwargs["system"] = system

            async with client.messages.stream(**stream_kwargs) as stream:
                async for text_chunk in stream.text_stream:
                    yield text_chunk

        else:  # OPENAI or GROK
            assert isinstance(client, AsyncOpenAI)
            stream = await client.chat.completions.create(
                model=resolved_model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=resolved_max_tokens,
                stream=True,
                **kwargs,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta

    except anthropic.RateLimitError as exc:
        logger.error("Anthropic rate limit (stream): %s", exc)
        raise
    except anthropic.APIStatusError as exc:
        logger.error("Anthropic API error (stream, status=%s): %s", exc.status_code, exc.message)
        raise
    except openai.RateLimitError as exc:
        logger.error("OpenAI/Grok rate limit (stream): %s", exc)
        raise
    except openai.APIStatusError as exc:
        logger.error("OpenAI/Grok API error (stream, status=%s): %s", exc.status_code, exc.message)
        raise
    except Exception as exc:
        logger.error("Unexpected LLM stream error [%s]: %s", type(exc).__name__, exc)
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: list[str] = [
    "get_llm_client",
    "reset_llm_client",
    "get_default_model",
    "get_default_max_tokens",
    "count_tokens",
    "get_llm_response",
    "get_llm_response_stream",
      ]
      

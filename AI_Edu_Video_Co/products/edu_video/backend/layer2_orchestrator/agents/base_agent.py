# products/edu_video/backend/layer2_orchestrator/agents/base_agent.py
"""
Abstract base class for all LangGraph pipeline agents.

Design decisions:
- Agents NEVER write to Redis directly. Cost is accumulated in GraphState
  via _record_cost() and flushed to Redis by the orchestrator after the graph completes.
- Agents NEVER raise. All exceptions are caught, logged, and returned as
  safe defaults via _safe_return().
- LLM calls go through _call_llm_json() which handles JSON parsing,
  retry with error feedback, and fallback to Grok.
- _timer() is a context manager that captures elapsed ms for structured logging.
"""

import json
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Generator

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from core.config import get_settings
from core.llm import llm_factory
from core.utils import safe_json_loads, utcnow
from layer2_orchestrator.graph import GraphState

__all__ = ["BaseAgent"]

# Claude claude-sonnet-4-5 pricing (USD per token)
# Update these if Anthropic changes pricing
_INPUT_COST_PER_TOKEN: float = 0.000003   # $3 per 1M input tokens
_OUTPUT_COST_PER_TOKEN: float = 0.000015  # $15 per 1M output tokens

# Hard cap on prompt size sent to LLM to avoid runaway costs
_MAX_PROMPT_CHARS: int = 12_000

# Retry error feedback is truncated to keep prompts manageable
_MAX_ERROR_FEEDBACK_CHARS: int = 200


class BaseAgent(ABC):
    """
    Abstract base for all pipeline agents.

    Each subclass must implement:
        - agent_name (property): unique string identifier
        - run(state): async method returning partial GraphState dict

    Provided concrete helpers:
        - _call_llm_json(): LLM call with JSON parsing + retry
        - _record_cost(): returns cost accumulation dict for state merge
        - _safe_return(): safe default dict for except blocks
        - _timer(): context manager for elapsed ms measurement
        - _estimate_cost(): USD cost from token counts
    """

    def __init__(self) -> None:
        self.llm = llm_factory.get_llm()
        self.llm_with_fallback = self.llm.with_fallbacks(
            [llm_factory.get_llm("grok")]
        )
        self.settings = get_settings()
        self.log = structlog.get_logger(self.__class__.__name__)

    # ------------------------------------------------------------------ #
    # Abstract interface                                                   #
    # ------------------------------------------------------------------ #

    @property
    @abstractmethod
    def agent_name(self) -> str:
        """Unique agent identifier used in logs and cost_breakdown entries."""
        ...

    @abstractmethod
    async def run(self, state: GraphState) -> dict:
        """
        Execute agent logic. Returns a partial GraphState update dict.

        Contract:
        - Must NEVER raise. Catch all exceptions and call _safe_return().
        - Must return ONLY the keys this agent modifies.
        - Must always include "current_node" in returned dict.
        - Must merge _record_cost() result into returned dict if LLM was called.
        """
        ...

    # ------------------------------------------------------------------ #
    # LLM call helper                                                     #
    # ------------------------------------------------------------------ #

    async def _call_llm_json(
        self,
        system_prompt: str,
        user_prompt: str,
        job_id: str,
        expected_keys: list[str],
        max_retries: int = 2,
    ) -> dict[str, Any]:
        """
        Call the LLM (Claude with Grok fallback), parse the response as JSON.
        Retries once with error feedback injected into user_prompt on parse failure.

        Args:
            system_prompt: Injected as SystemMessage. JSON instruction is auto-appended.
            user_prompt: Injected as HumanMessage.
            job_id: Used only for structured logging — not sent to LLM.
            expected_keys: If all retries fail, returns {k: None for k in expected_keys}.
            max_retries: Total attempts before giving up (default 2).

        Returns:
            Parsed dict on success.
            {key: None for key in expected_keys} on total failure.

        Never raises.
        """
        log = self.log.bind(job_id=job_id, agent=self.agent_name)

        # Enforce prompt size cap to avoid runaway token spend
        if len(user_prompt) > _MAX_PROMPT_CHARS:
            log.warning(
                "llm_json.prompt_truncated",
                original_chars=len(user_prompt),
                cap=_MAX_PROMPT_CHARS,
            )
            user_prompt = user_prompt[:_MAX_PROMPT_CHARS]

        full_system = (
            system_prompt.rstrip()
            + "\n\nCRITICAL: Respond ONLY with a valid JSON object. "
            "No markdown code fences. No prose before or after. "
            "No trailing commas. The first character of your response must be '{'."
        )

        current_user_prompt = user_prompt
        last_raw: str = ""
        last_error: str = ""

        for attempt in range(1, max_retries + 1):
            log.info("llm_json.attempt", attempt=attempt, max_retries=max_retries)
            try:
                messages = [
                    SystemMessage(content=full_system),
                    HumanMessage(content=current_user_prompt),
                ]
                response = await self.llm_with_fallback.ainvoke(messages)
                last_raw = str(response.content).strip()

                # Strip accidental markdown fences — LLMs sometimes add them
                # despite instructions
                cleaned = last_raw
                if cleaned.startswith("```"):
                    # Handle ```json\n{...}\n``` and ```\n{...}\n```
                    lines = cleaned.split("\n")
                    # Drop first line (the fence opener) and last non-empty line
                    inner_lines = lines[1:]
                    if inner_lines and inner_lines[-1].strip() == "```":
                        inner_lines = inner_lines[:-1]
                    cleaned = "\n".join(inner_lines).strip()

                parsed = safe_json_loads(cleaned)
                if parsed is not None:
                    log.info(
                        "llm_json.success",
                        attempt=attempt,
                        keys=list(parsed.keys()),
                    )
                    return parsed

                # JSON parse failed — prepare retry with feedback
                last_error = (
                    f"Response was not valid JSON. "
                    f"First 150 chars received: {cleaned[:150]!r}"
                )
                log.warning("llm_json.parse_failed", attempt=attempt, error=last_error)

            except Exception as exc:
                last_error = str(exc)
                log.error("llm_json.call_failed", attempt=attempt, error=last_error)

            # Inject error feedback for next attempt (only if retries remain)
            if attempt < max_retries:
                feedback = last_error[:_MAX_ERROR_FEEDBACK_CHARS]
                current_user_prompt = (
                    user_prompt
                    + f"\n\n[PREVIOUS ATTEMPT FAILED: {feedback}]\n"
                    "Return ONLY a valid JSON object. "
                    "Start your response with '{' immediately."
                )

        log.error(
            "llm_json.all_retries_failed",
            max_retries=max_retries,
            last_error=last_error,
            last_raw_preview=last_raw[:200],
        )
        return {k: None for k in expected_keys}

    # ------------------------------------------------------------------ #
    # Cost helpers                                                         #
    # ------------------------------------------------------------------ #

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """
        Estimate USD cost for a single LLM call based on Claude claude-sonnet-4-5 pricing.
        Use this when actual token counts are not available from the response object.
        """
        return round(
            prompt_tokens * _INPUT_COST_PER_TOKEN
            + completion_tokens * _OUTPUT_COST_PER_TOKEN,
            8,
        )

    def _record_cost(
        self,
        job_id: str,
        tokens_used: int,
        cost_usd: float,
        state: GraphState,
    ) -> dict:
        """
        Return a partial state dict that ACCUMULATES cost without overwriting.

        Always spread-merge this into the node's return dict:
            return {
                "scenes": scenes,
                **self._record_cost(job_id, 2000, 0.021, state),
            }

        Never call this twice in the same return — the second call would
        read stale state["total_cost_usd"] and double-count the first addition.
        Accumulate all costs for a node first, then call once.
        """
        log = self.log.bind(job_id=job_id, agent=self.agent_name)
        log.info(
            "cost.recorded",
            tokens=tokens_used,
            cost_usd=cost_usd,
            running_total=round(state["total_cost_usd"] + cost_usd, 8),
        )
        return {
            "total_cost_usd": state["total_cost_usd"] + cost_usd,
            "cost_breakdown": state["cost_breakdown"] + [
                {
                    "agent": self.agent_name,
                    "cost_usd": cost_usd,
                    "tokens": tokens_used,
                    "job_id": job_id,
                    "timestamp": utcnow().isoformat(),
                }
            ],
        }

    # ------------------------------------------------------------------ #
    # Error handling helper                                                #
    # ------------------------------------------------------------------ #

    def _safe_return(
        self,
        state: GraphState,
        error: str,
        defaults: dict,
    ) -> dict:
        """
        Return a safe default dict with the error appended to state["errors"].
        Call this in every except block — never re-raise from an agent.

        Args:
            state: Current GraphState (used only to read existing errors list).
            error: Human-readable error description. Prefixed with agent_name.
            defaults: The safe default values to return for all modified keys.
                      Must include "current_node".

        Example:
            except Exception as exc:
                return self._safe_return(
                    state,
                    error=str(exc),
                    defaults={
                        "scenes": [],
                        "current_node": "node_generate_scenes",
                    },
                )
        """
        tagged_error = f"{self.agent_name}: {error}"
        self.log.error(
            "agent.safe_return",
            agent=self.agent_name,
            error=tagged_error,
            existing_error_count=len(state["errors"]),
        )
        return {
            **defaults,
            "errors": state["errors"] + [tagged_error],
        }

    # ------------------------------------------------------------------ #
    # Timing helper                                                        #
    # ------------------------------------------------------------------ #

    @contextmanager
    def _timer(self) -> Generator[dict, None, None]:
        """
        Context manager that measures elapsed wall-clock time in milliseconds.
        Yields a mutable dict with key "elapsed_ms" — populated on exit.

        Usage:
            with self._timer() as t:
                result = await some_operation()
            self.log.info("done", duration_ms=t["elapsed_ms"])

        The dict is populated even if the body raises, so it's safe to read
        elapsed_ms in a finally block.
        """
        result: dict = {"elapsed_ms": 0.0}
        start = time.perf_counter()
        try:
            yield result
        finally:
            result["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 1)

    # ------------------------------------------------------------------ #
    # Repr                                                                 #
    # ------------------------------------------------------------------ #

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} agent_name={self.agent_name!r}>"

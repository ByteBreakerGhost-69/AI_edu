# products/edu_video/backend/utils/logging.py
"""
Centralised logging configuration and helpers.
Builds on structlog. Adds context managers, decorators,
request context binding, and log sampling for high-volume operations.
"""

import asyncio
import functools
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Callable, TypeVar

import structlog

from core.config import get_settings

__all__ = [
    "configure_logging",
    "get_logger",
    "bind_request_context",
    "clear_request_context",
    "log_execution_time",
    "log_pipeline_stage",
    "SampledLogger",
    "mask_sensitive_data",
]

F = TypeVar("F", bound=Callable[..., Any])

_DEFAULT_FULL_MASK: frozenset[str] = frozenset({
    "password", "token", "api_key", "secret", "webhook_secret",
    "stripe_secret_key", "authorization", "x-api-key",
    "access_token", "refresh_token", "hashed_password",
    "qdrant_api_key", "anthropic_api_key", "openai_api_key",
    "groq_api_key", "flux_api_key", "kling_api_key",
    "elevenlabs_api_key", "google_api_key",
})
_DEFAULT_PARTIAL_MASK: frozenset[str] = frozenset({
    "stripe_customer_id", "stripe_subscription_id",
})

# --------------------------------------------------------------------------- #
# Configuration                                                                #
# --------------------------------------------------------------------------- #

def configure_logging() -> None:
    """
    Configure structlog for the entire application.
    Call ONCE at startup in main.py lifespan — not on every import.

    Dev mode: ConsoleRenderer with colours + DEBUG level + caller info.
    Prod mode: JSONRenderer for Cloud Logging + INFO level, noisy libs silenced.
    """
    settings = get_settings()

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.APP_ENV == "prod":
        processors = shared_processors + [structlog.processors.JSONRenderer()]
        log_level = logging.INFO
    else:
        processors = shared_processors + [structlog.dev.ConsoleRenderer(colors=True)]
        log_level = logging.DEBUG

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(format="%(message)s", level=log_level)

    if settings.APP_ENV == "prod":
        _noisy = [
            "uvicorn.access",
            "sqlalchemy.engine",
            "httpx",
            "httpcore",
            "google.auth",
            "google.cloud",
            "manim",
            "PIL",
            "matplotlib",
            "pyppeteer",
        ]
        for lib in _noisy:
            logging.getLogger(lib).setLevel(logging.WARNING)


# --------------------------------------------------------------------------- #
# Logger factory                                                               #
# --------------------------------------------------------------------------- #

def get_logger(name: str, **initial_context: Any) -> structlog.stdlib.BoundLogger:
    """
    Return a structlog logger bound with optional initial context.

    Usage:
        log = get_logger(__name__, service="layer2_orchestrator")
        log = get_logger(__name__, worker_id="abc123", job_id="xyz")
    """
    logger = structlog.get_logger(name)
    if initial_context:
        logger = logger.bind(**initial_context)
    return logger


# --------------------------------------------------------------------------- #
# Request context                                                              #
# --------------------------------------------------------------------------- #

def bind_request_context(
    request_id: str,
    user_id: str | None = None,
    path: str | None = None,
    **extra: Any,
) -> None:
    """
    Bind context variables for the current async task via structlog.contextvars.
    All subsequent log calls within this async context will include these fields.

    Call at the start of every request:
        bind_request_context(request_id=req_id, user_id=str(user.id), path=request.url.path)
    """
    ctx: dict[str, Any] = {"request_id": request_id}
    if user_id is not None:
        ctx["user_id"] = user_id
    if path is not None:
        ctx["path"] = path
    ctx.update(extra)
    structlog.contextvars.bind_contextvars(**ctx)


def clear_request_context() -> None:
    """Clear contextvars at end of request or task."""
    structlog.contextvars.clear_contextvars()


# --------------------------------------------------------------------------- #
# Decorator: log_execution_time                                                #
# --------------------------------------------------------------------------- #

def log_execution_time(
    logger_name: str | None = None,
    level: str = "info",
    include_args: bool = False,
    slow_threshold_ms: float | None = None,
) -> Callable[[F], F]:
    """
    Decorator that logs function entry, exit, and execution time.
    Works for both sync and async functions.

    Args:
        logger_name:      Logger name. Defaults to function's module.
        level:            Log level for normal execution: "debug"|"info"|"warning".
        include_args:     Log function kwargs (sensitive values are masked).
        slow_threshold_ms: Emit WARNING when execution exceeds this threshold.

    Usage:
        @log_execution_time(slow_threshold_ms=1000)
        async def synthesize_audio(self, script: str) -> TTSResult: ...

        @log_execution_time(level="debug")
        def get_tier_features(tier: str) -> TierFeatures: ...
    """
    def decorator(func: F) -> F:
        name = logger_name or func.__module__
        log = get_logger(name)
        func_name = f"{func.__module__}.{func.__qualname__}"

        def _entry_log(**kw: Any) -> None:
            entry: dict[str, Any] = {"function": func_name}
            if include_args and kw:
                entry["kwargs"] = mask_sensitive_data(kw)
            getattr(log, level)("function_started", **entry)

        def _exit_log(elapsed_ms: int) -> None:
            if slow_threshold_ms and elapsed_ms > slow_threshold_ms:
                log.warning(
                    "slow_function_detected",
                    function=func_name,
                    duration_ms=elapsed_ms,
                    threshold_ms=slow_threshold_ms,
                )
            else:
                getattr(log, level)(
                    "function_completed",
                    function=func_name,
                    duration_ms=elapsed_ms,
                )

        def _error_log(elapsed_ms: int, exc: Exception) -> None:
            log.error(
                "function_failed",
                function=func_name,
                duration_ms=elapsed_ms,
                error=str(exc),
                error_type=type(exc).__name__,
            )

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                _entry_log(**kwargs)
                start = time.perf_counter()
                try:
                    result = await func(*args, **kwargs)
                    _exit_log(int((time.perf_counter() - start) * 1000))
                    return result
                except Exception as exc:
                    _error_log(int((time.perf_counter() - start) * 1000), exc)
                    raise

            return async_wrapper  # type: ignore[return-value]

        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                _entry_log(**kwargs)
                start = time.perf_counter()
                try:
                    result = func(*args, **kwargs)
                    _exit_log(int((time.perf_counter() - start) * 1000))
                    return result
                except Exception as exc:
                    _error_log(int((time.perf_counter() - start) * 1000), exc)
                    raise

            return sync_wrapper  # type: ignore[return-value]

    return decorator


# --------------------------------------------------------------------------- #
# Context manager: log_pipeline_stage                                          #
# --------------------------------------------------------------------------- #

@asynccontextmanager
async def log_pipeline_stage(
    stage_name: str,
    job_id: str,
    logger: structlog.stdlib.BoundLogger | None = None,
    **extra_context: Any,
):
    """
    Async context manager for logging named pipeline stages.

    Usage:
        async with log_pipeline_stage("layer2_orchestration", job_id=job_id):
            result = await orchestrator.run(job_payload)

    Emits:
        pipeline_stage_started   → on entry
        pipeline_stage_completed → on clean exit (includes duration_ms)
        pipeline_stage_failed    → on exception (includes error + duration_ms, re-raises)
    """
    log = logger or get_logger("pipeline")
    start = time.perf_counter()

    log.info(
        "pipeline_stage_started",
        stage=stage_name,
        job_id=job_id,
        **extra_context,
    )

    try:
        yield
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        log.info(
            "pipeline_stage_completed",
            stage=stage_name,
            job_id=job_id,
            duration_ms=elapsed_ms,
            **extra_context,
        )
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        log.error(
            "pipeline_stage_failed",
            stage=stage_name,
            job_id=job_id,
            duration_ms=elapsed_ms,
            error=str(exc),
            error_type=type(exc).__name__,
            **extra_context,
        )
        raise


# --------------------------------------------------------------------------- #
# SampledLogger                                                                #
# --------------------------------------------------------------------------- #

class SampledLogger:
    """
    Logger that samples a fraction of calls to prevent log flooding.
    Use for high-frequency events such as per-frame rendering logs.

    WARNING-level and ERROR-level calls are never sampled — always emitted.

    Usage:
        frame_log = SampledLogger(get_logger(__name__), sample_rate=0.01)
        for frame in frames:
            frame_log.debug("frame_rendered", frame_number=frame.index)
    """

    def __init__(
        self,
        logger: structlog.stdlib.BoundLogger,
        sample_rate: float = 0.1,
    ) -> None:
        """
        Args:
            logger:      Underlying structlog logger.
            sample_rate: Fraction of calls to emit (0.0–1.0).
                         0.1 = approximately 10% of calls logged.
        """
        if not 0.0 < sample_rate <= 1.0:
            raise ValueError(f"sample_rate must be in (0, 1], got {sample_rate}")
        self._logger = logger
        self._sample_rate = sample_rate
        self._call_count = 0
        self._logged_count = 0

    def _should_log(self) -> bool:
        import random  # noqa: PLC0415 — lazy import for performance
        self._call_count += 1
        if random.random() < self._sample_rate:
            self._logged_count += 1
            return True
        return False

    def debug(self, event: str, **kwargs: Any) -> None:
        if self._should_log():
            self._logger.debug(
                event, _sampled=True, _sample_rate=self._sample_rate, **kwargs
            )

    def info(self, event: str, **kwargs: Any) -> None:
        if self._should_log():
            self._logger.info(
                event, _sampled=True, _sample_rate=self._sample_rate, **kwargs
            )

    def warning(self, event: str, **kwargs: Any) -> None:
        """Warnings are never sampled."""
        self._logger.warning(event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        """Errors are never sampled."""
        self._logger.error(event, **kwargs)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "total_calls": self._call_count,
            "logged_calls": self._logged_count,
            "suppressed_calls": self._call_count - self._logged_count,
            "effective_rate": (
                self._logged_count / self._call_count
                if self._call_count > 0
                else 0.0
            ),
        }


# --------------------------------------------------------------------------- #
# Sensitive data masking                                                       #
# --------------------------------------------------------------------------- #

def mask_sensitive_data(
    data: dict[str, Any],
    sensitive_keys: list[str] | None = None,
) -> dict[str, Any]:
    """
    Recursively mask sensitive values in a dict before logging.

    Masking strategy:
        Full mask  → replace with "***"
        Partial    → replace with "***...{last4}"  (e.g. Stripe IDs)
        Long text  → replace with "***[N chars]"   (>500 chars)

    Usage:
        safe_payload = mask_sensitive_data(job_payload)
        log.info("job_received", payload=safe_payload)
    """
    all_sensitive = _DEFAULT_FULL_MASK | frozenset(
        k.lower() for k in (sensitive_keys or [])
    )

    def _mask(key: str, value: Any) -> Any:
        key_lower = key.lower()

        if key_lower in all_sensitive:
            return "***"

        if key_lower in _DEFAULT_PARTIAL_MASK and isinstance(value, str):
            return f"***...{value[-4:]}" if len(value) > 4 else "***"

        if isinstance(value, str) and len(value) > 500:
            return f"***[{len(value)} chars]"

        if isinstance(value, dict):
            return mask_sensitive_data(value, sensitive_keys)

        if isinstance(value, list):
            return [_mask(f"{key}[item]", item) for item in value]

        return value

    return {k: _mask(k, v) for k, v in data.items()}

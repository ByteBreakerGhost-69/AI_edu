# products/edu_video/backend/utils/monitoring.py
"""
Performance metrics tracking, alerting, and health indicators.
Redis-backed — no external monitoring service dependency.
Metrics stored as Redis sorted sets (time-series) and counters.
"""

import asyncio
import functools
import json
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, TypeVar

from core.config import get_settings
from core.database import _redis_client, _create_redis_client
from utils.logging import get_logger

__all__ = [
    "MetricType",
    "AlertLevel",
    "MetricPoint",
    "AlertRule",
    "MetricsCollector",
    "metrics",
    "track_metric",
    "alert_if",
]

F = TypeVar("F", bound=Callable[..., Any])
_log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Enums + data classes                                                         #
# --------------------------------------------------------------------------- #

class MetricType(StrEnum):
    COUNTER   = "counter"    # cumulative count
    GAUGE     = "gauge"      # current value
    HISTOGRAM = "histogram"  # value distribution
    TIMER     = "timer"      # duration measurement


class AlertLevel(StrEnum):
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"


@dataclass
class MetricPoint:
    name: str
    value: float
    metric_type: MetricType
    tags: dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class AlertRule:
    metric_name: str
    threshold: float
    level: AlertLevel
    condition: str              # "gt"|"lt"|"gte"|"lte"|"eq"
    message_template: str
    cooldown_seconds: int = 300


# --------------------------------------------------------------------------- #
# Default alert rules                                                           #
# --------------------------------------------------------------------------- #

DEFAULT_ALERT_RULES: list[AlertRule] = [
    AlertRule(
        metric_name="job_queue_depth",
        threshold=50.0,
        level=AlertLevel.WARNING,
        condition="gt",
        message_template="Job queue depth {value:.0f} exceeds warning threshold {threshold:.0f}",
        cooldown_seconds=300,
    ),
    AlertRule(
        metric_name="job_queue_depth",
        threshold=100.0,
        level=AlertLevel.CRITICAL,
        condition="gt",
        message_template="Job queue depth {value:.0f} is critically high (threshold {threshold:.0f})",
        cooldown_seconds=60,
    ),
    AlertRule(
        metric_name="job_failure_rate",
        threshold=0.1,
        level=AlertLevel.WARNING,
        condition="gt",
        message_template="Job failure rate {value:.1%} exceeds 10% threshold",
        cooldown_seconds=600,
    ),
    AlertRule(
        metric_name="job_processing_time_seconds",
        threshold=480.0,
        level=AlertLevel.WARNING,
        condition="gt",
        message_template="Job processing time {value:.0f}s approaching 600s timeout",
        cooldown_seconds=120,
    ),
    AlertRule(
        metric_name="tts_cost_per_job_usd",
        threshold=0.50,
        level=AlertLevel.WARNING,
        condition="gt",
        message_template="TTS cost per job ${value:.2f} unusually high (threshold ${threshold:.2f})",
        cooldown_seconds=300,
    ),
    AlertRule(
        metric_name="llm_cost_per_job_usd",
        threshold=0.30,
        level=AlertLevel.WARNING,
        condition="gt",
        message_template="LLM cost per job ${value:.2f} unusually high (threshold ${threshold:.2f})",
        cooldown_seconds=300,
    ),
    AlertRule(
        metric_name="render_failure_count",
        threshold=5.0,
        level=AlertLevel.CRITICAL,
        condition="gte",
        message_template="Renderer failures {value:.0f} in window — check renderer health",
        cooldown_seconds=120,
    ),
    AlertRule(
        metric_name="redis_connection_errors",
        threshold=3.0,
        level=AlertLevel.CRITICAL,
        condition="gte",
        message_template="Redis connection errors {value:.0f} — check Redis health",
        cooldown_seconds=60,
    ),
    AlertRule(
        metric_name="review_queue_depth",
        threshold=20.0,
        level=AlertLevel.WARNING,
        condition="gt",
        message_template="Review queue depth {value:.0f} — human reviewers may be overloaded",
        cooldown_seconds=600,
    ),
]


# --------------------------------------------------------------------------- #
# MetricsCollector                                                             #
# --------------------------------------------------------------------------- #

class MetricsCollector:
    """
    Redis-backed metrics collection for the EduVideo platform.

    Storage schema:
        Counter:   metrics:counter:{name}:{tag_hash}   → INCR + TTL
        Gauge:     metrics:gauge:{name}:{tag_hash}     → SET + TTL
        Histogram: metrics:hist:{name}:{tag_hash}      → ZADD (score=value, member=timestamp:value)
        Timer:     metrics:timer:{name}:{tag_hash}     → ZADD (score=duration_ms, member=timestamp)
        Timeseries: metrics:ts:{name}                  → ZADD (score=timestamp, member=JSON)

    Alert cooldowns: metrics:alert_cooldown:{name}:{level} → SET + TTL
    """

    METRICS_PREFIX    = "metrics"
    DEFAULT_TTL       = 86_400      # 24h for counters and gauges
    HISTOGRAM_TTL     = 604_800     # 7d for distributions
    MAX_HIST_POINTS   = 1_000
    TS_RETENTION_SECS = 86_400      # 24h for time-series window

    def __init__(self) -> None:
        self.settings = get_settings()
        self.log = get_logger(__name__)
        self._alert_rules = DEFAULT_ALERT_RULES.copy()

    # ------------------------------------------------------------------ #
    # Redis helper                                                          #
    # ------------------------------------------------------------------ #

    async def _redis(self):
        """Return shared Redis client, initialising if necessary."""
        from core.database import _redis_client  # noqa: PLC0415
        if _redis_client is None:
            return await _create_redis_client()
        return _redis_client

    # ------------------------------------------------------------------ #
    # Key builders                                                          #
    # ------------------------------------------------------------------ #

    def _tag_hash(self, tags: dict[str, str]) -> str:
        if not tags:
            return "notag"
        return ":".join(f"{k}={v}" for k, v in sorted(tags.items()))

    def _key(self, kind: str, name: str, tags: dict[str, str]) -> str:
        return f"{self.METRICS_PREFIX}:{kind}:{name}:{self._tag_hash(tags)}"

    # ------------------------------------------------------------------ #
    # Core recording methods                                               #
    # ------------------------------------------------------------------ #

    async def increment(
        self,
        name: str,
        value: float = 1.0,
        tags: dict[str, str] | None = None,
    ) -> None:
        """Increment a counter metric."""
        tags = tags or {}
        key = self._key("counter", name, tags)
        try:
            redis = await self._redis()
            await redis.incrbyfloat(key, value)
            await redis.expire(key, self.DEFAULT_TTL)
            await self._append_timeseries(name, value, tags)
            await self._check_alerts(name, value)
        except Exception as exc:
            self.log.warning("metrics.increment_failed", metric=name, error=str(exc))

    async def gauge(
        self,
        name: str,
        value: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        """Set a gauge to the current value."""
        tags = tags or {}
        key = self._key("gauge", name, tags)
        try:
            redis = await self._redis()
            await redis.set(key, value, ex=self.DEFAULT_TTL)
            await self._append_timeseries(name, value, tags)
            await self._check_alerts(name, value)
        except Exception as exc:
            self.log.warning("metrics.gauge_failed", metric=name, error=str(exc))

    async def histogram(
        self,
        name: str,
        value: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        """
        Record a value into a histogram (sorted set).
        Trims to MAX_HIST_POINTS to prevent unbounded growth.
        """
        tags = tags or {}
        key = self._key("hist", name, tags)
        member = f"{time.time()}:{value}"
        try:
            redis = await self._redis()
            await redis.zadd(key, {member: value})
            await redis.zremrangebyrank(key, 0, -(self.MAX_HIST_POINTS + 1))
            await redis.expire(key, self.HISTOGRAM_TTL)
            await self._append_timeseries(name, value, tags)
        except Exception as exc:
            self.log.warning("metrics.histogram_failed", metric=name, error=str(exc))

    async def timer(
        self,
        name: str,
        duration_ms: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        """Record a duration (milliseconds) as a timer metric."""
        tags = tags or {}
        key = self._key("timer", name, tags)
        member = f"{time.time()}:{duration_ms}"
        try:
            redis = await self._redis()
            await redis.zadd(key, {member: duration_ms})
            await redis.zremrangebyrank(key, 0, -(self.MAX_HIST_POINTS + 1))
            await redis.expire(key, self.HISTOGRAM_TTL)
            await self._append_timeseries(name, duration_ms, tags)
            await self._check_alerts(name, duration_ms / 1000)  # convert to seconds for rules
        except Exception as exc:
            self.log.warning("metrics.timer_failed", metric=name, error=str(exc))

    # ------------------------------------------------------------------ #
    # Aggregations                                                          #
    # ------------------------------------------------------------------ #

    async def get_counter(
        self, name: str, tags: dict[str, str] | None = None
    ) -> float:
        """Return current counter value."""
        key = self._key("counter", name, tags or {})
        try:
            redis = await self._redis()
            raw = await redis.get(key)
            return float(raw) if raw else 0.0
        except Exception:
            return 0.0

    async def get_gauge(
        self, name: str, tags: dict[str, str] | None = None
    ) -> float | None:
        """Return current gauge value or None if not set."""
        key = self._key("gauge", name, tags or {})
        try:
            redis = await self._redis()
            raw = await redis.get(key)
            return float(raw) if raw else None
        except Exception:
            return None

    async def get_histogram_percentiles(
        self,
        name: str,
        percentiles: list[float] | None = None,
        tags: dict[str, str] | None = None,
    ) -> dict[str, float]:
        """
        Compute percentiles from histogram data.
        percentiles: list of values 0.0–1.0, e.g. [0.5, 0.95, 0.99]
        Returns: {"p50": val, "p95": val, "p99": val, "min": val, "max": val, "count": N}
        """
        percentiles = percentiles or [0.5, 0.95, 0.99]
        key = self._key("hist", name, tags or {})
        result: dict[str, float] = {}
        try:
            redis = await self._redis()
            members = await redis.zrange(key, 0, -1, withscores=True)
            if not members:
                return {}
            values = sorted(float(score) for _, score in members)
            n = len(values)
            result["count"] = float(n)
            result["min"] = values[0]
            result["max"] = values[-1]
            result["mean"] = sum(values) / n
            for p in percentiles:
                idx = max(0, int(p * n) - 1)
                label = f"p{int(p * 100)}"
                result[label] = values[idx]
        except Exception as exc:
            self.log.warning("metrics.percentile_failed", metric=name, error=str(exc))
        return result

    async def get_timeseries(
        self,
        name: str,
        window_seconds: int = 3600,
    ) -> list[dict[str, Any]]:
        """
        Return time-series data points for the last window_seconds.
        Returns list of {timestamp, value, tags} dicts.
        """
        key = f"{self.METRICS_PREFIX}:ts:{name}"
        min_score = time.time() - window_seconds
        try:
            redis = await self._redis()
            members = await redis.zrangebyscore(
                key, min_score, "+inf", withscores=True
            )
            points = []
            for raw, score in members:
                try:
                    point = json.loads(raw)
                    point["timestamp"] = score
                    points.append(point)
                except json.JSONDecodeError:
                    continue
            return points
        except Exception as exc:
            self.log.warning("metrics.timeseries_read_failed", metric=name, error=str(exc))
            return []

    # ------------------------------------------------------------------ #
    # Health summary                                                        #
    # ------------------------------------------------------------------ #

    async def get_health_summary(self) -> dict[str, Any]:
        """
        Return a structured health summary for the /ready endpoint and admin dashboard.
        Includes key counters, recent failure rates, and queue depths.
        """
        try:
            redis = await self._redis()
            jobs_processed = await self.get_counter("jobs_processed")
            jobs_failed = await self.get_counter("jobs_failed")
            failure_rate = (
                jobs_failed / jobs_processed if jobs_processed > 0 else 0.0
            )
            queue_depth = await self.get_gauge("job_queue_depth") or 0.0
            review_depth = await self.get_gauge("review_queue_depth") or 0.0
            processing_times = await self.get_histogram_percentiles(
                "job_processing_time_seconds",
                percentiles=[0.5, 0.95],
            )
            llm_cost = await self.get_histogram_percentiles(
                "llm_cost_per_job_usd",
                percentiles=[0.5, 0.95],
            )
            return {
                "jobs_processed_24h": jobs_processed,
                "jobs_failed_24h": jobs_failed,
                "failure_rate": round(failure_rate, 4),
                "job_queue_depth": queue_depth,
                "review_queue_depth": review_depth,
                "processing_time_p50_seconds": processing_times.get("p50"),
                "processing_time_p95_seconds": processing_times.get("p95"),
                "llm_cost_p50_usd": llm_cost.get("p50"),
                "llm_cost_p95_usd": llm_cost.get("p95"),
                "sampled_at": time.time(),
            }
        except Exception as exc:
            self.log.error("metrics.health_summary_failed", error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------ #
    # Alert engine                                                          #
    # ------------------------------------------------------------------ #

    async def _check_alerts(self, metric_name: str, value: float) -> None:
        """Evaluate alert rules for a metric value and emit logs if triggered."""
        for rule in self._alert_rules:
            if rule.metric_name != metric_name:
                continue
            if not self._condition_met(value, rule.condition, rule.threshold):
                continue
            await self._fire_alert(rule, value)

    def _condition_met(
        self, value: float, condition: str, threshold: float
    ) -> bool:
        match condition:
            case "gt":  return value > threshold
            case "lt":  return value < threshold
            case "gte": return value >= threshold
            case "lte": return value <= threshold
            case "eq":  return value == threshold
            case _:     return False

    async def _fire_alert(self, rule: AlertRule, value: float) -> None:
        """
        Emit an alert log if cooldown has expired.
        Cooldown key: metrics:alert_cooldown:{name}:{level}
        """
        cooldown_key = (
            f"{self.METRICS_PREFIX}:alert_cooldown"
            f":{rule.metric_name}:{rule.level}"
        )
        try:
            redis = await self._redis()
            already_fired = await redis.get(cooldown_key)
            if already_fired:
                return

            message = rule.message_template.format(
                value=value, threshold=rule.threshold
            )
            log_fn = {
                AlertLevel.INFO:     self.log.info,
                AlertLevel.WARNING:  self.log.warning,
                AlertLevel.CRITICAL: self.log.error,
            }.get(rule.level, self.log.warning)

            log_fn(
                "alert_triggered",
                alert_level=rule.level,
                metric=rule.metric_name,
                value=value,
                threshold=rule.threshold,
                message=message,
            )

            await redis.set(cooldown_key, "1", ex=rule.cooldown_seconds)

        except Exception as exc:
            self.log.warning("metrics.alert_fire_failed", error=str(exc))

    def add_alert_rule(self, rule: AlertRule) -> None:
        """Register a custom alert rule at runtime."""
        self._alert_rules.append(rule)

    def remove_alert_rule(self, metric_name: str) -> None:
        """Remove all alert rules for a metric name."""
        self._alert_rules = [
            r for r in self._alert_rules if r.metric_name != metric_name
        ]

    # ------------------------------------------------------------------ #
    # Time-series helper                                                    #
    # ------------------------------------------------------------------ #

    async def _append_timeseries(
        self,
        name: str,
        value: float,
        tags: dict[str, str],
    ) -> None:
        """Append a data point to the time-series sorted set, trimming old points."""
        key = f"{self.METRICS_PREFIX}:ts:{name}"
        now = time.time()
        point = json.dumps({"value": value, "tags": tags})
        try:
            redis = await self._redis()
            await redis.zadd(key, {point: now})
            # Remove points older than retention window
            cutoff = now - self.TS_RETENTION_SECS
            await redis.zremrangebyscore(key, "-inf", cutoff)
            await redis.expire(key, self.TS_RETENTION_SECS + 3600)
        except Exception:
            pass  # Time-series append is best-effort — don't interrupt the caller


# --------------------------------------------------------------------------- #
# Module-level singleton                                                        #
# --------------------------------------------------------------------------- #

metrics = MetricsCollector()


# --------------------------------------------------------------------------- #
# Convenience decorators                                                        #
# --------------------------------------------------------------------------- #

def track_metric(
    name: str,
    metric_type: MetricType = MetricType.TIMER,
    tags: dict[str, str] | None = None,
) -> Callable[[F], F]:
    """
    Decorator that automatically records execution time (or increments a counter)
    for the decorated function.

    Usage:
        @track_metric("tts_synthesis", tags={"language": "en"})
        async def synthesize(self, text: str) -> TTSResult: ...

        @track_metric("job_processed", metric_type=MetricType.COUNTER)
        async def process_job(self, job_id: str) -> None: ...
    """
    def decorator(func: F) -> F:
        _tags = tags or {}

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                start = time.perf_counter()
                try:
                    result = await func(*args, **kwargs)
                    elapsed_ms = (time.perf_counter() - start) * 1000
                    if metric_type == MetricType.TIMER:
                        asyncio.create_task(metrics.timer(name, elapsed_ms, _tags))
                    else:
                        asyncio.create_task(metrics.increment(name, 1.0, _tags))
                    return result
                except Exception:
                    asyncio.create_task(
                        metrics.increment(f"{name}_errors", 1.0, _tags)
                    )
                    raise

            return async_wrapper  # type: ignore[return-value]

        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                start = time.perf_counter()
                try:
                    result = func(*args, **kwargs)
                    elapsed_ms = (time.perf_counter() - start) * 1000
                    # Sync functions: fire-and-forget via asyncio if loop running
                    try:
                        loop = asyncio.get_running_loop()
                        if metric_type == MetricType.TIMER:
                            loop.create_task(metrics.timer(name, elapsed_ms, _tags))
                        else:
                            loop.create_task(metrics.increment(name, 1.0, _tags))
                    except RuntimeError:
                        pass  # No event loop — skip metric recording in sync context
                    return result
                except Exception:
                    raise

            return sync_wrapper  # type: ignore[return-value]

    return decorator


async def alert_if(
    metric_name: str,
    value: float,
    threshold: float,
    condition: str,
    level: AlertLevel = AlertLevel.WARNING,
    message: str = "",
    cooldown_seconds: int = 300,
) -> None:
    """
    One-shot alert check without registering a persistent rule.
    Use for ad-hoc threshold checks inside pipeline stages.

    Usage:
        await alert_if(
            "render_cost_usd", value=render_cost,
            threshold=1.0, condition="gt",
            level=AlertLevel.WARNING,
            message=f"Scene render cost ${render_cost:.2f} exceeded $1.00"
        )
    """
    rule = AlertRule(
        metric_name=metric_name,
        threshold=threshold,
        level=level,
        condition=condition,
        message_template=message or (
            f"{metric_name} {{value:.3f}} exceeded threshold {{threshold:.3f}}"
        ),
        cooldown_seconds=cooldown_seconds,
    )
    if metrics._condition_met(value, condition, threshold):
        await metrics._fire_alert(rule, value)

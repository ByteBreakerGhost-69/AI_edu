# products/edu_video/backend/utils/__init__.py
"""
Shared utility modules for the EduVideo platform.
Import pattern:
    from utils.logging import get_logger, log_execution_time, log_pipeline_stage
    from utils.monitoring import metrics, track_metric, alert_if
    from utils.cache import cache_result, invalidate_cache, LRUCache
"""

from utils.logging import (
    configure_logging,
    get_logger,
    bind_request_context,
    clear_request_context,
    log_execution_time,
    log_pipeline_stage,
    SampledLogger,
    mask_sensitive_data,
)
from utils.monitoring import (
    MetricType,
    AlertLevel,
    MetricPoint,
    AlertRule,
    MetricsCollector,
    metrics,
    track_metric,
    alert_if,
)
from utils.cache import (
    cache_result,
    invalidate_cache,
    invalidate_pattern,
    LRUCache,
    local_lru_cache,
    CacheStats,
    get_cache_stats,
)

__all__ = [
    # logging
    "configure_logging",
    "get_logger",
    "bind_request_context",
    "clear_request_context",
    "log_execution_time",
    "log_pipeline_stage",
    "SampledLogger",
    "mask_sensitive_data",
    # monitoring
    "MetricType",
    "AlertLevel",
    "MetricPoint",
    "AlertRule",
    "MetricsCollector",
    "metrics",
    "track_metric",
    "alert_if",
    # cache
    "cache_result",
    "invalidate_cache",
    "invalidate_pattern",
    "LRUCache",
    "local_lru_cache",
    "CacheStats",
    "get_cache_stats",
]

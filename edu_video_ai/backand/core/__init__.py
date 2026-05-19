"""
backend/core/__init__.py

Public API surface for the core package.

Import from here instead of sub-modules whenever possible:

    from backend.core import settings
    from backend.core import LLMFactory, LLMProvider
    from backend.core import get_qdrant_client, init_qdrant_client
    from backend.core import get_db_session, get_redis
    from backend.core import generate_job_id, utc_now
"""

# ── Configuration ─────────────────────────────────────────────────────────────
from backend.core.config import Settings, get_settings, settings

# ── Database (PostgreSQL + Redis) ─────────────────────────────────────────────
from backend.core.database import (
    Base,
    close_db_connections,
    create_all_tables,
    get_db_session,
    get_redis,
    init_db_connections,
    redis_pipeline,
)

# ── Qdrant ────────────────────────────────────────────────────────────────────
from backend.core.qdrant import (
    close_qdrant_client,
    collection_info,
    ensure_collection,
    get_qdrant_client,
    init_qdrant_client,
)

# ── LLM Factory ───────────────────────────────────────────────────────────────
from backend.core.llm import (
    CURRICULUM_AGENT_CONFIG,
    FACT_CHECKER_AGENT_CONFIG,
    SCRIPT_AGENT_CONFIG,
    VISUAL_ASSET_AGENT_CONFIG,
    LLMFactory,
    LLMProvider,
    ModelConfig,
)

# ── Utilities ─────────────────────────────────────────────────────────────────
from backend.core.utils import (
    IDPrefix,
    async_retry,
    chunk_list,
    content_cache_key,
    elapsed_ms,
    generate_asset_id,
    generate_chunk_id,
    generate_id,
    generate_job_id,
    generate_scene_id,
    generate_session_id,
    sha256_hex,
    truncate_string,
    utc_now,
    utc_now_iso,
)

__all__ = [
    # config
    "Settings",
    "get_settings",
    "settings",
    # database
    "Base",
    "close_db_connections",
    "create_all_tables",
    "get_db_session",
    "get_redis",
    "init_db_connections",
    "redis_pipeline",
    # qdrant
    "close_qdrant_client",
    "collection_info",
    "ensure_collection",
    "get_qdrant_client",
    "init_qdrant_client",
    # llm
    "CURRICULUM_AGENT_CONFIG",
    "FACT_CHECKER_AGENT_CONFIG",
    "LLMFactory",
    "LLMProvider",
    "ModelConfig",
    "SCRIPT_AGENT_CONFIG",
    "VISUAL_ASSET_AGENT_CONFIG",
    # utils
    "IDPrefix",
    "async_retry",
    "chunk_list",
    "content_cache_key",
    "elapsed_ms",
    "generate_asset_id",
    "generate_chunk_id",
    "generate_id",
    "generate_job_id",
    "generate_scene_id",
    "generate_session_id",
    "sha256_hex",
    "truncate_string",
    "utc_now",
    "utc_now_iso",
]


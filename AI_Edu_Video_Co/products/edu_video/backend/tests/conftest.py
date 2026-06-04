# products/edu_video/backend/tests/conftest.py
"""
Shared pytest fixtures for all EduVideo test files.
All external dependencies (Redis, DB, LLM, Stripe) are mocked here.
Import pattern: fixtures are auto-discovered by pytest from conftest.py.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4


# --------------------------------------------------------------------------- #
# Settings                                                                      #
# --------------------------------------------------------------------------- #

@pytest.fixture
def test_settings():
    """Override Settings with safe test values — no real API keys."""
    from core.config import Settings
    return Settings(
        APP_NAME="EduVideo-Test",
        APP_ENV="test",
        DEBUG=True,
        SECRET_KEY="test-secret-key-32chars-minimum!!",
        POSTGRES_URL="postgresql+asyncpg://test:test@localhost:5432/test_db",
        REDIS_URL="redis://localhost:6379/15",
        QDRANT_HOST="localhost",
        QDRANT_PORT=6333,
        QDRANT_API_KEY="test-qdrant-key",
        QDRANT_COLLECTION_NAME="test_collection",
        ANTHROPIC_API_KEY="test-anthropic-key-sk-ant-xxx",
        GROQ_API_KEY="test-groq-key",
        DEFAULT_LLM_PROVIDER="claude",
        JWT_SECRET="test-jwt-secret-minimum-32chars!!",
        JWT_ALGORITHM="HS256",
        ACCESS_TOKEN_EXPIRE_MINUTES=30,
        GCS_BUCKET_NAME="test-bucket",
        GCS_PROJECT_ID="test-project",
        GCS_OUTPUT_PREFIX="outputs/",
        CDN_BASE_URL="https://cdn.test.eduvideo.ai",
        GCS_SIGNED_URL_EXPIRY_HOURS=24,
        STRIPE_SECRET_KEY="sk_test_xxx",
        STRIPE_WEBHOOK_SECRET="whsec_test_xxx",
        STRIPE_PREMIUM_PRICE_ID="price_test_xxx",
        STRIPE_PREMIUM_PRODUCT_ID="prod_test_xxx",
        FREE_VIDEOS_PER_MONTH=3,
        PREMIUM_VIDEOS_PER_MONTH=50,
        FREE_MAX_SCENES=4,
        PREMIUM_MAX_SCENES=8,
        SUBSCRIPTION_TRIAL_DAYS=7,
        INVOICE_FROM_EMAIL="billing@test.eduvideo.ai",
        TIER_CONFIG_PATH="/tmp/test_tier_limits.yaml",
        RENDER_TEMP_DIR="/tmp/test_edu_video",
        RENDER_FPS=30,
        MANIM_QUALITY="low",
        PUPPETEER_EXECUTABLE="/usr/bin/chromium-browser",
        MERMAID_CLI_PATH="/usr/local/bin/mmdc",
        FLUX_API_KEY="test-flux-key",
        FLUX_API_URL="https://api.bfl.ml/v1",
        KLING_API_KEY="test-kling-key",
        KLING_API_URL="https://api.klingai.com/v1",
        CDN_BASE_URL="https://cdn.test.eduvideo.ai",
        REVIEW_QUEUE_KEY="edu_video:review_queue:test",
        REVIEW_AUTO_APPROVE_THRESHOLD=0.85,
        PARTIAL_REGEN_MAX_RETRIES=2,
        ANALYTICS_REDIS_TTL_DAYS=7,
        WORKER_CONCURRENCY=1,
        WORKER_POLL_INTERVAL_SECONDS=0.1,
        WORKER_MAX_JOB_RETRIES=2,
        WORKER_JOB_TIMEOUT_SECONDS=30,
        WORKER_HEARTBEAT_INTERVAL=10,
        LANGGRAPH_CHECKPOINTING=False,
        MAX_VIDEO_DURATION_SECONDS=300,
    )


@pytest.fixture(autouse=True)
def patch_settings(test_settings, mocker):
    """Auto-patch get_settings() for every test — no opt-out needed."""
    mocker.patch("core.config.get_settings", return_value=test_settings)
    # Also patch in common import locations
    for module in [
        "utils.logging",
        "utils.cache",
        "utils.monitoring",
        "billing.tier_config",
        "billing.usage_limiter",
        "billing.subscription_service",
    ]:
        try:
            mocker.patch(f"{module}.get_settings", return_value=test_settings)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Redis mock                                                                    #
# --------------------------------------------------------------------------- #

@pytest.fixture
def mock_redis(mocker):
    """
    Mock async Redis client with all commonly used operations pre-configured.
    Configure per-test: mock_redis.get.return_value = b'{"key": "val"}'
    """
    redis = AsyncMock()
    redis.get.return_value = None
    redis.set.return_value = True
    redis.setex.return_value = True
    redis.delete.return_value = 1
    redis.exists.return_value = 0
    redis.incr.return_value = 1
    redis.incrbyfloat.return_value = 1.0
    redis.lpush.return_value = 1
    redis.rpush.return_value = 1
    redis.llen.return_value = 0
    redis.lrange.return_value = []
    redis.ltrim.return_value = True
    redis.brpop.return_value = None
    redis.hset.return_value = 1
    redis.hget.return_value = None
    redis.hgetall.return_value = {}
    redis.hmset.return_value = True
    redis.zadd.return_value = 1
    redis.zcard.return_value = 0
    redis.zrange.return_value = []
    redis.zrangebyscore.return_value = []
    redis.zrangebyrank = AsyncMock(return_value=[])
    redis.zremrangebyscore.return_value = 0
    redis.zremrangebyrank.return_value = 0
    redis.zpopmin.return_value = []
    redis.zrank.return_value = 0
    redis.zrem.return_value = 1
    redis.sadd.return_value = 1
    redis.srem.return_value = 1
    redis.smembers.return_value = set()
    redis.ping.return_value = True
    redis.expire.return_value = True
    redis.publish.return_value = 1
    redis.info.return_value = {"used_memory": 1_048_576, "used_memory_peak": 2_097_152, "maxmemory": 0}
    redis.scan_iter = AsyncMock(return_value=aiter([]))
    redis.aclose = AsyncMock()

    mocker.patch("core.database.get_redis_client", return_value=redis)
    mocker.patch("core.database._redis_client", redis)
    return redis


# --------------------------------------------------------------------------- #
# DB session mock                                                               #
# --------------------------------------------------------------------------- #

@pytest.fixture
def mock_db_session(mocker):
    """
    Mock AsyncSession. Pre-configured for common query patterns.
    Override per-test: mock_db_session.get.return_value = my_model_instance
    """
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.get.return_value = None

    execute_result = AsyncMock()
    execute_result.scalar_one_or_none = MagicMock(return_value=None)
    execute_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[]))
    )
    execute_result.all = MagicMock(return_value=[])
    session.execute = AsyncMock(return_value=execute_result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.close = AsyncMock()

    mocker.patch("core.database.AsyncSessionLocal", return_value=session)
    return session


# --------------------------------------------------------------------------- #
# LLM mock                                                                      #
# --------------------------------------------------------------------------- #

@pytest.fixture
def mock_llm(mocker):
    """
    Mock LangChain LLM returning valid JSON by default.
    Configure per-test: mock_llm.ainvoke.return_value.content = '{"key": "val"}'
    """
    llm = AsyncMock()
    default_response = MagicMock()
    default_response.content = '{"result": "mocked_llm_response"}'
    llm.ainvoke.return_value = default_response

    embedding_model = AsyncMock()
    embedding_model.aembed_query = AsyncMock(return_value=[0.1] * 1536)
    embedding_model.aembed_documents = AsyncMock(return_value=[[0.1] * 1536])

    mock_factory = MagicMock()
    mock_factory.get_llm.return_value = llm
    mock_factory.get_embedding_model.return_value = embedding_model

    mocker.patch("core.llm.llm_factory", mock_factory)
    return llm


# --------------------------------------------------------------------------- #
# Model factories                                                               #
# --------------------------------------------------------------------------- #

@pytest.fixture
def user_factory():
    """Create test User ORM instances with sensible defaults."""
    from models.user import User

    def make(**kwargs):
        uid = uuid4()
        defaults = {
            "id": uid,
            "email": f"user_{str(uid)[:8]}@test.com",
            "hashed_password": "$2b$12$testhash",
            "full_name": "Test User",
            "role": "free",
            "is_active": True,
            "is_verified": True,
        }
        defaults.update(kwargs)
        return User(**defaults)

    return make


@pytest.fixture
def premium_user_factory(user_factory):
    """Create premium-tier test User instances."""
    def make(**kwargs):
        return user_factory(role="premium", **kwargs)
    return make


@pytest.fixture
def job_factory():
    """Create test Job ORM instances."""
    from models.job import Job
    from decimal import Decimal

    def make(**kwargs):
        defaults = {
            "id": uuid4(),
            "user_id": uuid4(),
            "title": "Introduction to Calculus",
            "subject": "mathematics",
            "curriculum": "general",
            "difficulty_level": "intermediate",
            "language": "en",
            "input_text": "Explain derivatives",
            "status": "pending",
            "total_cost_usd": Decimal("0.00"),
            "metadata": {},
        }
        defaults.update(kwargs)
        return Job(**defaults)

    return make


@pytest.fixture
def subscription_factory():
    """Create test Subscription ORM instances."""
    from models.subscription import Subscription

    def make(**kwargs):
        defaults = {
            "id": uuid4(),
            "user_id": uuid4(),
            "tier": "free",
            "status": "active",
            "videos_used_this_month": 0,
            "videos_limit_per_month": 3,
            "cancel_at_period_end": False,
            "stripe_customer_id": None,
            "stripe_subscription_id": None,
            "current_period_start": None,
            "current_period_end": None,
            "trial_end": None,
        }
        defaults.update(kwargs)
        return Subscription(**defaults)

    return make


@pytest.fixture
def final_scene_package_factory():
    """Create test FinalScenePackage instances."""
    from layer4_script_visual.schemas import (
        FinalScenePackage,
        RefinedScript,
        VisualSpec,
        TTSInstructions,
    )

    def make(scene_index: int = 0, renderer_type: str = "lottie", **kwargs):
        tts = TTSInstructions(
            speaking_rate=1.0,
            pitch="medium",
            emphasis_words=["calculus"],
            pause_after_sentences=[1, 3],
            language_code="en-US",
        )
        script = RefinedScript(
            scene_index=scene_index,
            title=f"Scene {scene_index + 1}: Introduction",
            narration_text=(
                "Calculus is the mathematics of change and accumulation. "
                "It has two main branches: differential calculus and integral calculus."
            ),
            narration_ssml=(
                "<speak>Calculus is the mathematics of change and accumulation.</speak>"
            ),
            hook_sentence="Have you ever wondered how fast something changes?",
            key_terms=["derivative", "integral", "limit"],
            estimated_word_count=22,
            estimated_duration_seconds=30.0,
            tts_instructions=tts,
        )
        visual = VisualSpec(
            renderer_type=renderer_type,
            primary_content='["x^2", "2x"]' if renderer_type == "manim" else "Test content",
            secondary_content=None,
            color_palette=["#1F2937", "#3B82F6", "#8B5CF6", "#F9FAFB"],
            dimensions={"width": 1920, "height": 1080},
            animation_config={"animation_type": "text_reveal"},
            asset_references=[],
            generation_prompt=None,
        )
        pkg_defaults = {
            "scene_index": scene_index,
            "title": f"Scene {scene_index + 1}",
            "refined_script": script,
            "visual_spec": visual,
            "renderer_type": renderer_type,
            "estimated_duration_seconds": 30.0,
            "subject": "mathematics",
            "curriculum": "general",
            "difficulty_level": "intermediate",
            "language": "en",
            "metadata": {
                "job_id": str(uuid4()),
                "user_id": str(uuid4()),
            },
        }
        pkg_defaults.update(kwargs)
        return FinalScenePackage(**pkg_defaults)

    return make


# --------------------------------------------------------------------------- #
# GraphState fixture                                                             #
# --------------------------------------------------------------------------- #

@pytest.fixture
def base_graph_state():
    """Minimal valid GraphState dict for agent unit tests."""
    return {
        "job_id": "test-job-id-123",
        "user_id": "test-user-id-456",
        "title": "Introduction to Derivatives",
        "subject": "mathematics",
        "curriculum": "IB",
        "difficulty_level": "intermediate",
        "language": "en",
        "input_text": "Explain what a derivative is and how to calculate it",
        "input_image_url": None,
        "target_scene_count": 6,
        "curriculum_standards": ["Math AA HL 5.1", "Math AA HL 5.2"],
        "learning_objectives": [
            "Define derivative as a limit",
            "Apply differentiation rules",
        ],
        "prerequisite_concepts": ["limits", "functions"],
        "subject_profile": {},
        "renderer_preference": ["manim", "diagram", "lottie"],
        "validation_rules": ["check_equation_syntax"],
        "similar_jobs": [],
        "memory_context": "",
        "reuse_assets": [],
        "scenes": [],
        "fact_check_passed": False,
        "fact_check_issues": [],
        "fact_check_iteration": 0,
        "animation_assignments": {},
        "total_cost_usd": 0.0,
        "cost_breakdown": [],
        "current_node": "",
        "errors": [],
        "retry_count": 0,
        "pipeline_metadata": {},
    }


# --------------------------------------------------------------------------- #
# LRU cache reset                                                               #
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def reset_lru_caches():
    """Clear all module-level LRU caches between tests to prevent state bleed."""
    yield
    try:
        from utils.cache import (
            _tier_config_cache,
            _subject_profile_cache,
            _curriculum_prompt_cache,
        )
        _tier_config_cache.clear()
        _subject_profile_cache.clear()
        _curriculum_prompt_cache.clear()
    except ImportError:
        pass


# --------------------------------------------------------------------------- #
# Async iterator helper                                                          #
# --------------------------------------------------------------------------- #

async def aiter(iterable):
    """Helper to create async iterators for mock_redis.scan_iter."""
    for item in iterable:
        yield item

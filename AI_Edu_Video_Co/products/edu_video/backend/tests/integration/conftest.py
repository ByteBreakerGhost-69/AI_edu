# products/edu_video/backend/tests/integration/conftest.py
"""
Integration test fixtures.
Wires real async components: SQLite in-memory DB, fakeredis, FastAPI TestClient.
All external APIs (LLM, GCS, TTS, Stripe, FFmpeg) are mocked.
"""

import json
import time
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


# --------------------------------------------------------------------------- #
# SQLite in-memory engine (session-scoped — one DB for all tests)             #
# --------------------------------------------------------------------------- #

@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """
    SQLite in-memory async engine shared across the test session.
    StaticPool keeps a single connection alive (required for :memory: DBs).

    Limitations vs PostgreSQL:
      - No JSONB (use String / JSON)
      - No native UUID type (use String)
      - No SELECT FOR UPDATE (no row locking)
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )

    from core.database import Base
    import models.user        # noqa: F401
    import models.job         # noqa: F401
    import models.scene       # noqa: F401
    import models.feedback    # noqa: F401
    import models.subscription # noqa: F401
    import models.invoice     # noqa: F401
    import models.review      # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def test_db(test_engine):
    """
    Per-test AsyncSession wrapped in a nested transaction.
    All DB writes are rolled back after each test — no state bleeds.
    """
    async with test_engine.connect() as conn:
        await conn.begin()
        session_factory = async_sessionmaker(
            bind=conn,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        session = session_factory()
        try:
            yield session
        finally:
            await session.close()
            await conn.rollback()


# --------------------------------------------------------------------------- #
# Fake Redis (per-test — clean state every time)                               #
# --------------------------------------------------------------------------- #

@pytest_asyncio.fixture
async def fake_redis():
    """
    In-process fakeredis instance supporting all redis.asyncio operations.
    Flushed and closed after each test.
    """
    server = fakeredis.aioredis.FakeRedis(version=(7, 0, 0), decode_responses=False)
    yield server
    await server.flushall()
    await server.aclose()


@pytest_asyncio.fixture(autouse=True)
async def patch_redis(fake_redis, mocker):
    """Auto-patch Redis for all integration tests."""
    mocker.patch("core.database.get_redis_client", return_value=fake_redis)
    mocker.patch("core.database._redis_client", fake_redis)
    return fake_redis


@pytest_asyncio.fixture(autouse=True)
async def patch_db_session(test_db, mocker):
    """Auto-patch AsyncSessionLocal to use the test transaction session."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=test_db)
    cm.__aexit__ = AsyncMock(return_value=None)
    mocker.patch("core.database.AsyncSessionLocal", return_value=cm)


# --------------------------------------------------------------------------- #
# External API mocks                                                            #
# --------------------------------------------------------------------------- #

@pytest.fixture
def mock_anthropic_llm(mocker):
    """
    Mock all LLM calls with sequenced realistic responses.
    Simulates: subject detection → curriculum selection → curriculum agent
               → script agent → visual agent → fact checker.
    """
    responses = {
        "subject_detection": json.dumps({
            "detected_subject": "mathematics",
            "confidence": 0.95,
            "alternative_subjects": ["physics"],
            "reasoning": "High density of calculus terminology",
        }),
        "curriculum_selection": json.dumps({
            "selected_curriculum": "IB",
            "reasoning": "IB terminology detected",
            "key_standards": ["Math AA HL 5.1"],
        }),
        "curriculum": json.dumps({
            "curriculum_standards": ["Math AA HL 5.1", "Math AA HL 5.2"],
            "learning_objectives": [
                "Define the derivative as a limit",
                "Apply the chain rule",
            ],
            "prerequisite_concepts": ["limits", "functions"],
        }),
        "script": json.dumps({
            "scenes": [
                {
                    "scene_index": i,
                    "title": f"Scene {i + 1}: Derivatives Part {i + 1}",
                    "narration_text": (
                        f"In this scene we explore derivative concept {i + 1}. "
                        "The derivative measures the instantaneous rate of change. "
                        "We apply this concept to problems in velocity and acceleration."
                    ),
                    "content_type": "equation",
                }
                for i in range(6)
            ]
        }),
        "visual": json.dumps({
            "visual_descriptions": [
                {
                    "scene_index": i,
                    "visual_description": "Show equation f prime of x equals two x",
                    "visual_elements": ["equation", "graph"],
                    "color_hints": ["#3B82F6", "#1F2937"],
                }
                for i in range(6)
            ]
        }),
        "fact_check": json.dumps({
            "fact_check_passed": True,
            "confidence_score": 0.92,
            "issues": [],
            "retry_hint": None,
        }),
        "memory": json.dumps({
            "memory_context": "",
            "similar_jobs": [],
            "reuse_assets": [],
        }),
        "animation": json.dumps({
            "scene_assignments": [
                {"scene_index": i, "renderer_type": "lottie"}
                for i in range(6)
            ]
        }),
    }

    sequence = [
        "subject_detection",
        "curriculum_selection",
        "curriculum",
        "memory",
        "script",
        "visual",
        "fact_check",
        "animation",
    ]
    call_count: dict = {"n": 0}

    async def mock_ainvoke(*args, **kwargs):
        idx = call_count["n"] % len(sequence)
        key = sequence[idx]
        call_count["n"] += 1
        resp = MagicMock()
        resp.content = responses.get(key, '{"result": "ok"}')
        return resp

    llm = AsyncMock()
    llm.ainvoke = mock_ainvoke
    llm.with_fallbacks = MagicMock(return_value=llm)

    embedding = AsyncMock()
    embedding.aembed_query = AsyncMock(return_value=[0.1] * 1536)
    embedding.aembed_documents = AsyncMock(return_value=[[0.1] * 1536])

    factory = MagicMock()
    factory.get_llm = MagicMock(return_value=llm)
    factory.get_embedding_model = MagicMock(return_value=embedding)

    mocker.patch("core.llm.llm_factory", factory)
    return {"llm": llm, "responses": responses, "call_count": call_count}


@pytest.fixture
def mock_qdrant(mocker):
    """Mock Qdrant — returns empty search results (no similar jobs in memory)."""
    client = AsyncMock()
    client.search_vectors = AsyncMock(return_value=[])
    client.upsert_vectors = AsyncMock(return_value=None)
    client.ensure_collection_exists = AsyncMock(return_value=None)
    client.delete_vectors = AsyncMock(return_value=None)
    mocker.patch("core.qdrant.get_qdrant_client", return_value=client)
    return client


@pytest.fixture
def mock_gcs(mocker):
    """Mock GCS — all uploads succeed, return predictable URLs."""
    blob = MagicMock()
    blob.upload_from_filename = MagicMock(return_value=None)
    blob.generate_signed_url = MagicMock(
        return_value="https://storage.googleapis.com/test-bucket/signed-url"
    )
    blob.metadata = {}
    blob.patch = MagicMock()
    blob.exists = MagicMock(return_value=False)

    bucket = MagicMock()
    bucket.blob = MagicMock(return_value=blob)

    client = MagicMock()
    client.bucket = MagicMock(return_value=bucket)

    mocker.patch("google.cloud.storage.Client", return_value=client)
    return client


@pytest.fixture
def mock_tts(mocker):
    """
    Mock Google Cloud TTS.
    Returns minimal MP3 bytes and realistic 30s duration per scene.
    """
    MOCK_MP3 = bytes([0xFF, 0xFB, 0x90, 0x00] + [0x00] * 256)

    async def synthesize(input, voice, audio_config):
        resp = MagicMock()
        resp.audio_content = MOCK_MP3
        return resp

    tts_client = AsyncMock()
    tts_client.synthesize_speech = synthesize

    mocker.patch(
        "google.cloud.texttospeech.TextToSpeechAsyncClient",
        return_value=tts_client,
    )
    mocker.patch(
        "layer5_rendering.tts_service.MP3",
        return_value=MagicMock(info=MagicMock(length=30.0)),
    )
    return tts_client


@pytest.fixture
def mock_ffmpeg(mocker):
    """Mock FFmpeg — all operations succeed, probe returns valid video metadata."""
    mocker.patch(
        "ffmpeg.probe",
        return_value={
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30/1",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "sample_rate": "44100",
                },
            ],
            "format": {
                "duration": "30.0",
                "size": "102400",
                "filename": "test.mp4",
            },
        },
    )

    stream = MagicMock()
    stream.overwrite_output = MagicMock(return_value=stream)
    stream.run = MagicMock(return_value=(b"", b""))
    stream.output = MagicMock(return_value=stream)
    stream.filter = MagicMock(return_value=stream)
    stream.audio = stream
    stream.video = stream

    mocker.patch("ffmpeg.input", return_value=stream)
    mocker.patch("ffmpeg.output", return_value=stream)
    mocker.patch("ffmpeg.concat", return_value=stream)
    return stream


@pytest.fixture
def mock_renderers(mocker, tmp_path):
    """
    Stub all renderer render() calls to write minimal MP4 bytes.
    Files are large enough to pass _validate_output() (> 1 KB).
    """
    STUB_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 2048

    async def stub_render(package, output_path: str) -> str:
        from pathlib import Path
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(STUB_MP4)
        return output_path

    renderer_modules = [
        ("layer5_rendering.renderers.manim_renderer",    "ManimRenderer"),
        ("layer5_rendering.renderers.lottie_renderer",   "LottieRenderer"),
        ("layer5_rendering.renderers.flux_sdxl_renderer","FluxSDXLRenderer"),
        ("layer5_rendering.renderers.kling_renderer",    "KlingRenderer"),
        ("layer5_rendering.renderers.timeline_renderer", "TimelineRenderer"),
        ("layer5_rendering.renderers.diagram_renderer",  "DiagramRenderer"),
        ("layer5_rendering.renderers.graph_renderer",    "GraphRenderer"),
        ("layer5_rendering.renderers.code_renderer",     "CodeRenderer"),
    ]

    mocks = {}
    for module_path, class_name in renderer_modules:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            mock_instance = MagicMock()
            mock_instance.render = stub_render
            mock_cls = MagicMock(return_value=mock_instance)
            mocker.patch.object(mod, class_name, mock_cls)
            mocks[class_name] = mock_instance
        except (ImportError, AttributeError):
            pass

    return mocks


# --------------------------------------------------------------------------- #
# Auth helpers                                                                  #
# --------------------------------------------------------------------------- #

@pytest.fixture
def auth_headers_factory(test_settings):
    """Generate valid JWT auth headers for any user identity."""
    def make(user_id: str, email: str, role: str = "free") -> dict[str, str]:
        from core.auth import create_access_token
        token = create_access_token(
            data={"sub": email, "user_id": user_id, "role": role},
            expires_delta=timedelta(minutes=30),
        )
        return {"Authorization": f"Bearer {token}"}
    return make


# --------------------------------------------------------------------------- #
# Test application                                                              #
# --------------------------------------------------------------------------- #

@pytest_asyncio.fixture
async def test_app(
    test_db,
    fake_redis,
    mock_anthropic_llm,
    mock_qdrant,
    mock_gcs,
    mocker,
):
    """
    Configured FastAPI test application with all integrations wired.
    Startup lifecycle steps that require real connections are stubbed.
    """
    mocker.patch("core.database.init_db", AsyncMock())
    mocker.patch(
        "core.qdrant.ensure_collection_exists", AsyncMock()
    )
    mocker.patch("billing.tier_config.tier_config.load", MagicMock())

    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client


# --------------------------------------------------------------------------- #
# DB seed helpers (importable in test files)                                    #
# --------------------------------------------------------------------------- #

async def seed_test_user(
    db: AsyncSession,
    user_id: str | None = None,
    email: str | None = None,
    role: str = "free",
):
    """Create and persist a User in the integration test DB."""
    from models.user import User
    from core.auth import get_password_hash

    uid = user_id or str(uuid4())
    user = User(
        id=uid,
        email=email or f"user_{uuid4().hex[:8]}@test.com",
        hashed_password=get_password_hash("testpassword123"),
        full_name="Integration Test User",
        role=role,
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def seed_test_subscription(
    db: AsyncSession,
    user_id: str,
    tier: str = "free",
    videos_used: int = 0,
):
    """Create and persist a Subscription in the integration test DB."""
    from models.subscription import Subscription

    sub = Subscription(
        id=str(uuid4()),
        user_id=user_id,
        tier=tier,
        status="active",
        videos_used_this_month=videos_used,
        videos_limit_per_month=3 if tier == "free" else 50,
        cancel_at_period_end=False,
    )
    db.add(sub)
    await db.commit()
    return sub


async def seed_test_job(
    db: AsyncSession,
    user_id: str,
    status: str = "done",
    subject: str = "mathematics",
    curriculum: str = "general",
):
    """Create and persist a Job in the integration test DB."""
    from models.job import Job
    from decimal import Decimal

    job = Job(
        id=str(uuid4()),
        user_id=user_id,
        title="Integration Test Job",
        subject=subject,
        curriculum=curriculum,
        difficulty_level="intermediate",
        language="en",
        input_text="Explain derivatives.",
        status=status,
        total_cost_usd=Decimal("0.05"),
        metadata={},
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job

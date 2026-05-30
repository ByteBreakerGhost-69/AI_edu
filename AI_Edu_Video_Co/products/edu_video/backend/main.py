# products/edu_video/backend/main.py
"""
FastAPI application entrypoint for the EduVideo AI platform.
Wires all layers, configures middleware, registers routers,
and manages startup/shutdown lifecycle.
"""

import logging
import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from core.config import get_settings
from core.utils import generate_uuid

settings = get_settings()

# --------------------------------------------------------------------------- #
# Structlog configuration                                                      #
# Must be done before any logger is created — place at module level.          #
# --------------------------------------------------------------------------- #

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        (
            structlog.processors.JSONRenderer()
            if settings.APP_ENV == "prod"
            else structlog.dev.ConsoleRenderer()
        ),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logging.basicConfig(
    format="%(message)s",
    level=logging.INFO if settings.APP_ENV == "prod" else logging.DEBUG,
)

# Suppress noisy third-party loggers in production
if settings.APP_ENV == "prod":
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


# --------------------------------------------------------------------------- #
# Lifespan                                                                     #
# --------------------------------------------------------------------------- #

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup and shutdown lifecycle manager.
    Startup order is intentional — do not reorder without understanding deps.
    """
    log = structlog.get_logger("startup")

    # ------------------------------------------------------------------ #
    # STARTUP                                                              #
    # ------------------------------------------------------------------ #

    # 1. PostgreSQL — create tables
    from core.database import init_db  # noqa: PLC0415
    await init_db()
    log.info("database_initialized")

    # 2. Qdrant — ensure vector collections exist
    try:
        from core.qdrant import ensure_collection_exists  # noqa: PLC0415
        await ensure_collection_exists(vector_size=1536)
        log.info("qdrant_collections_ready")
    except Exception as exc:
        # Qdrant unavailable at startup — log warning but don't block
        # RAG will degrade gracefully until Qdrant recovers
        log.warning("qdrant_init_warning", error=str(exc))

    # 3. LLM connectivity — non-blocking warm-up check
    try:
        from core.llm import llm_factory  # noqa: PLC0415
        llm_factory.get_llm()
        log.info("llm_ready", provider=settings.DEFAULT_LLM_PROVIDER)
    except Exception as exc:
        log.warning("llm_init_warning", error=str(exc))

    # 4. Redis — required; fail startup if unreachable
    from core.database import _create_redis_client  # noqa: PLC0415
    try:
        redis = await _create_redis_client()
        await redis.ping()
        log.info("redis_ready")
    except Exception as exc:
        log.error("redis_connection_failed", error=str(exc))
        raise RuntimeError(f"Redis is required but unavailable: {exc}") from exc

    # 5. Subject profile registry integrity check
    try:
        from layer2_orchestrator.agents import PROFILE_REGISTRY  # noqa: PLC0415
        log.info(
            "profile_registry_loaded",
            profiles=len(PROFILE_REGISTRY),
            subjects=[s.value for s in PROFILE_REGISTRY],
        )
    except Exception as exc:
        log.warning("profile_registry_warning", error=str(exc))

    # 6. Billing tier config
    try:
        from billing.tier_config import tier_config  # noqa: PLC0415
        tier_config.load()
        log.info("tier_config_loaded")
    except Exception as exc:
        log.warning("tier_config_warning", error=str(exc))

    log.info(
        "application_started",
        app=settings.APP_NAME,
        env=settings.APP_ENV,
        version=app.version,
    )

    yield

    # ------------------------------------------------------------------ #
    # SHUTDOWN                                                             #
    # ------------------------------------------------------------------ #
    log.info("application_shutting_down")

    try:
        from core.database import _redis_client  # noqa: PLC0415
        if _redis_client is not None:
            await _redis_client.aclose()
            log.info("redis_closed")
    except Exception as exc:
        log.warning("redis_close_warning", error=str(exc))

    log.info("application_stopped")


# --------------------------------------------------------------------------- #
# App instance                                                                 #
# --------------------------------------------------------------------------- #

app = FastAPI(
    title="EduVideo AI API",
    description=(
        "AI-powered educational video generation platform. "
        "Converts educational text/image input into curriculum-aligned videos."
    ),
    version="1.0.0",
    docs_url="/docs" if settings.APP_ENV != "prod" else None,
    redoc_url="/redoc" if settings.APP_ENV != "prod" else None,
    openapi_url="/openapi.json" if settings.APP_ENV != "prod" else None,
    lifespan=lifespan,
)


# --------------------------------------------------------------------------- #
# Middleware (outermost first)                                                 #
# --------------------------------------------------------------------------- #

# 1. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",        # Next.js dev server
        "http://localhost:3001",        # alternative dev port
        "https://eduvideo.ai",
        "https://www.eduvideo.ai",
        "https://app.eduvideo.ai",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time"],
)

# 2. GZip (for large video metadata / scene JSON responses)
app.add_middleware(GZipMiddleware, minimum_size=1000)


# 3. Request logging + timing
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log every request with timing. Attach X-Request-ID to responses."""
    start = time.perf_counter()
    request_id = request.headers.get("X-Request-ID") or generate_uuid()

    log = structlog.get_logger("http").bind(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )
    log.info("request_started")

    try:
        response = await call_next(request)
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        log.error("request_failed", duration_ms=elapsed_ms, error=str(exc))
        raise

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    log.info(
        "request_completed",
        status_code=response.status_code,
        duration_ms=elapsed_ms,
    )

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time"] = f"{elapsed_ms}ms"
    return response


# --------------------------------------------------------------------------- #
# Exception handlers                                                           #
# --------------------------------------------------------------------------- #

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "validation_error",
            "detail": exc.errors(),
            "message": "Request validation failed.",
        },
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": "bad_request", "message": str(exc)},
    )


@app.exception_handler(PermissionError)
async def permission_error_handler(
    request: Request, exc: PermissionError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"error": "forbidden", "message": str(exc)},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log = structlog.get_logger("error")
    log.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        error_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred. Please try again.",
        },
    )


# --------------------------------------------------------------------------- #
# Router registration                                                          #
# --------------------------------------------------------------------------- #

# Auth endpoints (login, token refresh, register)
try:
    from core.auth import router as auth_router  # noqa: PLC0415
    app.include_router(auth_router, prefix="/auth", tags=["auth"])
except (ImportError, AttributeError):
    structlog.get_logger("startup").warning("auth_router_not_available")

# Layer 1: Job creation and management
from layer1_input.api_gateway import router as jobs_router  # noqa: PLC0415
app.include_router(jobs_router, prefix="/api/v1", tags=["jobs"])

# Billing
try:
    from billing.subscription_service import router as subscription_router  # noqa
    from billing.payment_gateway import router as payment_router  # noqa
    from billing.webhook_handler import router as webhook_router  # noqa
    from billing.invoice_service import router as invoice_router  # noqa

    app.include_router(subscription_router, prefix="/api/v1/billing", tags=["billing"])
    app.include_router(payment_router, prefix="/api/v1/billing", tags=["billing"])
    app.include_router(webhook_router, prefix="/webhooks", tags=["webhooks"])
    app.include_router(invoice_router, prefix="/api/v1/billing", tags=["billing"])
except (ImportError, AttributeError):
    structlog.get_logger("startup").warning("billing_routers_not_available")

# Layer 6: Review, feedback, analytics
try:
    from layer6_delivery.review.approval_service import router as review_router  # noqa
    app.include_router(review_router, prefix="/api/v1/review", tags=["review"])
except (ImportError, AttributeError):
    structlog.get_logger("startup").warning("review_router_not_available")

try:
    from layer6_delivery.feedback_service import router as feedback_router  # noqa
    app.include_router(feedback_router, prefix="/api/v1/feedback", tags=["feedback"])
except (ImportError, AttributeError):
    structlog.get_logger("startup").warning("feedback_router_not_available")

try:
    from layer6_delivery.analytics import router as analytics_router  # noqa
    app.include_router(analytics_router, prefix="/api/v1/analytics", tags=["analytics"])
except (ImportError, AttributeError):
    structlog.get_logger("startup").warning("analytics_router_not_available")

# Layer 3: RAG ingestion (admin-only)
try:
    from layer3_rag.ingestion.pipeline import router as ingestion_router  # noqa
    app.include_router(ingestion_router, prefix="/api/v1/admin/rag", tags=["admin"])
except (ImportError, AttributeError):
    structlog.get_logger("startup").warning("ingestion_router_not_available")


# --------------------------------------------------------------------------- #
# Health + readiness endpoints                                                 #
# --------------------------------------------------------------------------- #

@app.get("/health", tags=["system"], summary="Liveness check")
async def health_check() -> dict:
    """Liveness check — returns 200 if the process is alive."""
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "env": settings.APP_ENV,
        "version": "1.0.0",
    }


@app.get("/ready", tags=["system"], summary="Readiness check")
async def readiness_check() -> JSONResponse:
    """
    Deep readiness check — verifies PostgreSQL, Redis, and Qdrant connectivity.
    Returns 200 if all critical dependencies are reachable, 503 otherwise.
    Qdrant failure is treated as degraded (warning), not blocking (error).
    """
    checks: dict[str, str] = {}
    overall = True

    # PostgreSQL
    try:
        from core.database import AsyncSessionLocal  # noqa: PLC0415
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {str(exc)[:80]}"
        overall = False

    # Redis
    try:
        from core.database import _redis_client  # noqa: PLC0415
        if _redis_client:
            await _redis_client.ping()
            checks["redis"] = "ok"
        else:
            checks["redis"] = "error: client_not_initialised"
            overall = False
    except Exception as exc:
        checks["redis"] = f"error: {str(exc)[:80]}"
        overall = False

    # Qdrant (degraded — not blocking)
    try:
        from core.qdrant import get_qdrant_client  # noqa: PLC0415
        client = get_qdrant_client()
        await client.ensure_collection_exists(vector_size=1536)
        checks["qdrant"] = "ok"
    except Exception as exc:
        # Qdrant failure degrades RAG but doesn't block video generation
        checks["qdrant"] = f"degraded: {str(exc)[:80]}"

    return JSONResponse(
        status_code=status.HTTP_200_OK if overall else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"ready": overall, "checks": checks},
    )


@app.get("/", tags=["system"], summary="API root")
async def root() -> dict:
    return {
        "app": settings.APP_NAME,
        "version": "1.0.0",
        "docs": "/docs" if settings.APP_ENV != "prod" else "disabled in production",
        "health": "/health",
        "ready": "/ready",
    }


__all__ = ["app"]

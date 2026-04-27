"""
UMA Platform — Unified Migration Accelerator
FastAPI Backend — Main Entry Point (Production-hardened)
"""

import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.routes import (
    connections, jobs, tables, validation, ai, health, snowflake,
    auth, projects, drift, syncs, demo,
    settings as settings_routes,
)
from core.config import settings
from core.database import init_db
from core.middleware import (
    RateLimitMiddleware, RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware, RequestIDMiddleware,
)
from services.scheduler import start_scheduler_task, get_scheduler


# ─── Logging setup ────────────────────────────────────────────
def _setup_logging():
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    if settings.LOG_JSON:
        # Structured JSON logging for prod (friendly for Loki/Datadog)
        try:
            import structlog
            logging.basicConfig(
                format="%(message)s",
                stream=sys.stdout,
                level=level,
            )
            structlog.configure(
                processors=[
                    structlog.stdlib.add_log_level,
                    structlog.stdlib.add_logger_name,
                    structlog.processors.TimeStamper(fmt="iso"),
                    structlog.processors.StackInfoRenderer(),
                    structlog.processors.format_exc_info,
                    structlog.processors.JSONRenderer(),
                ],
                logger_factory=structlog.stdlib.LoggerFactory(),
            )
        except ImportError:
            logging.basicConfig(
                level=level,
                format="%(asctime)s %(levelname)s %(name)s: %(message)s"
            )
    else:
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            stream=sys.stdout,
        )

    # Reduce chatty third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)


_setup_logging()
logger = logging.getLogger("uma")


# ─── Sentry (optional) ────────────────────────────────────────
if settings.SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.ENVIRONMENT,
            traces_sample_rate=0.1 if settings.ENVIRONMENT == "production" else 1.0,
            profiles_sample_rate=0.1,
            integrations=[FastApiIntegration(), SqlalchemyIntegration()],
            send_default_pii=False,
        )
        logger.info("Sentry error tracking enabled")
    except ImportError:
        logger.warning("SENTRY_DSN set but sentry-sdk not installed")


# ─── Prometheus metrics (optional) ────────────────────────────
prometheus_instrumentator = None
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    prometheus_instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_respect_env_var=False,
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/api/metrics", "/api/health.*"],
    )
except ImportError:
    logger.info("prometheus-fastapi-instrumentator not installed — metrics disabled")


# ─── Lifespan ─────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"🚀 UMA Platform starting (env={settings.ENVIRONMENT})")

    # Initialize DB schema (in dev) or verify connectivity (in prod)
    try:
        await init_db()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.critical(f"Database initialization failed: {e}")
        raise

    # Warm up encryption cipher (fails fast if key is missing in prod)
    try:
        from core.security import get_cipher
        get_cipher()
        logger.info("✅ Credential encryption initialized")
    except Exception as e:
        if settings.ENVIRONMENT == "production":
            logger.critical(f"Encryption setup failed: {e}")
            raise
        logger.warning(f"Encryption not fully configured: {e}")

    # Start background scheduler
    try:
        await start_scheduler_task()
        logger.info("🕐 Scheduler started — 60s poll with leader election")
    except Exception as e:
        logger.warning(f"Scheduler startup failed: {e}")

    yield

    logger.info("🛑 UMA Platform shutting down...")
    get_scheduler().stop()


# ─── App ──────────────────────────────────────────────────────

app = FastAPI(
    title="UMA Platform API",
    description="Unified Migration Accelerator — Snowflake-native data migration & ingestion",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.ENVIRONMENT != "production" or settings.DEBUG else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" or settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.ENVIRONMENT != "production" or settings.DEBUG else None,
)


# ─── Middleware stack (order matters — executes outer→inner) ──
# 1. Security headers (always first — added to all responses)
app.add_middleware(SecurityHeadersMiddleware)

# 2. Request ID + logging
app.add_middleware(RequestIDMiddleware)

# 3. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
    max_age=3600,
)

# 4. Request size limit
app.add_middleware(RequestSizeLimitMiddleware)

# 5. Rate limiting
app.add_middleware(RateLimitMiddleware)

# 6. Gzip (innermost)
app.add_middleware(GZipMiddleware, minimum_size=1000)


# ─── Prometheus instrumentation ───────────────────────────────
if prometheus_instrumentator:
    prometheus_instrumentator.instrument(app).expose(app, endpoint="/api/metrics",
                                                      include_in_schema=False)


# ─── Global exception handlers ────────────────────────────────

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    # Never leak internals in 5xx errors in production
    detail = exc.detail
    if exc.status_code >= 500 and settings.ENVIRONMENT == "production":
        detail = "Internal server error"

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": detail,
            "request_id": getattr(request.state, "request_id", None),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Sanitize validation errors — don't include submitted values
    errors = []
    for err in exc.errors():
        errors.append({
            "loc": err.get("loc"),
            "msg": err.get("msg"),
            "type": err.get("type"),
        })
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Validation error",
            "errors": errors,
            "request_id": getattr(request.state, "request_id", None),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error" if settings.ENVIRONMENT == "production" else str(exc),
            "request_id": getattr(request.state, "request_id", None),
        },
    )


# ─── Public routes ────────────────────────────────────────────
app.include_router(health.router,      prefix="/api",              tags=["Health"])
app.include_router(auth.router,        prefix="/api/auth",         tags=["Auth"])

# ─── Protected routes ─────────────────────────────────────────
app.include_router(projects.router,    prefix="/api",              tags=["Projects"])
app.include_router(connections.router, prefix="/api/connections",  tags=["Connections"])
app.include_router(jobs.router,        prefix="/api/jobs",         tags=["Jobs"])
app.include_router(tables.router,      prefix="/api/tables",       tags=["Tables"])
app.include_router(validation.router,  prefix="/api/validation",   tags=["Validation"])
app.include_router(drift.router,       prefix="/api/drift",        tags=["Schema Drift"])
app.include_router(ai.router,          prefix="/api/ai",           tags=["AI"])
app.include_router(snowflake.router,   prefix="/api/snowflake",    tags=["Snowflake"])
app.include_router(settings_routes.router, prefix="/api/settings",     tags=["Settings"])
app.include_router(syncs.router,       prefix="/api/syncs",        tags=["Managed Syncs"])
app.include_router(demo.router,        prefix="/api/demo",         tags=["Demo"])


@app.get("/")
async def root():
    return {
        "name": "UMA Platform",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
    }

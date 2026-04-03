"""
FastAPI application entry point for Kolya BR Proxy.
AI Gateway service providing OpenAI-compatible access to AWS Bedrock Claude models.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.database import init_db
from app.api.v1.router import gateway_router
from app.api.anthropic.router import anthropic_router
from app.api.gemini.router import gemini_router
from app.api.admin.router import admin_router
from app.api.health import health_router
from app.middleware.security import SecurityMiddleware
from app.services.bedrock import BedrockClient

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class HealthCheckFilter(logging.Filter):
    """Filter out health check access logs to reduce noise."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return '"GET /health/' not in msg


# Apply filter to uvicorn access logger
logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup and shutdown events."""
    # Startup
    logger.info("Starting Kolya BR Proxy...")

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Initialize singleton Bedrock client and populate profile cache FIRST
    # so pricing updater can filter out unavailable global. profiles
    bedrock = BedrockClient.get_instance()
    logger.info("BedrockClient initialized")

    await bedrock.refresh_profile_cache()
    logger.info("Inference profile cache populated")

    # Initialize pricing data if database is empty
    from app.core.database import async_session_maker
    from app.services.pricing_updater import PricingUpdater
    from app.services.gemini_pricing_updater import GeminiPricingUpdater
    from sqlalchemy import select, func
    from app.models.model_pricing import ModelPricing

    async with async_session_maker() as db:
        result = await db.execute(select(func.count(ModelPricing.id)))
        count = result.scalar()

        updater = PricingUpdater(db)
        if count == 0:
            logger.info(
                "Pricing database is empty, fetching initial pricing data from AWS..."
            )
            stats = await updater.update_all_pricing()
            logger.info(
                f"Initial pricing data loaded: {stats['updated']} models from {stats['source']}"
            )
        else:
            logger.info(f"Pricing database already contains {count} records")
            # Always run cleanup on startup to remove stale cross-region
            # entries that are not in the profile cache (e.g. after a code
            # update that fixes filtering logic).
            await updater.cleanup_stale_cross_region_entries()
            # Back-fill pricing for locally-available models that are
            # missing from the DB (e.g. new models not yet in the region's
            # Price List data).  Collects existing model IDs first.
            try:
                _settings = get_settings()
                existing = await db.execute(
                    select(ModelPricing.model_id).where(
                        ModelPricing.region == _settings.AWS_REGION
                    )
                )
                found_ids = {row[0] for row in existing.fetchall()}
                backfill_count = await updater._backfill_from_reference_region(
                    found_ids
                )
                if backfill_count:
                    logger.info(
                        f"Back-filled {backfill_count} pricing records on startup"
                    )
            except Exception as e:
                logger.warning(f"Startup pricing back-fill failed: {e}")

    # Initialize Gemini pricing (scrapes public pricing page, no API key needed)
    async with async_session_maker() as db:
        try:
            gemini_updater = GeminiPricingUpdater(db)
            gemini_stats = await gemini_updater.update_all_pricing()
            logger.info(
                f"Gemini pricing initialized: {gemini_stats['updated']} models loaded"
            )
        except Exception as e:
            logger.warning(f"Gemini pricing initialization failed (non-fatal): {e}")

    # Start pricing update scheduler
    from app.tasks.pricing_tasks import start_scheduler

    start_scheduler()
    logger.info("Pricing update scheduler started")

    logger.info("Kolya BR Proxy started successfully")

    yield

    # Shutdown
    logger.info("Shutting down Kolya BR Proxy...")

    # Stop pricing update scheduler
    from app.tasks.pricing_tasks import stop_scheduler

    stop_scheduler()
    logger.info("Pricing update scheduler stopped")

    logger.info("Kolya BR Proxy shutdown complete")


def _is_anthropic_request(request: Request) -> bool:
    """Check if request targets Anthropic API endpoints."""
    return request.url.path.rstrip("/").endswith("/messages") and request.headers.get(
        "x-api-key"
    )


async def _disable_cache(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


async def _global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled errors."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)

    if _is_anthropic_request(request):
        return JSONResponse(
            status_code=500,
            content={
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": "Internal server error",
                },
            },
        )

    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "message": "Internal server error",
                "type": "internal_error",
                "code": "internal_error",
            }
        },
    )


async def _validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors with detailed logging."""
    logger.error(f"Validation error: {exc.errors()}")
    logger.error(f"Request body: {exc.body}")

    if _is_anthropic_request(request):
        return JSONResponse(
            status_code=422,
            content={
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": f"Validation error: {exc.errors()}",
                },
            },
        )

    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "message": "Validation error",
                "type": "invalid_request_error",
                "details": exc.errors(),
            }
        },
    )


async def _http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with format-aware error responses."""
    if _is_anthropic_request(request):
        error_type_map = {
            400: "invalid_request_error",
            401: "authentication_error",
            403: "permission_error",
            404: "not_found_error",
            429: "rate_limit_error",
            500: "api_error",
        }
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": "error",
                "error": {
                    "type": error_type_map.get(exc.status_code, "api_error"),
                    "message": exc.detail,
                },
            },
        )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": exc.detail,
                "type": "error",
                "code": str(exc.status_code),
            }
        },
    )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Kolya BR Proxy",
        description="AI Gateway service providing OpenAI and Anthropic compatible access to AWS Bedrock models",
        version="1.0.0",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.get_allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add CSRF protection middleware
    app.add_middleware(
        SecurityMiddleware,
        allowed_origins=settings.get_allowed_origins(),
        require_custom_header=True,
        enforce_referer=False,
    )

    # Register middleware and exception handlers
    app.middleware("http")(_disable_cache)
    app.add_exception_handler(Exception, _global_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(HTTPException, _http_exception_handler)

    # Include routers
    app.include_router(health_router, prefix="/health", tags=["health"])
    app.include_router(gateway_router, prefix="/v1", tags=["ai-gateway"])
    app.include_router(anthropic_router, prefix="/v1", tags=["anthropic-api"])
    app.include_router(gemini_router, prefix="/v1beta", tags=["gemini-api"])
    app.include_router(admin_router, prefix="/admin", tags=["admin"])

    return app


app = create_app()

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
        timeout_keep_alive=settings.UVICORN_TIMEOUT_KEEP_ALIVE,
        limit_concurrency=settings.UVICORN_LIMIT_CONCURRENCY,
        limit_max_requests=settings.UVICORN_LIMIT_MAX_REQUESTS or None,
    )

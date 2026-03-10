"""
FastAPI application entry point for Kolya BR Proxy.
AI Gateway service providing OpenAI-compatible access to AWS Bedrock Claude models.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.database import init_db
from app.api.v1.router import gateway_router
from app.api.admin.router import admin_router
from app.api.health import health_router
from app.middleware.security import SecurityMiddleware
from app.services.bedrock import BedrockClient

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup and shutdown events."""
    # Startup
    logger.info("Starting Kolya BR Proxy...")

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Initialize pricing data if database is empty
    from app.core.database import async_session_maker
    from app.services.pricing_updater import PricingUpdater
    from sqlalchemy import select, func
    from app.models.model_pricing import ModelPricing

    async with async_session_maker() as db:
        result = await db.execute(select(func.count(ModelPricing.id)))
        count = result.scalar()

        if count == 0:
            logger.info(
                "Pricing database is empty, fetching initial pricing data from AWS..."
            )
            updater = PricingUpdater(db)
            stats = await updater.update_all_pricing()
            logger.info(
                f"Initial pricing data loaded: {stats['updated']} models from {stats['source']}"
            )
        else:
            logger.info(f"Pricing database already contains {count} records")

    # Initialize singleton Bedrock client at startup
    BedrockClient.get_instance()
    logger.info("BedrockClient initialized")

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


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Kolya BR Proxy",
        description="AI Gateway service providing OpenAI-compatible access to AWS Bedrock Claude models",
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

    # Add middleware to disable caching
    @app.middleware("http")
    async def disable_cache(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    # Include routers
    app.include_router(health_router, prefix="/health", tags=["health"])
    app.include_router(gateway_router, prefix="/v1", tags=["ai-gateway"])
    app.include_router(admin_router, prefix="/admin", tags=["admin"])

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Global exception handler for unhandled errors."""
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
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

    # Add validation error handler for better debugging
    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        """Handle validation errors with detailed logging."""
        logger.error(f"Validation error: {exc.errors()}")
        logger.error(f"Request body: {exc.body}")
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
        limit_max_requests=settings.UVICORN_LIMIT_MAX_REQUESTS,
    )

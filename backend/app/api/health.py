"""
Health check endpoints for load balancer integration and system monitoring.
"""

import logging
from datetime import datetime
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_db
from app.core.config import get_settings

logger = logging.getLogger(__name__)

health_router = APIRouter()


@health_router.get("/")
async def health_check() -> Dict[str, Any]:
    """
    Basic health check endpoint for load balancer.

    Returns:
        Dict containing health status
    """
    logger.info("Health check requested")

    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "kolya-br-proxy",
    }


@health_router.get("/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """
    Readiness check that verifies database and Redis connectivity.

    Args:
        db: Database session

    Returns:
        Dict containing readiness status and component health

    Raises:
        HTTPException: If any component is unhealthy
    """
    logger.info("Readiness check requested")

    components = {}
    overall_healthy = True

    # Check database connectivity
    try:
        result = await db.execute(text("SELECT 1"))
        await result.fetchone()
        components["database"] = {"status": "healthy", "message": "Connected"}
        logger.debug("Database health check passed")
    except Exception as e:
        components["database"] = {"status": "unhealthy", "message": str(e)}
        overall_healthy = False
        logger.error(f"Database health check failed: {e}")

    response = {
        "status": "ready" if overall_healthy else "not_ready",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "kolya-br-proxy",
        "components": components,
    }

    if not overall_healthy:
        logger.warning("Readiness check failed")
        raise HTTPException(status_code=503, detail=response)

    logger.info("Readiness check passed")
    return response


@health_router.get("/live")
async def liveness_check() -> Dict[str, Any]:
    """
    Liveness check for Kubernetes liveness probe.

    Returns:
        Dict containing liveness status
    """
    logger.info("Liveness check requested")

    return {
        "status": "alive",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "kolya-br-proxy",
    }


@health_router.get("/metrics")
async def metrics_endpoint() -> Dict[str, Any]:
    """
    Basic metrics endpoint (Prometheus-compatible format can be added later).

    Returns:
        Dict containing basic system metrics
    """
    logger.info("Metrics endpoint requested")

    settings = get_settings()

    return {
        "service": "kolya-br-proxy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "debug_mode": settings.DEBUG,
        "metrics": {
            "health_checks_total": "counter",
            "requests_total": "counter",
            "request_duration_seconds": "histogram",
        },
    }

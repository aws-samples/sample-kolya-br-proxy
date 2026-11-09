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

logger = logging.getLogger(__name__)

health_router = APIRouter()


@health_router.get("/")
async def health_check() -> Dict[str, Any]:
    """
    Basic health check endpoint for load balancer.

    Returns:
        Dict containing health status
    """
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
        # AsyncSession.execute returns a buffered Result; fetchone() is sync.
        result.fetchone()
        components["database"] = {"status": "healthy", "message": "Connected"}
        logger.debug("Database health check passed")
    except Exception as e:
        # Don't leak the raw exception (connection strings, internals) to the
        # client — log it server-side and return a generic message.
        components["database"] = {
            "status": "unhealthy",
            "message": "Connection failed",
        }
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
    return {
        "status": "alive",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "kolya-br-proxy",
    }


@health_router.get("/metrics")
async def metrics_endpoint() -> Dict[str, Any]:
    """Minimal status for the metrics probe.

    Runtime observability settings (log level, exporter) used to be listed
    here, but this endpoint is unauthenticated. Super-admins can read them
    from the admin settings API instead.
    """
    return {
        "service": "kolya-br-proxy",
        "timestamp": datetime.utcnow().isoformat(),
    }

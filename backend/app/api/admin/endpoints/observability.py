"""
Admin endpoints for runtime observability configuration.

Allows hot-toggling log level and metrics without restarting the service.
Tracing (OTEL_EXPORTER) cannot be changed at runtime — TracerProvider
is initialized once at startup.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import get_current_user_from_jwt
from app.core.config import get_settings
from app.core.metrics import is_metrics_enabled, set_metrics_enabled
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


class ObservabilityUpdate(BaseModel):
    """Request body for updating observability settings."""

    log_level: Optional[str] = Field(
        default=None,
        description="Log level: DEBUG, INFO, WARNING, ERROR",
    )
    enable_metrics: Optional[bool] = Field(
        default=None,
        description="Enable/disable CloudWatch EMF metrics",
    )


@router.get("")
async def get_observability_config(
    current_user: User = Depends(get_current_user_from_jwt),
):
    """Get current observability configuration."""
    settings = get_settings()
    root_logger = logging.getLogger()

    return {
        "log_level": logging.getLevelName(root_logger.level),
        "log_format": settings.LOG_FORMAT,
        "metrics_enabled": is_metrics_enabled(),
        "tracing_exporter": settings.OTEL_EXPORTER or "disabled",
        "note": "log_format and tracing_exporter require restart to change",
    }


@router.put("")
async def update_observability_config(
    update: ObservabilityUpdate,
    current_user: User = Depends(get_current_user_from_jwt),
):
    """Update observability settings at runtime (no restart required).

    Supports:
    - **log_level**: Changes root logger level immediately
    - **enable_metrics**: Toggles CloudWatch EMF metric emission

    Does NOT support (requires restart):
    - log_format (text/json)
    - tracing exporter (xray/otlp)
    """
    changes = {}
    root_logger = logging.getLogger()

    if update.log_level is not None:
        level_upper = update.log_level.upper()
        if level_upper not in _VALID_LOG_LEVELS:
            return {
                "success": False,
                "error": f"Invalid log_level: {update.log_level}. Must be one of {_VALID_LOG_LEVELS}",
            }
        old_level = logging.getLevelName(root_logger.level)
        numeric_level = getattr(logging, level_upper)
        root_logger.setLevel(numeric_level)
        for handler in root_logger.handlers:
            handler.setLevel(numeric_level)
        changes["log_level"] = {"old": old_level, "new": level_upper}
        logger.info("Log level changed: %s -> %s", old_level, level_upper)

    if update.enable_metrics is not None:
        old_val = is_metrics_enabled()
        set_metrics_enabled(update.enable_metrics)
        changes["metrics_enabled"] = {"old": old_val, "new": update.enable_metrics}
        logger.info("Metrics toggled: %s -> %s", old_val, update.enable_metrics)

    if not changes:
        return {"success": True, "message": "No changes requested", "changes": {}}

    return {"success": True, "changes": changes}

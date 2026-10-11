"""
Admin endpoints for runtime observability configuration.

Allows hot-toggling log level and metrics without restarting the service.
Tracing (OTEL_EXPORTER) cannot be changed at runtime — TracerProvider
is initialized once at startup.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_superadmin
from app.core.config import get_settings
from app.core.config_sync import publish_config_change
from app.core.database import get_db
from app.core.json_formatter import set_log_level
from app.core.metrics import is_metrics_enabled, set_metrics_enabled
from app.core.redis import get_redis
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


class ObservabilityUpdate(BaseModel):
    """Request body for updating runtime configuration."""

    log_level: Optional[str] = Field(
        default=None,
        description="Log level: DEBUG, INFO, WARNING, ERROR",
    )
    enable_metrics: Optional[bool] = Field(
        default=None,
        description="Enable/disable CloudWatch EMF metrics",
    )
    openai_gpt_backend: Optional[str] = Field(
        default=None,
        description="Removed. GPT routing is automatic per exact model ID; "
        "sending this field returns an error instead of being silently ignored.",
    )


@router.get("")
async def get_observability_config(
    current_user: User = Depends(get_current_superadmin),
):
    """Get current runtime configuration."""
    settings = get_settings()
    root_logger = logging.getLogger()

    return {
        "log_level": logging.getLevelName(root_logger.level),
        "log_format": settings.LOG_FORMAT,
        "metrics_enabled": is_metrics_enabled(),
        "tracing_exporter": settings.OTEL_EXPORTER or "disabled",
        # GPT routing is automatic: canonical openai.* IDs → Mantle Responses,
        # us./global. profiles → Runtime Responses. No global switch.
        "openai_gpt_routing": "auto",
        "note": "log_format and tracing_exporter require restart to change",
    }


@router.put("")
async def update_observability_config(
    update: ObservabilityUpdate,
    current_user: User = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Update runtime configuration (no restart required).

    Supports:
    - **log_level**: Changes root logger level immediately
    - **enable_metrics**: Toggles CloudWatch EMF metric emission

    Does NOT support (requires restart):
    - log_format (text/json)
    - tracing exporter (xray/otlp)
    """
    if update.openai_gpt_backend is not None:
        # 400 (not 200 + success=False) so a stale client cannot mistake the
        # dropped update for success.
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": "openai_gpt_backend was removed: GPT routing is automatic "
                "(canonical IDs use Mantle Responses, us./global. profiles use "
                "Runtime Responses).",
            },
        )

    changes = {}

    if update.log_level is not None:
        level_upper = update.log_level.upper()
        if level_upper not in _VALID_LOG_LEVELS:
            return {
                "success": False,
                "error": f"Invalid log_level: {update.log_level}. Must be one of {_VALID_LOG_LEVELS}",
            }
        old_level = logging.getLevelName(logging.getLogger().level)
        set_log_level(level_upper)
        changes["log_level"] = {"old": old_level, "new": level_upper}
        logger.info("Log level changed: %s -> %s", old_level, level_upper)

    if update.enable_metrics is not None:
        old_val = is_metrics_enabled()
        set_metrics_enabled(update.enable_metrics)
        changes["metrics_enabled"] = {"old": old_val, "new": update.enable_metrics}
        logger.info("Metrics toggled: %s -> %s", old_val, update.enable_metrics)

    if not changes:
        return {"success": True, "message": "No changes requested", "changes": {}}

    redis_client = await get_redis()
    if redis_client:
        broadcast = {}
        if "log_level" in changes:
            broadcast["log_level"] = changes["log_level"]["new"]
        if "metrics_enabled" in changes:
            broadcast["metrics_enabled"] = changes["metrics_enabled"]["new"]
        await publish_config_change(redis_client, broadcast)

    return {"success": True, "changes": changes}

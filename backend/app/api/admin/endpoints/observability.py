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
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_superadmin
from app.core.config import get_settings
from app.core.config_sync import publish_config_change
from app.core.database import get_db
from app.core.json_formatter import set_log_level
from app.core.metrics import is_metrics_enabled, set_metrics_enabled
from app.core.redis import get_redis
from app.core.runtime_config import (
    get_openai_gpt_backend,
    persist_openai_gpt_backend,
    set_openai_gpt_backend,
)
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
_VALID_GPT_BACKENDS = {"mantle", "runtime"}


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
        description="OpenAI GPT (openai.gpt-5.x) upstream: 'mantle' or 'runtime'",
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
        "openai_gpt_backend": get_openai_gpt_backend(),
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
    - **openai_gpt_backend**: Switch GPT upstream (mantle | runtime); persisted
      to system_configs so it survives restarts

    Does NOT support (requires restart):
    - log_format (text/json)
    - tracing exporter (xray/otlp)
    """
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

    if update.openai_gpt_backend is not None:
        candidate = update.openai_gpt_backend.lower()
        if candidate not in _VALID_GPT_BACKENDS:
            return {
                "success": False,
                "error": f"Invalid openai_gpt_backend: {update.openai_gpt_backend}. "
                f"Must be one of {_VALID_GPT_BACKENDS}",
            }
        old_backend = get_openai_gpt_backend()
        set_openai_gpt_backend(candidate)
        await persist_openai_gpt_backend(db, candidate)
        changes["openai_gpt_backend"] = {"old": old_backend, "new": candidate}
        logger.info("OpenAI GPT backend changed: %s -> %s", old_backend, candidate)

    if not changes:
        return {"success": True, "message": "No changes requested", "changes": {}}

    redis_client = await get_redis()
    if redis_client:
        broadcast = {}
        if "log_level" in changes:
            broadcast["log_level"] = changes["log_level"]["new"]
        if "metrics_enabled" in changes:
            broadcast["metrics_enabled"] = changes["metrics_enabled"]["new"]
        if "openai_gpt_backend" in changes:
            broadcast["openai_gpt_backend"] = changes["openai_gpt_backend"]["new"]
        await publish_config_change(redis_client, broadcast)

    return {"success": True, "changes": changes}

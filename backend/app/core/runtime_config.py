"""Runtime-mutable configuration that overrides env defaults without a restart.

Some Settings are operational switches an admin needs to flip live from the UI
and have persist across restarts. Those live here as process-local state:

* seeded from the persisted ``system_configs`` table at startup, falling back to
  the env default (``Settings.OPENAI_GPT_BACKEND``) when no row exists;
* read on every request via the getter (so ``get_settings()``'s lru_cache does
  not pin a stale value);
* kept in sync across pods by ``config_sync`` (Redis pub/sub).
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)

# system_configs.key under which the GPT backend override is persisted.
OPENAI_GPT_BACKEND_KEY = "openai_gpt_backend"
_VALID_GPT_BACKENDS = ("mantle", "runtime")

# None until an override is set; the getter falls back to the env default.
_openai_gpt_backend: str | None = None


def get_openai_gpt_backend() -> str:
    """Return the effective OpenAI GPT upstream ('mantle' or 'runtime')."""
    if _openai_gpt_backend is not None:
        return _openai_gpt_backend
    return get_settings().OPENAI_GPT_BACKEND


def set_openai_gpt_backend(value: str) -> str:
    """Set the in-memory override. Returns the normalized value.

    Raises ValueError for anything other than 'mantle' / 'runtime'.
    """
    global _openai_gpt_backend
    lowered = (value or "").lower()
    if lowered not in _VALID_GPT_BACKENDS:
        raise ValueError(
            f"openai_gpt_backend must be one of {_VALID_GPT_BACKENDS}, got {value!r}"
        )
    _openai_gpt_backend = lowered
    return lowered


async def load_persisted_config(db: AsyncSession) -> None:
    """Seed in-memory runtime config from the system_configs table (startup)."""
    try:
        row = await db.execute(
            select(SystemConfig.value).where(SystemConfig.key == OPENAI_GPT_BACKEND_KEY)
        )
        value = row.scalar_one_or_none()
        if value:
            set_openai_gpt_backend(value)
            logger.info("Loaded persisted openai_gpt_backend=%s", value)
    except ValueError:
        logger.warning("Ignoring invalid persisted openai_gpt_backend=%r", value)
    except Exception as e:  # non-fatal: fall back to env default
        logger.warning("Failed to load persisted runtime config: %s", e)


async def persist_openai_gpt_backend(db: AsyncSession, value: str) -> None:
    """Upsert the GPT backend override into system_configs."""
    row = await db.execute(
        select(SystemConfig).where(SystemConfig.key == OPENAI_GPT_BACKEND_KEY)
    )
    config = row.scalar_one_or_none()
    if config is None:
        config = SystemConfig(
            key=OPENAI_GPT_BACKEND_KEY,
            value=value,
            description="OpenAI GPT (openai.gpt-5.x) upstream: mantle | runtime",
            is_public=False,
        )
        db.add(config)
    else:
        config.value = value
    await db.commit()

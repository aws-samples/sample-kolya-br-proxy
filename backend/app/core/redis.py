"""
Redis client for distributed rate limiting and caching.

Provides async Redis connection management with graceful degradation
when Redis is unavailable.
"""

import json
import logging
from typing import Any, Optional

import redis.asyncio as aioredis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_redis_client: Optional[aioredis.Redis] = None


async def get_redis() -> Optional[aioredis.Redis]:
    """Get the singleton async Redis client.

    Returns None if Redis is not configured or connection fails.
    """
    global _redis_client

    if _redis_client is not None:
        return _redis_client

    settings = get_settings()
    if not settings.REDIS_URL:
        return None

    try:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=False,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=True,
        )
        await _redis_client.ping()
        logger.info(f"Redis connected: {settings.REDIS_URL}")
        return _redis_client
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
        _redis_client = None
        return None


async def close_redis() -> None:
    """Close the Redis connection."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
        logger.info("Redis connection closed")


class RedisCache:
    """Thin wrapper over an async Redis client with JSON serialization."""

    def __init__(self, client: Optional[aioredis.Redis]):
        self._client = client

    async def get(self, key: str) -> Optional[Any]:
        if self._client is None:
            return None
        raw = await self._client.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set(self, key: str, value: Any, expire: int = 300) -> None:
        if self._client is None:
            return
        await self._client.set(key, json.dumps(value), ex=expire)

    async def delete(self, key: str) -> None:
        if self._client is None:
            return
        await self._client.delete(key)

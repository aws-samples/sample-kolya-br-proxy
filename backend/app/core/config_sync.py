"""
Cross-pod runtime config synchronization via Redis Pub/Sub.

When an admin changes log_level or metrics_enabled through the API,
the change is published to a Redis channel. All pods subscribe to
this channel and apply the change locally, so every pod stays in sync.
"""

import asyncio
import json
import logging
from typing import Optional

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

CHANNEL = "kbp:config_sync"

# Backoff while waiting for Redis to become reachable (e.g. the Redis pod is
# being rescheduled while this pod starts).
_RETRY_INITIAL_SECONDS = 2.0
_RETRY_MAX_SECONDS = 30.0

_subscriber_task: Optional[asyncio.Task] = None


def _apply_config(payload: dict) -> None:
    """Apply a config change locally."""
    if "log_level" in payload:
        from app.core.json_formatter import set_log_level

        level_name = payload["log_level"]
        if set_log_level(level_name):
            numeric = getattr(logging, level_name.upper(), logging.INFO)
            logger.log(
                max(numeric, logging.INFO),
                "Log level synced from peer: %s",
                level_name,
            )

    if "metrics_enabled" in payload:
        value = payload["metrics_enabled"]
        if isinstance(value, bool):
            from app.core.metrics import set_metrics_enabled

            set_metrics_enabled(value)
            logger.info("Metrics toggle synced from peer: %s", value)


async def publish_config_change(client: aioredis.Redis, changes: dict) -> None:
    """Publish a config change so all pods pick it up."""
    try:
        await client.publish(CHANNEL, json.dumps(changes))
    except Exception as e:
        logger.warning("Failed to publish config change: %s", e)


async def _wait_for_client() -> aioredis.Redis:
    """Retry get_redis() with capped exponential backoff until it succeeds."""
    delay = _RETRY_INITIAL_SECONDS
    while True:
        client = await get_redis()
        if client is not None:
            logger.info("Redis became available, starting config sync")
            return client
        logger.warning("Redis not available for config sync, retrying in %.0fs", delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, _RETRY_MAX_SECONDS)


async def _listen(client: Optional[aioredis.Redis]) -> None:
    """Background loop that listens for config changes."""
    if client is None:
        client = await _wait_for_client()
    while True:
        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(CHANNEL)
            logger.info("Subscribed to config sync channel")

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    payload = json.loads(message["data"])
                    _apply_config(payload)
                except Exception as e:
                    logger.warning("Bad config sync message: %s", e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "Config sync listener lost connection: %s, reconnecting...", e
            )
            await asyncio.sleep(2)
        finally:
            try:
                await pubsub.close()
            except Exception:
                pass


async def start_subscriber(client: Optional[aioredis.Redis]) -> None:
    """Start the background subscriber task (call from lifespan startup).

    If Redis is configured but unreachable right now, the task keeps retrying
    in the background instead of disabling sync for the life of the pod.
    """
    global _subscriber_task
    if _subscriber_task is not None:
        return
    if client is None and not get_settings().REDIS_URL:
        logger.info("Redis not configured, config sync disabled")
        return
    _subscriber_task = asyncio.create_task(_listen(client), name="config_sync")


async def stop_subscriber() -> None:
    """Cancel the background subscriber (call from lifespan shutdown)."""
    global _subscriber_task
    if _subscriber_task is not None:
        _subscriber_task.cancel()
        try:
            await _subscriber_task
        except asyncio.CancelledError:
            pass
        _subscriber_task = None

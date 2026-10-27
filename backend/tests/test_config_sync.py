"""Config sync must recover when Redis is unavailable at pod startup.

Regression: a pod that started while Redis was being rescheduled (node
rotation, EKS upgrade) logged "config sync disabled" and never subscribed,
so it silently ignored peer config changes until restarted.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core import config_sync


@pytest.fixture(autouse=True)
async def _reset_subscriber():
    yield
    await config_sync.stop_subscriber()


def _fake_client():
    """A Redis client whose pubsub subscribes and then idles forever."""
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.close = AsyncMock()

    async def _listen():
        await asyncio.Event().wait()
        yield  # pragma: no cover

    pubsub.listen = _listen
    client = MagicMock()
    client.pubsub.return_value = pubsub
    return client, pubsub


def _settings(redis_url):
    return SimpleNamespace(REDIS_URL=redis_url)


@pytest.mark.asyncio
async def test_subscribes_once_redis_becomes_available():
    client, pubsub = _fake_client()
    get_redis = AsyncMock(side_effect=[None, None, client])

    with (
        patch.object(config_sync, "get_settings", return_value=_settings("redis://x")),
        patch.object(config_sync, "get_redis", get_redis),
        patch.object(config_sync, "_RETRY_INITIAL_SECONDS", 0.01),
    ):
        await config_sync.start_subscriber(None)
        for _ in range(100):
            if pubsub.subscribe.await_count:
                break
            await asyncio.sleep(0.01)

    assert get_redis.await_count == 3
    pubsub.subscribe.assert_awaited_once_with(config_sync.CHANNEL)


@pytest.mark.asyncio
async def test_disabled_when_redis_not_configured():
    get_redis = AsyncMock()

    with (
        patch.object(config_sync, "get_settings", return_value=_settings("")),
        patch.object(config_sync, "get_redis", get_redis),
    ):
        await config_sync.start_subscriber(None)

    assert config_sync._subscriber_task is None
    get_redis.assert_not_awaited()


@pytest.mark.asyncio
async def test_uses_client_available_at_startup():
    client, pubsub = _fake_client()
    get_redis = AsyncMock()

    with (
        patch.object(config_sync, "get_settings", return_value=_settings("redis://x")),
        patch.object(config_sync, "get_redis", get_redis),
    ):
        await config_sync.start_subscriber(client)
        for _ in range(100):
            if pubsub.subscribe.await_count:
                break
            await asyncio.sleep(0.01)

    pubsub.subscribe.assert_awaited_once_with(config_sync.CHANNEL)
    get_redis.assert_not_awaited()

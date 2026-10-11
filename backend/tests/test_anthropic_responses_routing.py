"""Anthropic-compatible requests must preserve Runtime Responses profiles."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.anthropic.endpoints import messages as messages_module
from app.schemas.anthropic import AnthropicMessagesRequest


def _db_with_models(names):
    db = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [
        SimpleNamespace(model_name=name) for name in names
    ]
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model",
    [
        "openai.gpt-5.6-sol",
        "us.openai.gpt-5.6-sol",
        "global.openai.gpt-5.6-sol",
        "openai.gpt-6-sol",
        "global.openai.gpt-6-luna",
        "us.openai.gpt-6.1-sol",
        "global.openai.gpt-6.1-sol",
    ],
)
async def test_gpt_messages_always_route_via_responses(model):
    request = AnthropicMessagesRequest.model_validate(
        {
            "model": model,
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hello"}],
        }
    )
    token = SimpleNamespace(id="tok", user_id="usr", token_metadata=None)
    db = _db_with_models([model])

    @asynccontextmanager
    async def fake_scope():
        yield db

    with (
        patch("app.services.quota.enforce_quota", new=AsyncMock()),
        patch.object(messages_module, "session_scope", fake_scope),
        patch.object(
            messages_module,
            "_handle_mantle_via_anthropic",
            new=AsyncMock(return_value="responses"),
        ) as handler,
    ):
        result = await messages_module.create_message(request, MagicMock(), token=token)

    assert result == "responses"
    handler.assert_awaited_once()
    assert handler.await_args.kwargs["request_data"].model == model

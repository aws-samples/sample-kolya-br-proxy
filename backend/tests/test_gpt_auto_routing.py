"""GPT models are routed automatically from the exact model ID.

The legacy global Mantle/Runtime switch is gone: canonical IDs always use
Mantle Responses, US/Global profiles always use Runtime Responses, and no GPT
request falls through to boto3 Converse (which drops explicit cache markers).
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import chat as chat_module
from app.schemas.openai import ChatCompletionRequest, ChatMessage


def _request(model):
    return ChatCompletionRequest(
        model=model, messages=[ChatMessage(role="user", content="hi")]
    )


def _http_request():
    req = MagicMock()
    req.headers = {}
    return req


def _db_with_models(names):
    db = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [
        SimpleNamespace(model_name=n) for n in names
    ]
    db.execute = AsyncMock(return_value=result)
    return db


async def _call(request, allowed_names):
    token = SimpleNamespace(id="tok", user_id="usr", token_metadata=None)
    db = _db_with_models(allowed_names)

    @asynccontextmanager
    async def fake_scope():
        yield db

    bedrock_client = MagicMock()
    bedrock_client.invoke = AsyncMock()
    with (
        patch("app.services.quota.enforce_quota", new=AsyncMock()),
        patch.object(chat_module, "session_scope", fake_scope),
        patch.object(
            chat_module,
            "get_settings",
            return_value=SimpleNamespace(PROMPT_CACHE_TTL="5m"),
        ),
        patch.object(
            chat_module,
            "_handle_mantle_request",
            new=AsyncMock(return_value="responses"),
        ) as responses_handler,
        patch.object(
            chat_module.BedrockClient, "get_instance", return_value=bedrock_client
        ),
    ):
        result = await chat_module.create_chat_completion(
            request, _http_request(), token=token
        )
    return result, responses_handler, bedrock_client


def test_legacy_backend_switch_is_removed():
    assert not hasattr(chat_module, "get_openai_gpt_backend")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model",
    [
        "openai.gpt-5.6-sol",
        "us.openai.gpt-5.6-sol",
        "global.openai.gpt-5.6-sol",
        "openai.gpt-6-sol",
        "us.openai.gpt-6-sol",
        "global.openai.gpt-6-sol",
        "global.openai.gpt-6-luna",
        "us.openai.gpt-6-astra",
        "openai.gpt-6.1-sol",
        "us.openai.gpt-6.1-sol",
        "global.openai.gpt-6.1-sol",
        "openai.gpt-5.4",
    ],
)
async def test_gpt_models_always_use_responses_with_exact_id(model):
    result, responses_handler, bedrock_client = await _call(
        _request(model), allowed_names=[model]
    )

    assert result == "responses"
    responses_handler.assert_awaited_once()
    assert responses_handler.await_args.kwargs["request_data"].model == model
    bedrock_client.invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_global_profile_is_not_authorized_by_us_profile_grant():
    with pytest.raises(HTTPException) as caught:
        await _call(
            _request("global.openai.gpt-6.1-sol"),
            allowed_names=["us.openai.gpt-6.1-sol"],
        )

    assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_unsupported_cache_marker_returns_clear_400():
    request = ChatCompletionRequest.model_validate(
        {
            "model": "openai.gpt-5.4",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "prefix",
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            ],
        }
    )
    token = SimpleNamespace(id="tok", user_id="usr", token_metadata=None)
    db = _db_with_models(["openai.gpt-5.4"])

    @asynccontextmanager
    async def fake_scope():
        yield db

    with (
        patch("app.services.quota.enforce_quota", new=AsyncMock()),
        patch.object(chat_module, "session_scope", fake_scope),
        pytest.raises(HTTPException) as caught,
    ):
        await chat_module.create_chat_completion(request, _http_request(), token=token)

    assert caught.value.status_code == 400
    assert "does not support explicit prompt caching" in caught.value.detail

"""Routing tests for the OPENAI_GPT_BACKEND switch.

GPT models default to the Mantle Responses API. GPT-5.6 Sol always remains on
Responses so explicit cache controls cannot be silently stripped by Converse;
the legacy switch still applies to other canonical GPT model IDs.
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


async def _call(request, allowed_names, backend):
    token = SimpleNamespace(id="tok", user_id="usr", token_metadata=None)
    db = _db_with_models(allowed_names)

    @asynccontextmanager
    async def fake_scope():
        yield db

    settings_ns = SimpleNamespace(PROMPT_CACHE_TTL="5m")
    bedrock_client = MagicMock()
    bedrock_response = SimpleNamespace(
        usage=SimpleNamespace(cache_creation_input_tokens=0, cache_read_input_tokens=0)
    )
    bedrock_client.invoke = AsyncMock(return_value=bedrock_response)
    openai_response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1)
    )
    with (
        patch("app.services.quota.enforce_quota", new=AsyncMock()),
        patch.object(chat_module, "session_scope", fake_scope),
        patch.object(chat_module, "get_settings", return_value=settings_ns),
        patch.object(chat_module, "get_openai_gpt_backend", return_value=backend),
        patch.object(
            chat_module, "_handle_mantle_request", new=AsyncMock(return_value="mantle")
        ) as mantle,
        patch.object(
            chat_module.BedrockClient, "get_instance", return_value=bedrock_client
        ),
        patch.object(
            chat_module.RequestTranslator,
            "openai_to_bedrock",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch.object(
            chat_module.ResponseTranslator,
            "bedrock_to_openai",
            return_value=openai_response,
        ),
        patch.object(chat_module.background_tasks, "create_task"),
        patch.object(chat_module, "record_usage", new=MagicMock()),
    ):
        result = await chat_module.create_chat_completion(
            request, _http_request(), token=token
        )
    return result, mantle, bedrock_client


@pytest.mark.asyncio
async def test_mantle_backend_routes_gpt_to_mantle():
    request = _request("openai.gpt-5.6-sol")
    result, mantle, bedrock_client = await _call(
        request, allowed_names=["openai.gpt-5.6-sol"], backend="mantle"
    )

    assert result == "mantle"
    mantle.assert_awaited_once()
    bedrock_client.invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_backend_does_not_bypass_responses_for_gpt56_sol():
    request = _request("openai.gpt-5.6-sol")
    result, mantle, bedrock_client = await _call(
        request, allowed_names=["openai.gpt-5.6-sol"], backend="runtime"
    )

    assert result == "mantle"
    mantle.assert_awaited_once()
    bedrock_client.invoke.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model",
    ["us.openai.gpt-5.6-sol", "global.openai.gpt-5.6-sol"],
)
@pytest.mark.parametrize("backend", ["mantle", "runtime"])
async def test_inference_profiles_always_use_runtime_responses(model, backend):
    request = _request(model)
    result, responses_handler, bedrock_client = await _call(
        request, allowed_names=[model], backend=backend
    )

    assert result == "mantle"
    responses_handler.assert_awaited_once()
    forwarded_request = responses_handler.await_args.kwargs["request_data"]
    assert forwarded_request.model == model
    bedrock_client.invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_global_profile_is_not_authorized_by_us_profile_grant():
    request = _request("global.openai.gpt-5.6-sol")

    with pytest.raises(HTTPException) as caught:
        await _call(
            request,
            allowed_names=["us.openai.gpt-5.6-sol"],
            backend="mantle",
        )

    assert caught.value.status_code == 403

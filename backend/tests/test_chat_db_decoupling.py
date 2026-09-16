"""Regression tests for decoupling the DB connection from Bedrock streaming.

Under load the 100-concurrency HTTP 500s were pool exhaustion: the chat endpoint
held its pooled DB connection for the whole request — including the tens of
seconds a Bedrock stream runs — so ~50 concurrent streams/pod starved a pool of
30. The fix does the quota + model-access reads in a short-lived ``session_scope``
that is released before streaming, and validates the token in a short session too
(``get_current_token_streaming``), so a long stream holds zero DB connections.

These tests pin that behaviour:
- the early-read session is closed before Bedrock streaming starts;
- ``get_current_token_streaming`` releases its session before returning.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api import deps as deps_module
from app.api.v1.endpoints import chat as chat_module
from app.api.v1.endpoints import responses as responses_module
from app.schemas.openai import ChatCompletionRequest, ChatMessage


def _http_request():
    req = MagicMock()
    req.headers = {}
    req.is_disconnected = AsyncMock(return_value=False)
    return req


def _db_with_models(names):
    db = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [
        SimpleNamespace(model_name=n) for n in names
    ]
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_db_session_released_before_streaming():
    """The early-read session must be back in the pool before Bedrock streams."""
    model = "global.anthropic.claude-opus-4-8"
    request = ChatCompletionRequest(
        model=model, messages=[ChatMessage(role="user", content="hi")], stream=True
    )
    token = SimpleNamespace(id="tok", user_id="usr", token_metadata=None)
    db = _db_with_models([model])

    state = {"scope_open": False, "open_when_stream_started": None}

    @asynccontextmanager
    async def fake_scope():
        state["scope_open"] = True
        try:
            yield db
        finally:
            state["scope_open"] = False

    async def fake_stream(*args, **kwargs):
        # Runs on the first __anext__, i.e. once the endpoint is already
        # streaming. The early-read scope must be closed by now.
        state["open_when_stream_started"] = state["scope_open"]
        return
        yield  # pragma: no cover - makes this an async generator

    bedrock_client = MagicMock()
    bedrock_client.invoke_stream = fake_stream

    with (
        patch("app.services.quota.enforce_quota", new=AsyncMock()),
        patch.object(chat_module, "session_scope", fake_scope),
        patch.object(chat_module, "_is_gemini_model", return_value=False),
        patch.object(chat_module, "is_openai_mantle_model", return_value=False),
        patch.object(
            chat_module.BedrockClient, "get_instance", return_value=bedrock_client
        ),
        patch.object(chat_module, "get_fallback_models", return_value=[]),
        patch.object(chat_module, "emit_request_metrics", new=AsyncMock()),
        patch.object(chat_module.background_tasks, "create_task", new=MagicMock()),
    ):
        response = await chat_module.create_chat_completion(
            request, _http_request(), token=token
        )
        async for _ in response.body_iterator:
            pass

    assert state["open_when_stream_started"] is False, (
        "DB connection must be released before Bedrock streaming starts"
    )


@pytest.mark.asyncio
async def test_responses_session_released_before_streaming():
    """The /v1/responses early-read session must close before mantle streams."""
    model = "openai.gpt-6-astra"
    token = SimpleNamespace(id="tok", user_id="usr", token_metadata=None)
    db = _db_with_models([model])
    http_request = MagicMock()
    http_request.json = AsyncMock(return_value={"model": model, "stream": True})

    state = {"scope_open": False, "open_when_stream_started": None}

    @asynccontextmanager
    async def fake_scope():
        state["scope_open"] = True
        try:
            yield db
        finally:
            state["scope_open"] = False

    async def fake_passthrough_stream(_body):
        state["open_when_stream_started"] = state["scope_open"]
        return
        yield  # pragma: no cover - makes this an async generator

    with (
        patch("app.services.quota.enforce_quota", new=AsyncMock()),
        patch.object(responses_module, "session_scope", fake_scope),
        patch.object(responses_module, "resolve_mantle_model_id", return_value=model),
        patch.object(responses_module, "match_allowed_model", return_value=model),
        patch.object(
            responses_module.MantleClient,
            "responses_passthrough_stream",
            new=fake_passthrough_stream,
        ),
        patch.object(responses_module.background_tasks, "create_task", new=MagicMock()),
    ):
        response = await responses_module.create_response(http_request, token=token)
        async for _ in response.body_iterator:
            pass

    assert state["open_when_stream_started"] is False, (
        "DB connection must be released before the Responses stream starts"
    )


@pytest.mark.asyncio
async def test_flexible_streaming_auth_releases_session():
    """get_current_token_flexible_streaming validates in a short session (x-api-key)."""
    session = MagicMock()
    session.close = AsyncMock()
    session.rollback = AsyncMock()
    token = SimpleNamespace(id="tok", name="t", user_id="usr")

    @asynccontextmanager
    async def fake_scope():
        try:
            yield session
        finally:
            await session.close()

    request = MagicMock()
    request.headers = {"x-api-key": "sk-test"}

    with (
        patch.object(deps_module, "session_scope", fake_scope),
        patch.object(
            deps_module, "_validate_token_with_cache", AsyncMock(return_value=token)
        ),
        patch.object(deps_module, "set_log_context", MagicMock()),
    ):
        result = await deps_module.get_current_token_flexible_streaming(request=request)

    assert result is token
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_streaming_auth_dependency_releases_session():
    """get_current_token_streaming must not hold its session past validation."""
    released = {"closed_before_return": None}

    session = MagicMock()
    session.close = AsyncMock()
    session.rollback = AsyncMock()

    token = SimpleNamespace(id="tok", name="t", user_id="usr")

    @asynccontextmanager
    async def fake_scope():
        try:
            yield session
        finally:
            await session.close()

    async def fake_validate(_service, _plain):
        # At validation time the session is still open (not yet closed).
        released["closed_before_return"] = session.close.await_count
        return token

    creds = SimpleNamespace(credentials="sk-test")

    with (
        patch.object(deps_module, "session_scope", fake_scope),
        patch.object(deps_module, "_validate_token_with_cache", fake_validate),
        patch.object(deps_module, "set_log_context", MagicMock()),
    ):
        result = await deps_module.get_current_token_streaming(credentials=creds)

    assert result is token
    # close() had not run yet during validation, but must have run by return.
    assert released["closed_before_return"] == 0
    session.close.assert_awaited_once()

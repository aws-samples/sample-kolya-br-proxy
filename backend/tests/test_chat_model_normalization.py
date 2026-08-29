"""Regression tests for mantle model-name normalization in the chat endpoint.

The OpenAI-compatible ``/v1/chat/completions`` path stores mantle models under
their canonical ``openai.``-prefixed ID but clients commonly send the bare form
(``gpt-5.6-luna``). Before the fix the access check was an exact match, so a
bare name never matched the stored canonical name and returned 403. These tests
pin that a bare mantle name is rewritten to canonical, passes the access check,
and routes to the mantle Responses handler — while a genuinely unknown model
still gets 403.
"""

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
    token = SimpleNamespace(id="tok", token_metadata=None)
    db = _db_with_models(allowed_names)
    with (
        patch("app.services.quota.enforce_quota", new=AsyncMock()),
        patch.object(
            chat_module, "_handle_mantle_request", new=AsyncMock(return_value="mantle")
        ) as mantle,
    ):
        result = await chat_module.create_chat_completion(
            request, _http_request(), token=token, db=db
        )
    return result, mantle


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("bare", "canonical"),
    [
        ("gpt-5.6-sol", "openai.gpt-5.6-sol"),
        ("gpt-5.6-terra", "openai.gpt-5.6-terra"),
        ("gpt-5.6-luna", "openai.gpt-5.6-luna"),
        ("gpt-5.5", "openai.gpt-5.5"),
        ("gpt-5.4", "openai.gpt-5.4"),
    ],
)
async def test_bare_mantle_name_normalized_and_routed(bare, canonical):
    request = _request(bare)
    result, mantle = await _call(request, allowed_names=[canonical])

    # Rewritten to canonical, passed the access check, routed to mantle.
    assert request.model == canonical
    assert result == "mantle"
    mantle.assert_awaited_once()


@pytest.mark.asyncio
async def test_canonical_name_still_works():
    request = _request("openai.gpt-5.6-luna")
    result, mantle = await _call(request, allowed_names=["openai.gpt-5.6-luna"])

    assert request.model == "openai.gpt-5.6-luna"
    assert result == "mantle"
    mantle.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_model_still_403():
    # ``gpt-4o`` is not a mantle model, so it is not normalized and does not
    # match the token's allowed (canonical) list — must still be rejected.
    request = _request("gpt-4o")
    with pytest.raises(HTTPException) as exc:
        await _call(request, allowed_names=["openai.gpt-5.6-luna"])
    assert exc.value.status_code == 403

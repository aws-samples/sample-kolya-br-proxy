"""Stored responses can only be continued by the key that created them.

Bedrock keeps Responses API results per AWS account (``store`` defaults to
true) and every key shares the gateway's account; ``previous_response_id``
continues a stored response, context included, for whoever presents the ID.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import responses as responses_module
from app.models.token import APIToken
from app.services import response_ownership
from app.services.mantle_client import _openai_to_responses

MODEL = "openai.gpt-6-luna"


async def _call(body, *, owner=True, upstream=None):
    token = cast(
        APIToken, SimpleNamespace(id="tok-a", user_id="u", token_metadata=None)
    )
    req = MagicMock()
    req.json = AsyncMock(return_value={"model": MODEL, "stream": False, **body})
    db = MagicMock()
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = [SimpleNamespace(model_name=MODEL)]
    db.execute = AsyncMock(return_value=rows)

    @asynccontextmanager
    async def fake_scope():
        yield db

    with (
        patch("app.services.quota.enforce_quota", new=AsyncMock()),
        patch.object(responses_module, "session_scope", fake_scope),
        patch.object(
            responses_module, "resolve_responses_model_id", return_value=MODEL
        ),
        patch.object(
            responses_module.MantleClient,
            "responses_passthrough",
            new=AsyncMock(return_value=upstream or {"id": "resp_new", "store": True}),
        ) as passthrough,
        patch.object(response_ownership, "is_owner", new=AsyncMock(return_value=owner)),
        patch.object(response_ownership, "record_owner", new=AsyncMock()) as record,
        patch.object(responses_module, "record_usage", new=AsyncMock()),
        patch.object(responses_module.background_tasks, "create_task"),
    ):
        try:
            await responses_module.create_response(req, token=token)
        except HTTPException as e:
            return e, passthrough, record
    return None, passthrough, record


@pytest.mark.asyncio
async def test_other_keys_response_cannot_be_continued():
    err, passthrough, _ = await _call({"previous_response_id": "resp_x"}, owner=False)
    assert err is not None and err.status_code == 404
    passthrough.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [123, ["resp_x"], {"id": "resp_x"}])
async def test_non_string_previous_id_rejected(value):
    err, passthrough, _ = await _call({"previous_response_id": value})
    assert err is not None and err.status_code == 404
    passthrough.assert_not_awaited()


@pytest.mark.asyncio
async def test_own_response_can_be_continued():
    err, passthrough, _ = await _call({"previous_response_id": "resp_mine"}, owner=True)
    assert err is None
    passthrough.assert_awaited_once()


@pytest.mark.asyncio
async def test_conversation_param_rejected():
    err, passthrough, _ = await _call({"conversation": "conv_x"})
    assert err is not None and err.status_code == 400
    passthrough.assert_not_awaited()


@pytest.mark.asyncio
async def test_stored_response_owner_recorded():
    _, _, record = await _call({})
    record.assert_awaited_once_with("resp_new", "tok-a")


@pytest.mark.asyncio
async def test_unstored_response_not_recorded():
    _, _, record = await _call(
        {"store": False}, upstream={"id": "resp_new", "store": False}
    )
    record.assert_not_awaited()


def test_gateway_translations_do_not_store_upstream():
    body = _openai_to_responses(
        {"model": MODEL, "messages": [{"role": "user", "content": "hi"}]}
    )
    assert body["store"] is False


@pytest.mark.parametrize(
    "body,response,stored",
    [
        ({}, None, True),
        ({"store": False}, None, False),
        ({}, {"store": False}, False),
        ({"store": False}, {"store": True}, True),
    ],
)
def test_is_stored(body, response, stored):
    assert response_ownership.is_stored(body, response) is stored

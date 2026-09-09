"""Regression tests for model-access normalization on the Responses endpoint.

The OpenAI Responses path (``POST /v1/responses``, used by codex-style clients)
resolves a client model to its canonical mantle ID (``gpt-6-astra`` →
``openai.gpt-6-astra``) but a token is often granted the same model under its
Bedrock inference-profile ID (``us.openai.gpt-6-astra``). Before the fix the
access check was an exact match, so the prefixed grant never matched the bare
mantle ID and returned 403. These tests pin that the region prefix is ignored
for authorization while the mantle canonical ID is still forwarded downstream.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import responses as responses_module


def _http_request(body):
    req = MagicMock()
    req.json = AsyncMock(return_value=body)
    return req


def _db_with_models(names):
    db = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [
        SimpleNamespace(model_name=n) for n in names
    ]
    db.execute = AsyncMock(return_value=result)
    return db


async def _call(requested_model, canonical, allowed_names):
    token = SimpleNamespace(id="tok", user_id="usr", token_metadata=None)
    db = _db_with_models(allowed_names)
    http_request = _http_request({"model": requested_model, "stream": False})
    with (
        patch("app.services.quota.enforce_quota", new=AsyncMock()),
        patch.object(
            responses_module, "resolve_mantle_model_id", return_value=canonical
        ),
        patch.object(
            responses_module.MantleClient,
            "responses_passthrough",
            new=AsyncMock(return_value={"ok": True}),
        ) as passthrough,
        patch.object(responses_module, "record_usage", new=AsyncMock()),
        patch.object(responses_module.background_tasks, "create_task"),
    ):
        result = await responses_module.create_response(
            http_request, token=token, db=db
        )
    return result, passthrough


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested", "canonical", "granted"),
    [
        ("gpt-6-astra", "openai.gpt-6-astra", "us.openai.gpt-6-astra"),
        ("openai.gpt-6-astra", "openai.gpt-6-astra", "global.openai.gpt-6-astra"),
        ("openai.gpt-5.6-sol", "openai.gpt-5.6-sol", "openai.gpt-5.6-sol"),
    ],
)
async def test_region_prefixed_grant_authorises(requested, canonical, granted):
    _result, passthrough = await _call(requested, canonical, allowed_names=[granted])
    # Authorised → forwarded to mantle with the canonical (bare) ID.
    passthrough.assert_awaited_once()
    forwarded_body = passthrough.await_args.args[0]
    assert forwarded_body["model"] == canonical


@pytest.mark.asyncio
async def test_unrelated_model_still_403():
    with pytest.raises(HTTPException) as exc:
        await _call(
            "gpt-6-nova",
            "openai.gpt-6-nova",
            allowed_names=["us.openai.gpt-6-astra"],
        )
    assert exc.value.status_code == 403

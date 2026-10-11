"""Regression tests for model-access normalization on the Responses endpoint.

The OpenAI Responses path (``POST /v1/responses``, used by codex-style clients)
resolves a client model to its canonical mantle ID (``gpt-6-astra`` →
``openai.gpt-6-astra``) but a token is often granted the same model under its
Bedrock inference-profile ID (``us.openai.gpt-6-astra``). Before the fix the
access check was an exact match, so the prefixed grant never matched the bare
mantle ID and returned 403. These tests pin that the region prefix is ignored
for authorization while the mantle canonical ID is still forwarded downstream.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import responses as responses_module
from app.models.token import APIToken


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


async def _call(requested_model, canonical, allowed_names, body=None):
    token = cast(
        APIToken, SimpleNamespace(id="tok", user_id="usr", token_metadata=None)
    )
    db = _db_with_models(allowed_names)
    http_request = _http_request(body or {"model": requested_model, "stream": False})

    @asynccontextmanager
    async def fake_scope():
        yield db

    with (
        patch("app.services.quota.enforce_quota", new=AsyncMock()),
        patch.object(responses_module, "session_scope", fake_scope),
        patch.object(
            responses_module, "resolve_responses_model_id", return_value=canonical
        ),
        patch.object(
            responses_module.MantleClient,
            "responses_passthrough",
            new=AsyncMock(return_value={"ok": True}),
        ) as passthrough,
        patch.object(responses_module, "record_usage", new=AsyncMock()),
        patch.object(responses_module.background_tasks, "create_task"),
    ):
        result = await responses_module.create_response(http_request, token=token)
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
async def test_region_prefixed_grant_authorises_within_its_scope(
    requested, canonical, granted
):
    _result, passthrough = await _call(requested, canonical, allowed_names=[granted])
    # A profile-only grant serves canonical/bare requests through that exact
    # profile rather than escalating to In-Region Mantle (scope and price).
    passthrough.assert_awaited_once()
    forwarded_body = passthrough.await_args_list[0].args[0]
    assert forwarded_body["model"] == granted


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "profile", ["us.openai.gpt-5.6-sol", "global.openai.gpt-5.6-sol"]
)
async def test_runtime_profile_is_forwarded_without_canonicalization(profile):
    _result, passthrough = await _call(profile, profile, allowed_names=[profile])
    forwarded_body = passthrough.await_args_list[0].args[0]
    assert forwarded_body["model"] == profile


@pytest.mark.asyncio
async def test_global_profile_is_not_authorized_by_us_profile_grant():
    with pytest.raises(HTTPException) as exc:
        await _call(
            "global.openai.gpt-5.6-sol",
            "global.openai.gpt-5.6-sol",
            allowed_names=["us.openai.gpt-5.6-sol"],
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_unrelated_model_still_403():
    with pytest.raises(HTTPException) as exc:
        await _call(
            "gpt-6-nova",
            "openai.gpt-6-nova",
            allowed_names=["us.openai.gpt-6-astra"],
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_unsupported_native_breakpoint_returns_400_before_upstream():
    body = {
        "model": "us.openai.gpt-6.1-sol",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,AA==",
                        "prompt_cache_breakpoint": {"mode": "explicit"},
                    }
                ],
            }
        ],
    }

    with pytest.raises(HTTPException) as exc:
        await _call(
            body["model"],
            body["model"],
            allowed_names=[body["model"]],
            body=body,
        )

    assert exc.value.status_code == 400
    assert "input_image" in exc.value.detail


@pytest.mark.asyncio
async def test_unauthorized_token_gets_403_before_cache_validation():
    body = {
        "model": "us.openai.gpt-6.1-sol",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_image", "prompt_cache_breakpoint": {}}],
            }
        ],
    }
    with pytest.raises(HTTPException) as exc:
        await _call(
            body["model"],
            body["model"],
            allowed_names=["global.openai.gpt-6.1-sol"],
            body=body,
        )
    assert exc.value.status_code == 403

"""Regression tests for native Responses streaming failures."""

import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.api.v1.endpoints import responses


def _token() -> MagicMock:
    token = MagicMock()
    token.id = "token-id"
    token.user_id = "user-id"
    return token


def _upstream_error() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://bedrock-mantle.example/responses")
    response = httpx.Response(
        500,
        request=request,
        headers={"x-amzn-requestid": "aws-request-123"},
        content=b"temporary upstream failure",
    )
    return httpx.HTTPStatusError(
        "mantle stream error 500: temporary upstream failure",
        request=request,
        response=response,
    )


@pytest.mark.asyncio
async def test_prestream_responses_error_is_observable_without_leaking(caplog):
    calls = 0

    async def stream(_body):
        nonlocal calls
        calls += 1
        raise _upstream_error()
        yield b""  # pragma: no cover - keeps this an async generator

    record_usage = MagicMock()
    with (
        patch.object(responses.MantleClient, "responses_passthrough_stream", stream),
        patch.object(responses, "record_usage", record_usage),
        caplog.at_level(logging.ERROR, logger=responses.__name__),
    ):
        chunks = [
            chunk
            async for chunk in responses._stream_responses(
                body={},
                request_id="gateway-request-456",
                model="openai.gpt-5.6-sol",
                token=_token(),
                start_time=0.0,
            )
        ]

    output = b"".join(chunks).decode()
    assert calls == 1
    assert "Bedrock Responses API error: status 500" in output
    assert "temporary upstream failure" not in output
    assert "aws-request-123" not in output
    assert "model=openai.gpt-5.6-sol" in caplog.text
    assert "status=500" in caplog.text
    assert "gateway-request-456" not in caplog.text
    assert "aws-request-123" not in caplog.text
    assert "temporary upstream failure" not in caplog.text
    assert "upstream_detail" not in caplog.text
    record_usage.assert_not_called()

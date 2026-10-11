"""Upstream selection for Bedrock OpenAI Responses requests."""

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import mantle_client
from app.services.mantle_client import MantleClient


@pytest.mark.parametrize(
    "model",
    ["us.openai.gpt-5.6-sol", "global.openai.gpt-5.6-sol"],
)
def test_inference_profile_targets_runtime_responses(monkeypatch, model):
    monkeypatch.setattr(
        mantle_client,
        "get_settings",
        lambda: SimpleNamespace(AWS_REGION="us-west-2"),
    )

    target = MantleClient._endpoint(model)

    assert target.url == (
        "https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1/responses"
    )
    assert target.region == "us-west-2"
    assert target.sigv4_service == "bedrock"
    assert target.backend == "bedrock-runtime-responses"


def test_canonical_model_still_targets_mantle_responses(monkeypatch):
    monkeypatch.setattr(
        mantle_client,
        "resolve_mantle_region",
        lambda model: "us-east-1",
    )

    target = MantleClient._endpoint("openai.gpt-5.6-sol")

    assert target.url == (
        "https://bedrock-mantle.us-east-1.api.aws/openai/v1/responses"
    )
    assert target.region == "us-east-1"
    assert target.sigv4_service
    assert target.backend == "bedrock-mantle-responses"


@pytest.mark.asyncio
async def test_runtime_passthrough_signs_and_preserves_explicit_cache_body(
    monkeypatch, caplog
):
    monkeypatch.setattr(
        mantle_client,
        "get_settings",
        lambda: SimpleNamespace(AWS_REGION="us-east-1"),
    )
    signed = AsyncMock(return_value={"Authorization": "redacted"})
    monkeypatch.setattr(mantle_client, "signed_headers", signed)
    captured = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"id": "response-test"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, headers, content):
            captured.update(url=url, headers=headers, content=content)
            return FakeResponse()

    monkeypatch.setattr(
        mantle_client.httpx,
        "AsyncClient",
        lambda **kwargs: FakeClient(),
    )
    body = {
        "model": "global.openai.gpt-5.6-sol",
        "prompt_cache_options": {"mode": "explicit"},
        "input": [
            {
                "type": "message",
                "role": "developer",
                "content": [
                    {
                        "type": "input_text",
                        "text": "shared prefix",
                        "prompt_cache_breakpoint": {"mode": "explicit"},
                    }
                ],
            }
        ],
    }

    caplog.set_level(logging.INFO, logger="app.services.mantle_client")
    result = await MantleClient.responses_passthrough(body)

    assert result == {"id": "response-test"}
    assert captured["url"].endswith("/openai/v1/responses")
    forwarded = json.loads(captured["content"])
    assert forwarded["model"] == "global.openai.gpt-5.6-sol"
    assert forwarded["prompt_cache_options"] == {"mode": "explicit"}
    assert forwarded["input"][0]["content"][0]["prompt_cache_breakpoint"] == {
        "mode": "explicit"
    }
    assert signed.await_args.kwargs["service"] == "bedrock"
    assert "backend=bedrock-runtime-responses" in caplog.text
    assert "cache_mode=explicit" in caplog.text
    assert "breakpoints=1" in caplog.text
    assert "shared prefix" not in caplog.text


@pytest.mark.asyncio
async def test_stream_failure_log_omits_upstream_message(monkeypatch, caplog):
    monkeypatch.setattr(
        mantle_client,
        "get_settings",
        lambda: SimpleNamespace(AWS_REGION="us-east-1"),
    )
    monkeypatch.setattr(mantle_client, "signed_headers", AsyncMock(return_value={}))

    class FakeStreamResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def aiter_lines(self):
            yield "event: response.failed"
            yield (
                'data: {"type":"response.failed","response":{"error":'
                '{"type":"server_error","code":"upstream_failed",'
                '"message":"sensitive upstream detail"}}}'
            )
            yield ""

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def stream(self, *args, **kwargs):
            return FakeStreamResponse()

    monkeypatch.setattr(
        mantle_client.httpx,
        "AsyncClient",
        lambda **kwargs: FakeClient(),
    )
    caplog.set_level(logging.ERROR, logger="app.services.mantle_client")

    chunks = [
        chunk
        async for chunk in MantleClient.invoke_stream(
            {
                "model": "global.openai.gpt-5.6-sol",
                "messages": [{"role": "user", "content": "question"}],
            }
        )
    ]

    public_error = json.loads(chunks[-1].removeprefix("data: "))
    assert public_error == {
        "error": {
            "message": "Bedrock Responses stream failed",
            "type": "server_error",
            "code": "upstream_failed",
        }
    }
    assert "error_type=server_error" in caplog.text
    assert "error_code=upstream_failed" in caplog.text
    assert "sensitive upstream detail" not in caplog.text

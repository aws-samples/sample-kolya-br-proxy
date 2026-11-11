# pyright: reportArgumentType=false, reportAttributeAccessIssue=false
"""Malformed client input is a 400, not a 500.

Each case is a request shape the 2026-11-10 penetration test sent that the
gateway answered with HTTP 500 before this change.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1.endpoints.usage import _naive_utc
from app.schemas.anthropic import AnthropicMessagesRequest
from app.schemas.bedrock import BedrockRequest
from app.schemas.openai import ChatCompletionRequest
from app.services.anthropic_translator import AnthropicRequestTranslator
from app.services.bedrock import BedrockClient
from app.services.request_errors import InvalidRequestError
from app.services.translator import RequestTranslator

MODEL = "anthropic.claude-haiku-5-5"


@pytest.mark.parametrize("text", [1, ["a"], True, {"x": 1}])
def test_non_string_text_in_system_is_a_validation_error(text):
    with pytest.raises(ValidationError):
        AnthropicMessagesRequest.model_validate(
            {
                "model": MODEL,
                "max_tokens": 1,
                "messages": [
                    {"role": "system", "content": [{"type": "text", "text": text}]},
                    {"role": "user", "content": "hi"},
                ],
            }
        )


def _bedrock_request(**fields):
    return BedrockRequest.model_validate(
        {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 1, **fields}
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"tools": "not-a-list"},
        {"messages": [{"role": "user", "content": [1, 2]}]},
    ],
)
def test_bad_shapes_in_anthropic_body_are_invalid_request(fields):
    try:
        req = _bedrock_request(**fields)
    except ValidationError:
        return  # rejected even earlier, which is also a 4xx
    with pytest.raises(InvalidRequestError):
        BedrockClient._build_anthropic_body(req, model_id=MODEL)


def test_invalid_request_error_is_a_value_error():
    # The endpoints already map ValueError to 400.
    assert issubclass(InvalidRequestError, ValueError)


@pytest.mark.asyncio
async def test_openai_translation_shape_error_is_invalid_request(monkeypatch):
    request = ChatCompletionRequest.model_validate(
        {"model": MODEL, "messages": [{"role": "user", "content": "hi"}]}
    )
    # Simulate a loose field carrying the wrong type deep in translation.
    monkeypatch.setattr(request, "messages", [None])
    with pytest.raises(InvalidRequestError):
        await RequestTranslator.openai_to_bedrock(request)


def test_anthropic_translation_shape_error_is_invalid_request(monkeypatch):
    request = AnthropicMessagesRequest.model_validate(
        {
            "model": MODEL,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}],
        }
    )
    monkeypatch.setattr(request, "messages", ["not-a-message"])
    with pytest.raises(InvalidRequestError):
        AnthropicRequestTranslator.to_bedrock(request)


@pytest.mark.parametrize("latency", ["optimized", "standard"])
def test_invoke_maps_performance_config_to_latency_param(latency):
    kwargs = BedrockClient._build_invoke_kwargs(
        _bedrock_request(performance_config={"latency": latency}), MODEL
    )
    assert kwargs["performanceConfigLatency"] == latency
    assert "performanceConfig" not in kwargs


@pytest.mark.parametrize("config", [{"latency": "fast"}, {"latency": 1}, "optimized"])
def test_invoke_rejects_bad_performance_config(config):
    try:
        req = _bedrock_request(performance_config=config)
    except ValidationError:
        return
    with pytest.raises(InvalidRequestError):
        BedrockClient._build_invoke_kwargs(req, MODEL)


def test_usage_date_overflow_is_400():
    edge = datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=5)))
    with pytest.raises(HTTPException) as exc:
        _naive_utc(edge)
    assert exc.value.status_code == 400

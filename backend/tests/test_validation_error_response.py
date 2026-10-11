"""Validation errors must always render as JSON rather than cascading to 500."""

import json
from unittest.mock import MagicMock

import pytest
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.schemas.openai import ChatCompletionRequest
from main import _validation_exception_handler


def _five_marker_payload() -> dict:
    return {
        "model": "us.openai.gpt-5.6-sol",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"prefix {index}",
                        "cache_control": {"type": "ephemeral"},
                    }
                    for index in range(5)
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_custom_value_error_context_is_json_serializable():
    payload = _five_marker_payload()
    with pytest.raises(ValidationError) as caught:
        ChatCompletionRequest.model_validate(payload)

    request = MagicMock()
    request.url.path = "/v1/chat/completions"
    request.headers = {}
    exc = RequestValidationError(caught.value.errors(), body=payload)

    response = await _validation_exception_handler(request, exc)
    parsed = json.loads(response.body)

    assert response.status_code == 422
    assert parsed["error"]["type"] == "invalid_request_error"
    serialized = json.dumps(parsed)
    assert "At most 4 prompt cache breakpoints" in serialized
    assert "prefix 0" not in serialized

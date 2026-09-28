"""Anthropic tool definitions must serialize to Bedrock-supported fields."""

import pytest

from app.schemas.anthropic import AnthropicMessagesRequest
from app.services.anthropic_translator import AnthropicRequestTranslator
from app.services.bedrock import BedrockClient


@pytest.mark.parametrize(
    ("request_model", "bedrock_model_id"),
    [
        ("claude-opus-4-8", "global.anthropic.claude-opus-4-8"),
        ("claude-opus-5", "global.anthropic.claude-opus-5"),
        ("claude-opus-5-5", "global.anthropic.claude-opus-5-5"),
    ],
)
def test_strict_tool_is_not_forwarded_to_unsupported_models(
    request_model: str, bedrock_model_id: str
):
    request = AnthropicMessagesRequest.model_validate(
        {
            "model": request_model,
            "max_tokens": 256,
            "messages": [{"role": "user", "content": "Use the lookup tool"}],
            "tools": [
                {
                    "name": "lookup",
                    "description": "Look up a value",
                    "input_schema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                    "strict": True,
                }
            ],
        }
    )

    bedrock_request = AnthropicRequestTranslator.to_bedrock(request)
    body = BedrockClient._build_anthropic_body(
        bedrock_request,
        model_id=bedrock_model_id,
    )

    assert body["tools"] == [
        {
            "name": "lookup",
            "description": "Look up a value",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
    ]


def test_strict_tool_is_preserved_for_documented_supported_model():
    request = AnthropicMessagesRequest.model_validate(
        {
            "model": "claude-opus-4-6",
            "max_tokens": 256,
            "messages": [{"role": "user", "content": "Use the lookup tool"}],
            "tools": [
                {
                    "name": "lookup",
                    "input_schema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                    },
                    "strict": True,
                }
            ],
        }
    )

    bedrock_request = AnthropicRequestTranslator.to_bedrock(request)
    body = BedrockClient._build_anthropic_body(
        bedrock_request,
        model_id="global.anthropic.claude-opus-4-6",
    )

    assert body["tools"][0]["strict"] is True

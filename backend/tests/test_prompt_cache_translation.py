"""Client cache-control markers must survive every compatible gateway path."""

from unittest.mock import MagicMock

import pytest

from app.api.anthropic.endpoints.messages import (
    _anthropic_to_openai_messages,
    _handle_mantle_via_anthropic,
)
from app.api.v1.endpoints.chat import _handle_mantle_request
from app.models.token import APIToken
from app.schemas.anthropic import AnthropicMessagesRequest
from app.schemas.openai import ChatCompletionRequest
from app.services.anthropic_translator import AnthropicRequestTranslator
from app.services.bedrock import BedrockClient
from app.services.mantle_client import _openai_to_responses
from app.services.translator import RequestTranslator

CACHE_CONTROL = {"type": "ephemeral"}


def _marked_text(text: str) -> dict:
    return {"type": "text", "text": text, "cache_control": CACHE_CONTROL}


def _responses_body(request: ChatCompletionRequest) -> dict:
    return _openai_to_responses(request.model_dump(exclude_none=True))


def test_chat_sol_maps_cache_control_to_explicit_responses_breakpoint():
    request = ChatCompletionRequest.model_validate(
        {
            "model": "openai.gpt-5.6-sol",
            "messages": [
                {"role": "system", "content": [_marked_text("shared prefix")]},
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "dynamic suffix"}],
                },
            ],
        }
    )

    body = _responses_body(request)

    assert body["prompt_cache_options"] == {"mode": "explicit"}
    assert body["input"][0]["content"][0] == {
        "type": "input_text",
        "text": "shared prefix",
        "prompt_cache_breakpoint": {"mode": "explicit"},
    }
    assert "prompt_cache_breakpoint" not in body["input"][1]["content"][0]


def test_chat_rejects_more_than_four_cache_breakpoints():
    with pytest.raises(ValueError, match="At most 4"):
        ChatCompletionRequest.model_validate(
            {
                "model": "openai.gpt-5.6-sol",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            _marked_text(f"prefix {index}") for index in range(5)
                        ],
                    }
                ],
            }
        )


def test_chat_sol_without_marker_keeps_implicit_default():
    request = ChatCompletionRequest.model_validate(
        {
            "model": "openai.gpt-5.6-sol",
            "messages": [{"role": "user", "content": "no explicit marker"}],
        }
    )

    body = _responses_body(request)

    assert "prompt_cache_options" not in body


@pytest.mark.asyncio
async def test_chat_anthropic_preserves_system_cache_control():
    request = ChatCompletionRequest.model_validate(
        {
            "model": "anthropic.claude-haiku-5-5",
            "messages": [
                {"role": "system", "content": [_marked_text("shared prefix")]},
                {"role": "user", "content": "dynamic suffix"},
            ],
            "bedrock_auto_cache": True,
        }
    )

    bedrock_request = await RequestTranslator.openai_to_bedrock(request)
    body = BedrockClient._build_anthropic_body(
        bedrock_request,
        model_id="anthropic.claude-haiku-5-5",
    )

    assert body["system"] == [
        {
            "type": "text",
            "text": "shared prefix",
            "cache_control": CACHE_CONTROL,
        }
    ]


@pytest.mark.asyncio
async def test_chat_anthropic_preserves_message_cache_control():
    request = ChatCompletionRequest.model_validate(
        {
            "model": "anthropic.claude-opus-5-5",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        _marked_text("shared prefix"),
                        {"type": "text", "text": "dynamic suffix"},
                    ],
                }
            ],
            "bedrock_auto_cache": False,
        }
    )

    bedrock_request = await RequestTranslator.openai_to_bedrock(request)
    body = BedrockClient._build_anthropic_body(
        bedrock_request,
        model_id="anthropic.claude-opus-5-5",
    )

    assert body["messages"][0]["content"][0]["cache_control"] == CACHE_CONTROL
    assert "cache_control" not in body["messages"][0]["content"][1]


def test_messages_rejects_more_than_four_cache_breakpoints():
    with pytest.raises(ValueError, match="At most 4"):
        AnthropicMessagesRequest.model_validate(
            {
                "model": "anthropic.claude-opus-5-5",
                "max_tokens": 256,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            _marked_text(f"prefix {index}") for index in range(5)
                        ],
                    }
                ],
            }
        )


def test_messages_counts_cache_markers_on_fallback_content_blocks():
    with pytest.raises(ValueError, match="At most 4"):
        AnthropicMessagesRequest.model_validate(
            {
                "model": "anthropic.claude-opus-5-5",
                "max_tokens": 256,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {"type": "text", "data": str(index)},
                                "cache_control": CACHE_CONTROL,
                            }
                            for index in range(5)
                        ],
                    }
                ],
            }
        )


def test_messages_anthropic_preserves_client_cache_control():
    request = AnthropicMessagesRequest.model_validate(
        {
            "model": "anthropic.claude-opus-5-5",
            "max_tokens": 256,
            "system": [_marked_text("shared system")],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        _marked_text("shared message"),
                        {"type": "text", "text": "dynamic suffix"},
                    ],
                }
            ],
        }
    )

    bedrock_request = AnthropicRequestTranslator.to_bedrock(request)
    bedrock_request.auto_cache = True
    body = BedrockClient._build_anthropic_body(
        bedrock_request,
        model_id="anthropic.claude-opus-5-5",
    )

    assert body["system"][0]["cache_control"] == CACHE_CONTROL
    assert body["messages"][0]["content"][0]["cache_control"] == CACHE_CONTROL
    assert "cache_control" not in body["messages"][0]["content"][1]


def test_messages_sol_maps_cache_control_to_explicit_responses_breakpoint():
    request = AnthropicMessagesRequest.model_validate(
        {
            "model": "openai.gpt-5.6-sol",
            "max_tokens": 256,
            "system": [_marked_text("shared prefix")],
            "messages": [{"role": "user", "content": "dynamic suffix"}],
        }
    )

    openai_messages = _anthropic_to_openai_messages(request)
    body = _openai_to_responses({"model": request.model, "messages": openai_messages})

    assert body["prompt_cache_options"] == {"mode": "explicit"}
    assert body["input"][0]["content"][0]["prompt_cache_breakpoint"] == {
        "mode": "explicit"
    }
    assert "prompt_cache_breakpoint" not in body["input"][1]["content"][0]


def test_messages_sol_preserves_message_cache_control():
    request = AnthropicMessagesRequest.model_validate(
        {
            "model": "openai.gpt-5.6-sol",
            "max_tokens": 256,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        _marked_text("shared prefix"),
                        {"type": "text", "text": "dynamic suffix"},
                    ],
                }
            ],
        }
    )

    body = _openai_to_responses(
        {
            "model": request.model,
            "messages": _anthropic_to_openai_messages(request),
        }
    )

    assert body["prompt_cache_options"] == {"mode": "explicit"}
    assert body["input"][0]["content"][0]["prompt_cache_breakpoint"] == {
        "mode": "explicit"
    }
    assert "prompt_cache_breakpoint" not in body["input"][0]["content"][1]


def test_chat_sol_rejects_breakpoint_on_assistant_output_content():
    request = ChatCompletionRequest.model_validate(
        {
            "model": "openai.gpt-5.6-sol",
            "messages": [
                {"role": "assistant", "content": [_marked_text("prior output")]},
                {"role": "user", "content": "continue"},
            ],
        }
    )

    with pytest.raises(ValueError, match="not supported on assistant content"):
        _responses_body(request)


@pytest.mark.asyncio
async def test_chat_anthropic_keeps_marked_boundary_across_system_messages():
    request = ChatCompletionRequest.model_validate(
        {
            "model": "anthropic.claude-haiku-5-5",
            "messages": [
                {"role": "system", "content": [_marked_text("shared prefix")]},
                {"role": "system", "content": "dynamic system suffix"},
                {"role": "user", "content": "question"},
            ],
            "bedrock_auto_cache": True,
        }
    )

    bedrock_request = await RequestTranslator.openai_to_bedrock(request)
    body = BedrockClient._build_anthropic_body(
        bedrock_request,
        model_id="anthropic.claude-haiku-5-5",
    )

    assert body["system"][0]["cache_control"] == CACHE_CONTROL
    assert body["system"][1]["text"] == "\n\ndynamic system suffix"
    assert "cache_control" not in body["system"][1]


def test_messages_hoisted_system_role_preserves_cache_control_for_sol():
    request = AnthropicMessagesRequest.model_validate(
        {
            "model": "openai.gpt-5.6-sol",
            "max_tokens": 256,
            "messages": [
                {"role": "system", "content": [_marked_text("shared prefix")]},
                {"role": "user", "content": "dynamic suffix"},
            ],
        }
    )

    assert request.system and not isinstance(request.system, str)
    body = _openai_to_responses(
        {
            "model": request.model,
            "messages": _anthropic_to_openai_messages(request),
        }
    )

    assert body["prompt_cache_options"] == {"mode": "explicit"}
    assert body["input"][0]["content"][0]["prompt_cache_breakpoint"] == {
        "mode": "explicit"
    }


def test_unmarked_anthropic_arrays_keep_legacy_flattened_wire_shape():
    request = AnthropicMessagesRequest.model_validate(
        {
            "model": "openai.gpt-5.6-sol",
            "max_tokens": 256,
            "system": [
                {"type": "text", "text": "system one"},
                {"type": "text", "text": "system two"},
            ],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "message one"},
                        {"type": "text", "text": "message two"},
                    ],
                }
            ],
        }
    )

    bedrock_request = AnthropicRequestTranslator.to_bedrock(request)
    openai_messages = _anthropic_to_openai_messages(request)

    assert bedrock_request.system == "system one system two"
    assert openai_messages == [
        {"role": "system", "content": "system one system two"},
        {"role": "user", "content": "message one\nmessage two"},
    ]


def test_messages_anthropic_preserves_tool_use_cache_control():
    request = AnthropicMessagesRequest.model_validate(
        {
            "model": "anthropic.claude-opus-5-5",
            "max_tokens": 256,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool-1",
                            "name": "lookup",
                            "input": {"query": "cache"},
                            "cache_control": CACHE_CONTROL,
                        }
                    ],
                }
            ],
        }
    )

    bedrock_request = AnthropicRequestTranslator.to_bedrock(request)
    body = BedrockClient._build_anthropic_body(
        bedrock_request,
        model_id="anthropic.claude-opus-5-5",
    )

    assert body["messages"][0]["content"][0]["cache_control"] == CACHE_CONTROL


@pytest.mark.asyncio
async def test_chat_sol_stream_rejects_assistant_marker_before_response_starts():
    request = ChatCompletionRequest.model_validate(
        {
            "model": "openai.gpt-5.6-sol",
            "stream": True,
            "messages": [
                {"role": "assistant", "content": [_marked_text("prior output")]}
            ],
        }
    )

    with pytest.raises(ValueError, match="not supported on assistant content"):
        await _handle_mantle_request(request, "req-test", MagicMock(spec=APIToken), 0.0)


@pytest.mark.asyncio
async def test_messages_sol_stream_rejects_assistant_marker_before_response_starts():
    request = AnthropicMessagesRequest.model_validate(
        {
            "model": "openai.gpt-5.6-sol",
            "max_tokens": 256,
            "stream": True,
            "messages": [
                {"role": "assistant", "content": [_marked_text("prior output")]}
            ],
        }
    )

    with pytest.raises(ValueError, match="not supported on assistant content"):
        await _handle_mantle_via_anthropic(
            request, "req-test", MagicMock(spec=APIToken), 0.0
        )


@pytest.mark.parametrize(
    ("role", "block"),
    [
        (
            "assistant",
            {
                "type": "tool_use",
                "id": "tool-1",
                "name": "lookup",
                "input": {},
                "cache_control": CACHE_CONTROL,
            },
        ),
        (
            "user",
            {
                "type": "tool_result",
                "tool_use_id": "tool-1",
                "content": "result",
                "cache_control": CACHE_CONTROL,
            },
        ),
    ],
)
def test_messages_sol_rejects_marked_non_text_blocks(role: str, block: dict):
    request = AnthropicMessagesRequest.model_validate(
        {
            "model": "openai.gpt-5.6-sol",
            "max_tokens": 256,
            "messages": [{"role": role, "content": [block]}],
        }
    )

    with pytest.raises(ValueError, match="not supported"):
        _anthropic_to_openai_messages(request)

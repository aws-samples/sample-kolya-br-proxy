"""Anthropic protocol fidelity when GPT profiles use Responses upstream."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.api.anthropic.endpoints import messages as messages_module
from app.api.anthropic.endpoints.messages import (
    _anthropic_to_openai_payload,
    _openai_response_to_anthropic_content,
)
from app.schemas.anthropic import AnthropicMessagesRequest
from app.services.mantle_client import (
    MantleClient,
    _openai_to_responses,
    _responses_to_openai,
)

CACHE_CONTROL = {"type": "ephemeral"}


def test_anthropic_images_tools_and_results_survive_responses_translation():
    request = AnthropicMessagesRequest.model_validate(
        {
            "model": "global.openai.gpt-5.6-sol",
            "max_tokens": 256,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "AA==",
                            },
                            "cache_control": CACHE_CONTROL,
                        },
                        {"type": "text", "text": "inspect"},
                    ],
                },
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call-1",
                            "name": "lookup",
                            "input": {"query": "value"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call-1",
                            "content": "result",
                        }
                    ],
                },
            ],
            "tools": [
                {
                    "name": "lookup",
                    "description": "Look up a value",
                    "input_schema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                    },
                    "strict": True,
                }
            ],
            "tool_choice": {"type": "tool", "name": "lookup"},
        }
    )

    payload = _anthropic_to_openai_payload(request)
    body = _openai_to_responses(payload)

    image = body["input"][0]["content"][0]
    assert image == {
        "type": "input_image",
        "image_url": "data:image/png;base64,AA==",
        "prompt_cache_breakpoint": {"mode": "explicit"},
    }
    assert body["input"][1] == {
        "type": "function_call",
        "call_id": "call-1",
        "name": "lookup",
        "arguments": '{"query": "value"}',
    }
    assert body["input"][2] == {
        "type": "function_call_output",
        "call_id": "call-1",
        "output": "result",
    }
    assert body["tools"][0]["name"] == "lookup"
    assert body["tools"][0]["strict"] is True
    assert body["tool_choice"] == {"type": "function", "name": "lookup"}
    assert body["prompt_cache_options"] == {"mode": "explicit"}


def test_url_images_and_multimodal_tool_results_survive_translation():
    request = AnthropicMessagesRequest.model_validate(
        {
            "model": "us.openai.gpt-5.6-sol",
            "max_tokens": 128,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "url",
                                "url": "https://example.invalid/a.png",
                            },
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call-1",
                            "content": [
                                {"type": "text", "text": "result"},
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": "AA==",
                                    },
                                },
                            ],
                        }
                    ],
                },
            ],
        }
    )

    body = _openai_to_responses(_anthropic_to_openai_payload(request))

    assert body["input"][0]["content"][0]["image_url"] == (
        "https://example.invalid/a.png"
    )
    assert body["input"][1]["type"] == "function_call_output"
    assert body["input"][1]["output"][0] == {
        "type": "input_text",
        "text": "result",
    }
    assert body["input"][1]["output"][1]["type"] == "input_image"


def test_openai_tool_calls_become_anthropic_tool_use_blocks():
    content, stop_reason = _openai_response_to_anthropic_content(
        {
            "content": "checking",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "arguments": '{"query":"value"}',
                    },
                }
            ],
        }
    )

    assert content == [
        {"type": "text", "text": "checking"},
        {
            "type": "tool_use",
            "id": "call-1",
            "name": "lookup",
            "input": {"query": "value"},
        },
    ]
    assert stop_reason == "tool_use"


def test_chat_conversion_keeps_text_alongside_tool_calls():
    response = _responses_to_openai(
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "checking"}],
                },
                {
                    "type": "function_call",
                    "call_id": "call-1",
                    "name": "lookup",
                    "arguments": "{}",
                },
            ],
            "usage": {},
        },
        "global.openai.gpt-5.6-sol",
        "request-test",
    )

    message = response["choices"][0]["message"]
    assert message["content"] == "checking"
    assert message["tool_calls"][0]["id"] == "call-1"


@pytest.mark.asyncio
async def test_streaming_tool_call_becomes_anthropic_tool_events():
    async def chunks(_payload):
        yield (
            'data: {"choices":[{"delta":{"content":"checking","tool_calls":[{"index":0,'
            '"id":"call-1","type":"function","function":{"name":"lookup",'
            '"arguments":""}}]},"finish_reason":null}]}\n\n'
        )
        yield (
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
            '"function":{"arguments":"{\\"query\\":\\"value\\"}"}}]},'
            '"finish_reason":null}]}\n\n'
        )
        yield (
            'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}],'
            '"usage":{"prompt_tokens":20,"completion_tokens":5,'
            '"prompt_tokens_details":{"cache_write_tokens":10}}}\n\n'
        )
        yield "data: [DONE]\n\n"

    token = SimpleNamespace(id="tok", user_id="usr")
    with (
        patch.object(MantleClient, "invoke_stream", new=chunks),
        patch.object(
            messages_module.background_tasks, "create_task", new=MagicMock()
        ) as create_task,
    ):
        output = "".join(
            [
                event
                async for event in messages_module._stream_mantle_as_anthropic(
                    payload={},
                    request_id="request-test",
                    model="global.openai.gpt-5.6-sol",
                    token=token,
                    start_time=0.0,
                )
            ]
        )

    assert '"type": "tool_use"' in output
    assert '"id": "call-1"' in output
    assert '"type": "input_json_delta"' in output
    assert '"stop_reason": "tool_use"' in output
    text_stop = output.index('"type": "content_block_stop", "index": 0')
    tool_start = output.index('"type": "tool_use"')
    tool_stop = output.index('"type": "content_block_stop", "index": 1')
    assert text_stop < tool_start < tool_stop
    create_task.assert_called_once()


@pytest.mark.asyncio
async def test_streaming_upstream_error_becomes_anthropic_error_event():
    async def chunks(_payload):
        yield (
            'data: {"error":{"message":"public","type":"server_error",'
            '"code":"upstream_failed"}}\n\n'
        )

    token = SimpleNamespace(id="tok", user_id="usr")
    with (
        patch.object(MantleClient, "invoke_stream", new=chunks),
        patch.object(messages_module.background_tasks, "create_task", new=MagicMock()),
    ):
        output = "".join(
            [
                event
                async for event in messages_module._stream_mantle_as_anthropic(
                    payload={},
                    request_id="request-test",
                    model="us.openai.gpt-5.6-sol",
                    token=token,
                    start_time=0.0,
                )
            ]
        )

    assert "event: error" in output
    assert "Internal server error" in output
    assert "event: message_stop" not in output

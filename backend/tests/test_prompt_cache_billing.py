"""Prompt-cache token categories must each be billed exactly once."""

import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.api.anthropic.endpoints import messages
from app.api.v1.endpoints import chat, responses
from app.api.v1.endpoints.responses import _usage_from_response
from app.models.token import APIToken
from app.services.mantle_client import (
    MantleClient,
    _build_usage,
    extract_cache_write_tokens,
    extract_cache_write_tokens_from_chunk,
    extract_cached_tokens,
)


def _responses_usage():
    return {
        "input_tokens": 100,
        "output_tokens": 10,
        "input_tokens_details": {
            "cached_tokens": 60,
            "cache_write_tokens": 20,
        },
    }


def test_native_responses_usage_splits_all_input_categories():
    usage = _usage_from_response(_responses_usage())

    assert usage == {
        "non_cached_prompt": 20,
        "completion": 10,
        "cached": 60,
        "cache_write": 20,
    }


def test_chat_conversion_preserves_cache_write_tokens():
    usage = _build_usage(_responses_usage())

    assert usage["prompt_tokens"] == 100
    assert usage["prompt_tokens_details"] == {
        "cached_tokens": 60,
        "cache_write_tokens": 20,
    }
    response = {"usage": usage}
    assert extract_cached_tokens(response) == 60
    assert extract_cache_write_tokens(response) == 20
    assert extract_cache_write_tokens_from_chunk(response) == 20


class _CaptureTasks:
    def create_task(self, coro, task_name="background_task"):
        coro.close()


def _capture_record_usage(captured):
    def fake_record_usage(**kwargs):
        captured.append(kwargs)

        async def complete():
            return None

        return complete()

    return fake_record_usage


def _token() -> APIToken:
    return cast(APIToken, SimpleNamespace(id=uuid4(), user_id=uuid4()))


def _chat_usage_chunk():
    usage = _build_usage(_responses_usage())
    return f"data: {json.dumps({'usage': usage, 'choices': []})}\n\n"


def _responses_completed_event():
    event = {
        "type": "response.completed",
        "response": {"usage": _responses_usage()},
    }
    return f"data: {json.dumps(event)}\n\n".encode()


@pytest.mark.asyncio
async def test_openai_chat_mantle_stream_records_all_cache_categories():
    async def stream(_payload):
        yield _chat_usage_chunk()

    recorded = []
    with (
        patch.object(chat.MantleClient, "invoke_stream", stream),
        patch.object(chat, "record_usage", _capture_record_usage(recorded)),
        patch.object(chat, "background_tasks", _CaptureTasks()),
    ):
        async for _ in chat.stream_mantle_completion(
            payload={},
            request_id="req-chat-cache",
            model="openai.gpt-5.6",
            token=_token(),
            start_time=0.0,
        ):
            pass

    assert recorded[0]["prompt_tokens"] == 20
    assert recorded[0]["cache_creation_input_tokens"] == 20
    assert recorded[0]["cache_read_input_tokens"] == 60


@pytest.mark.asyncio
async def test_anthropic_mantle_stream_records_all_cache_categories():
    async def stream(_payload):
        yield _chat_usage_chunk()

    recorded = []
    with (
        patch.object(MantleClient, "invoke_stream", stream),
        patch.object(messages, "record_usage", _capture_record_usage(recorded)),
        patch.object(messages, "background_tasks", _CaptureTasks()),
    ):
        async for _ in messages._stream_mantle_as_anthropic(
            payload={},
            request_id="req-anthropic-cache",
            model="openai.gpt-5.6",
            token=_token(),
            start_time=0.0,
        ):
            pass

    assert recorded[0]["prompt_tokens"] == 20
    assert recorded[0]["cache_creation_input_tokens"] == 20
    assert recorded[0]["cache_read_input_tokens"] == 60


@pytest.mark.asyncio
async def test_native_responses_stream_records_all_cache_categories():
    async def stream(_body):
        yield _responses_completed_event()

    recorded = []
    with (
        patch.object(responses.MantleClient, "responses_passthrough_stream", stream),
        patch.object(responses, "record_usage", _capture_record_usage(recorded)),
        patch.object(responses, "background_tasks", _CaptureTasks()),
    ):
        async for _ in responses._stream_responses(
            body={},
            request_id="req-responses-cache",
            model="openai.gpt-5.6",
            token=_token(),
            start_time=0.0,
        ):
            pass

    assert recorded[0]["prompt_tokens"] == 20
    assert recorded[0]["cache_creation_input_tokens"] == 20
    assert recorded[0]["cache_read_input_tokens"] == 60

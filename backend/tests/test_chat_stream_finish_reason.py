"""Regression test: Converse streams still emit a finish_reason chunk.

The runtime backend routes non-Anthropic models (e.g. openai.gpt-5.6-sol)
through the Converse API. Converse's ``messageStop`` is normalized to a
``message_delta`` event — it never produces a ``message_stop`` event. The chat
streaming generator used to emit the OpenAI ``finish_reason`` chunk only on
``message_stop``, so Converse streams ended without one and clients like pi
errored with "Stream ended without finish_reason".
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.endpoints import chat as chat_module
from app.schemas.bedrock import BedrockStreamEvent, BedrockUsage


def _converse_events():
    """Events as _converse_stream_event_to_bedrock would emit them.

    Note the absence of any ``message_stop`` event and the trailing
    metadata-as-message_delta (delta=None) that must not clobber stop_reason.
    """
    return [
        BedrockStreamEvent(type="message_start", message={"role": "assistant"}),
        BedrockStreamEvent(
            type="content_block_start", index=0, content_block={"type": "text"}
        ),
        BedrockStreamEvent(
            type="content_block_delta", index=0, delta={"text": "Hi hi hi!"}
        ),
        BedrockStreamEvent(type="content_block_stop", index=0),
        BedrockStreamEvent(type="message_delta", delta={"stop_reason": "end_turn"}),
        BedrockStreamEvent(
            type="message_delta",
            usage=BedrockUsage(input_tokens=11, output_tokens=5),
        ),
    ]


async def _collect(events):
    async def _stream(*args, **kwargs):
        for ev in events:
            yield ev

    bedrock_client = MagicMock()
    bedrock_client.invoke_stream = _stream

    token = MagicMock()
    token.id = "tok"
    token.user_id = "usr"

    chunks = []
    with (
        patch.object(chat_module, "emit_request_metrics", new=AsyncMock()),
        patch.object(chat_module.background_tasks, "create_task", new=MagicMock()),
    ):
        async for chunk in chat_module.stream_chat_completion(
            request_id="chatcmpl-test",
            model="openai.gpt-5.6-sol",
            bedrock_request=MagicMock(),
            bedrock_client=bedrock_client,
            token=token,
            start_time=0.0,
        ):
            chunks.append(chunk)
    return chunks


def _finish_reasons(chunks):
    reasons = []
    for raw in chunks:
        for line in raw.splitlines():
            if not line.startswith("data: ") or line.strip() == "data: [DONE]":
                continue
            payload = json.loads(line[len("data: ") :])
            for choice in payload.get("choices", []):
                fr = choice.get("finish_reason")
                if fr is not None:
                    reasons.append(fr)
    return reasons


@pytest.mark.asyncio
async def test_converse_stream_emits_finish_reason():
    chunks = await _collect(_converse_events())
    joined = "".join(chunks)

    assert "data: [DONE]\n\n" in joined
    # Exactly one finish_reason, mapped from the Converse stop_reason
    # "end_turn" to the spec-valid OpenAI value "stop" (clients like pi
    # reject "end_turn"), and not clobbered to null by the trailing
    # metadata-as-message_delta event.
    assert _finish_reasons(chunks) == ["stop"]


@pytest.mark.asyncio
async def test_finish_reason_not_double_emitted_with_message_stop():
    """Anthropic path (native message_stop) must still emit exactly one."""
    events = _converse_events()
    events.append(BedrockStreamEvent(type="message_stop"))
    chunks = await _collect(events)
    assert _finish_reasons(chunks) == ["stop"]

"""Idle upstream streams must still put bytes on the wire.

Regression: a multi-thousand-word tool_use argument made Bedrock go quiet
for 30s+ between input_json_delta chunks. Heartbeats were only checked
when an upstream event arrived, so nothing was sent during the stall and a
60s idle proxy cut the connection (client: "terminated").
"""

import asyncio
import time
from types import SimpleNamespace

import pytest

from app.api.anthropic.endpoints import messages
from app.core.stream_heartbeat import HEARTBEAT, with_heartbeat
from app.schemas.bedrock import BedrockStreamEvent


async def _slow(items, delay):
    for item in items:
        await asyncio.sleep(delay)
        yield item


@pytest.mark.asyncio
async def test_heartbeat_during_idle_and_items_pass_through():
    out = [x async for x in with_heartbeat(_slow([1, 2], 0.25), 0.1)]
    assert [x for x in out if x is not HEARTBEAT] == [1, 2]
    assert out.count(HEARTBEAT) >= 2


@pytest.mark.asyncio
async def test_no_heartbeat_when_upstream_is_busy():
    out = [x async for x in with_heartbeat(_slow(range(5), 0.0), 0.5)]
    assert out == list(range(5))


@pytest.mark.asyncio
async def test_upstream_closed_when_consumer_stops():
    closed = asyncio.Event()

    async def src():
        try:
            yield 1
            await asyncio.sleep(10)
            yield 2
        finally:
            closed.set()

    gen = with_heartbeat(src(), 0.05)
    assert await gen.__anext__() == 1
    assert await gen.__anext__() is HEARTBEAT
    await gen.aclose()
    assert closed.is_set()


@pytest.mark.asyncio
async def test_upstream_errors_propagate():
    async def src():
        yield 1
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        [x async for x in with_heartbeat(src(), 0.05)]


@pytest.mark.asyncio
async def test_anthropic_stream_pings_while_tool_input_stalls(monkeypatch):
    """End to end through stream_anthropic_messages with a stalled tool_use."""
    events = [
        BedrockStreamEvent(type="message_start"),
        BedrockStreamEvent(
            type="content_block_start",
            index=0,
            content_block={"type": "tool_use", "id": "toolu_1", "name": "write"},
        ),
        BedrockStreamEvent(
            type="content_block_delta", index=0, delta={"partial_json": '{"path":'}
        ),
        "STALL",
        BedrockStreamEvent(
            type="content_block_delta", index=0, delta={"partial_json": '"a"}'}
        ),
        BedrockStreamEvent(type="content_block_stop", index=0),
        BedrockStreamEvent(type="message_stop"),
    ]

    class _Client:
        async def invoke_stream(self, *_a, **_k):
            for ev in events:
                if ev == "STALL":
                    await asyncio.sleep(0.5)
                    continue
                yield ev

    monkeypatch.setattr(messages.get_settings(), "STREAM_HEARTBEAT_INTERVAL", 0.1)
    monkeypatch.setattr(messages.background_tasks, "create_task", lambda *a, **k: None)
    token = SimpleNamespace(id="t", user_id="u", name="n")
    out = []
    async for chunk in messages.stream_anthropic_messages(
        request_id="msg_test",
        model="claude",
        bedrock_request=SimpleNamespace(),
        bedrock_client=_Client(),
        token=token,
        start_time=time.time(),
    ):
        out.append(chunk)
    joined = "".join(out)
    stall_start = joined.index('{\\"path\\":')
    stall_end = joined.index('\\"a\\"}')
    assert joined[stall_start:stall_end].count("event: ping") >= 2
    assert "message_stop" in joined

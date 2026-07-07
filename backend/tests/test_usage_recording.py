"""
Tests for usage-recording robustness.

Covers two guarantees that keep recorded usage from silently diverging from
what the upstream provider actually charged:

A. Streaming records usage on *every* exit path — normal completion, client
   disconnect, or a mid-stream error after the provider already produced (and
   billed) tokens — and does so exactly once (idempotent).

B. When pricing is missing for a model, usage is still recorded with
   ``cost_usd=0`` and ``note="pricing_missing"`` instead of being dropped, so
   the tokens stay auditable and the cost can be back-filled later.

All provider/DB access is mocked — no real AWS or database calls.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.bedrock import BedrockStreamEvent, BedrockUsage


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch):
    """Provide the required settings env vars so get_settings() works in CI.

    Settings is a pydantic BaseSettings with DATABASE_URL / JWT_SECRET_KEY as
    required fields; locally a .env satisfies them, but CI has neither. The
    streaming handlers and record_usage call get_settings() (lru_cached), so
    set dummy-but-valid values and clear the cache around each test.
    """
    from app.core.config import get_settings

    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/test"
    )
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 32)  # pragma: allowlist secret
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _message_start(input_tokens=100, cache_read=0, cache_write=0):
    return BedrockStreamEvent(
        type="message_start",
        usage=BedrockUsage(
            input_tokens=input_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_write,
        ),
    )


def _content_delta(text="hi"):
    return BedrockStreamEvent(type="content_block_delta", index=0, delta={"text": text})


def _make_token():
    token = MagicMock()
    token.id = uuid.uuid4()
    token.user_id = uuid.uuid4()
    return token


class _CaptureTasks:
    """Stand-in for BackgroundTaskManager that captures scheduled coroutines."""

    def __init__(self):
        self.calls = []

    def create_task(self, coro, task_name="background_task"):
        self.calls.append((task_name, coro))
        # Close the coroutine so pytest doesn't warn about it never being awaited.
        coro.close()


# ---------------------------------------------------------------------------
# A — streaming records usage on abnormal exit paths, exactly once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_stream_records_usage_on_midstream_error():
    """If Bedrock produces tokens then the stream raises, usage is still recorded."""
    from app.api.v1.endpoints import chat

    async def broken_stream(*args, **kwargs):
        yield _message_start(input_tokens=123)
        yield _content_delta("partial")
        raise RuntimeError("connection dropped mid-stream")

    bedrock_client = MagicMock()
    bedrock_client.invoke_stream = broken_stream

    capture = _CaptureTasks()
    with (
        patch.object(chat, "background_tasks", capture),
        patch.object(chat, "get_fallback_models", return_value=[]),
    ):
        gen = chat.stream_chat_completion(
            request_id="req-err",
            model="global.anthropic.claude-opus-4-8",
            bedrock_request={},
            bedrock_client=bedrock_client,
            token=_make_token(),
            db=MagicMock(),
            start_time=0.0,
        )
        # Drain the generator; the mid-stream error is caught and turned into an
        # SSE error frame, not re-raised.
        async for _ in gen:
            pass

    record_calls = [c for c in capture.calls if c[0] == "record_usage_req-err"]
    assert len(record_calls) == 1, "usage must be recorded exactly once on error path"


@pytest.mark.asyncio
async def test_openai_stream_records_usage_once_on_success():
    """Normal completion records usage exactly once (finally is idempotent)."""
    from app.api.v1.endpoints import chat

    async def good_stream(*args, **kwargs):
        yield _message_start(input_tokens=50)
        yield _content_delta("hello")
        yield BedrockStreamEvent(
            type="message_delta",
            delta={"stop_reason": "end_turn"},
            usage=BedrockUsage(output_tokens=7),
        )
        yield BedrockStreamEvent(type="message_stop")

    bedrock_client = MagicMock()
    bedrock_client.invoke_stream = good_stream

    capture = _CaptureTasks()
    with (
        patch.object(chat, "background_tasks", capture),
        patch.object(chat, "get_fallback_models", return_value=[]),
    ):
        gen = chat.stream_chat_completion(
            request_id="req-ok",
            model="global.anthropic.claude-opus-4-8",
            bedrock_request={},
            bedrock_client=bedrock_client,
            token=_make_token(),
            db=MagicMock(),
            start_time=0.0,
        )
        async for _ in gen:
            pass

    record_calls = [c for c in capture.calls if c[0] == "record_usage_req-ok"]
    assert len(record_calls) == 1, "success path must record exactly once"


@pytest.mark.asyncio
async def test_openai_stream_no_usage_when_nothing_consumed():
    """A failure before any tokens arrive records nothing (matches AWS: no charge)."""
    from app.api.v1.endpoints import chat

    async def empty_then_error(*args, **kwargs):
        raise RuntimeError("failed before message_start")
        yield  # pragma: no cover - makes this an async generator

    bedrock_client = MagicMock()
    bedrock_client.invoke_stream = empty_then_error

    capture = _CaptureTasks()
    with (
        patch.object(chat, "background_tasks", capture),
        patch.object(chat, "get_fallback_models", return_value=[]),
    ):
        gen = chat.stream_chat_completion(
            request_id="req-none",
            model="global.anthropic.claude-opus-4-8",
            bedrock_request={},
            bedrock_client=bedrock_client,
            token=_make_token(),
            db=MagicMock(),
            start_time=0.0,
        )
        async for _ in gen:
            pass

    record_calls = [c for c in capture.calls if c[0] == "record_usage_req-none"]
    assert len(record_calls) == 0, "no tokens consumed → no usage record"


@pytest.mark.asyncio
async def test_anthropic_stream_records_usage_on_midstream_error():
    """Anthropic native path also records usage when the stream aborts mid-way."""
    from app.api.anthropic.endpoints import messages

    async def broken_stream(*args, **kwargs):
        yield _message_start(input_tokens=200)
        raise RuntimeError("boom")

    # The Anthropic path accumulates usage via the translator; make it populate
    # input_tokens from the message_start event like the real translator does.
    def fake_translate(event, model, request_id, accumulated_usage):
        if event.type == "message_start" and event.usage:
            accumulated_usage["input_tokens"] = event.usage.input_tokens or 0
        return []

    bedrock_client = MagicMock()
    bedrock_client.invoke_stream = broken_stream

    capture = _CaptureTasks()
    with (
        patch.object(messages, "background_tasks", capture),
        patch.object(messages, "get_fallback_models", return_value=[]),
        patch.object(
            messages.AnthropicResponseTranslator,
            "bedrock_stream_to_anthropic_events",
            side_effect=fake_translate,
        ),
    ):
        gen = messages.stream_anthropic_messages(
            request_id="req-anthropic",
            model="global.anthropic.claude-opus-4-8",
            bedrock_request={},
            bedrock_client=bedrock_client,
            token=_make_token(),
            db=MagicMock(),
            start_time=0.0,
        )
        async for _ in gen:
            pass

    record_calls = [c for c in capture.calls if c[0] == "record_usage_req-anthropic"]
    assert len(record_calls) == 1, "anthropic path must record once on error"


# ---------------------------------------------------------------------------
# B — missing pricing degrades to cost=0 + note instead of dropping usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_usage_pricing_missing_records_zero_cost():
    """When calculate_cost raises ValueError, a record is still written."""
    from app.api.v1.endpoints import chat

    added = []

    class FakeSession:
        def add(self, obj):
            added.append(obj)

        async def commit(self):
            pass

        async def rollback(self):
            pass

        async def close(self):
            pass

    async def fake_get_db():
        yield FakeSession()

    pricing_instance = MagicMock()
    pricing_instance.calculate_cost = AsyncMock(
        side_effect=ValueError("no pricing row for model")
    )

    with (
        patch.object(chat, "get_db", fake_get_db),
        patch.object(chat, "ModelPricing", return_value=pricing_instance),
        patch("app.services.alert.check_alerts_for_usage", new=AsyncMock()),
    ):
        await chat.record_usage(
            token_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            model="global.anthropic.some-brand-new-model",
            request_id="req-nopricing",
            prompt_tokens=100,
            completion_tokens=20,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )

    assert len(added) == 1, "usage must be recorded even without pricing"
    rec = added[0]
    assert rec.cost_usd == Decimal("0.0000")
    assert rec.note == "pricing_missing"
    assert rec.prompt_tokens == 100
    assert rec.completion_tokens == 20
    assert rec.total_tokens == 120


@pytest.mark.asyncio
async def test_record_usage_normal_pricing_has_no_note():
    """Happy path records the computed cost and leaves note unset."""
    from app.api.v1.endpoints import chat

    added = []

    class FakeSession:
        def add(self, obj):
            added.append(obj)

        async def commit(self):
            pass

        async def rollback(self):
            pass

        async def close(self):
            pass

    async def fake_get_db():
        yield FakeSession()

    pricing_instance = MagicMock()
    pricing_instance.calculate_cost = AsyncMock(return_value=Decimal("0.1234"))

    with (
        patch.object(chat, "get_db", fake_get_db),
        patch.object(chat, "ModelPricing", return_value=pricing_instance),
        patch("app.services.alert.check_alerts_for_usage", new=AsyncMock()),
    ):
        await chat.record_usage(
            token_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            model="global.anthropic.claude-opus-4-8",
            request_id="req-ok",
            prompt_tokens=100,
            completion_tokens=20,
        )

    assert len(added) == 1
    rec = added[0]
    assert rec.cost_usd == Decimal("0.1234")
    assert rec.note is None

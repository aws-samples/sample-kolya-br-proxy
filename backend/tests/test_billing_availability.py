# pyright: reportArgumentType=false, reportAttributeAccessIssue=false
"""Billing and availability fixes from the code review (low-confidence batch).

- a stream aborted before its final usage event is billed from what was
  streamed, not as zero
- the Gemini streaming route validates in a short-lived DB session
- trace records are size-bounded and tracing is off by default
- the metric Path dimension is the route template, never the raw URL
- /admin/auth/revoke rejects non-JWT input before the slow hash
"""

import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.anthropic.endpoints import messages
from app.api.v1.endpoints import chat
from app.schemas.bedrock import BedrockStreamEvent, BedrockUsage
from app.services.stream_usage_estimate import (
    StreamUsageFallback,
    estimate_input_tokens,
    tokens_from_chars,
)

# --- estimator ----------------------------------------------------------


def test_tokens_from_chars_rounds_up():
    assert tokens_from_chars(0) == 0
    assert tokens_from_chars(1) == 1
    assert tokens_from_chars(8) == 2
    assert tokens_from_chars(9) == 3


def test_input_estimate_skips_binary_payloads():
    request = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "x" * 400},
                    {"type": "image", "source": {"data": "A" * 1_000_000}},
                ],
            }
        ],
        "system": "s" * 40,
    }
    # 400 + 40 text chars (+ role/type words), not the 1 MB of base64
    assert 110 <= estimate_input_tokens(request) < 130


def test_fallback_trusts_final_usage():
    fb = StreamUsageFallback()
    fb.add_output("x" * 4000)
    fb.final_usage_seen = True
    assert fb.resolve(10, 20, {"messages": []}) == (10, 20)


def test_fallback_fills_missing_usage():
    fb = StreamUsageFallback()
    fb.add_output("x" * 4000)
    request = {"messages": [{"role": "user", "content": "q" * 400}]}
    inp, out = fb.resolve(0, 0, request)
    assert out == 1000
    assert inp >= 100


def test_fallback_keeps_reported_input():
    fb = StreamUsageFallback()
    fb.add_output("x" * 40)
    assert fb.resolve(500, 0, {"messages": []}) == (500, 10)


# --- streams aborted before the usage event -----------------------------


def _capture(monkeypatch, module):
    calls = []
    monkeypatch.setattr(module, "record_usage", lambda **kw: calls.append(kw))
    monkeypatch.setattr(module.background_tasks, "create_task", lambda *a, **k: None)
    return calls


class _Client:
    def __init__(self, events):
        self.events = events

    async def invoke_stream(self, *_a, **_k):
        for ev in self.events:
            yield ev


_REQUEST = {"messages": [{"role": "user", "content": "q" * 400}]}

# Converse-style: no message_start usage; usage only in trailing metadata.
_CONVERSE_EVENTS = [
    BedrockStreamEvent(type="content_block_start", index=0),
    *[
        BedrockStreamEvent(
            type="content_block_delta", index=0, delta={"text": "x" * 40}
        )
        for _ in range(10)
    ],
    BedrockStreamEvent(type="content_block_stop", index=0),
    BedrockStreamEvent(type="message_delta", delta={"stop_reason": "end_turn"}),
    BedrockStreamEvent(
        type="message_delta",
        usage=BedrockUsage(input_tokens=123, output_tokens=456),
    ),
]


async def _consume_then_disconnect(agen, stop_after):
    seen = 0
    async for chunk in agen:
        if "x" * 40 in chunk:
            seen += 1
            if seen == stop_after:
                break
    await agen.aclose()


@pytest.mark.asyncio
async def test_chat_stream_aborted_before_metadata_is_billed(monkeypatch):
    calls = _capture(monkeypatch, chat)
    agen = chat.stream_chat_completion(
        request_id="r",
        model="m",
        bedrock_request=_REQUEST,
        bedrock_client=_Client(_CONVERSE_EVENTS),
        token=SimpleNamespace(id="t", user_id="u", name="n"),
        start_time=time.time(),
    )
    await _consume_then_disconnect(agen, stop_after=10)
    assert len(calls) == 1
    assert calls[0]["completion_tokens"] >= 100
    assert calls[0]["prompt_tokens"] >= 100


@pytest.mark.asyncio
async def test_chat_stream_completed_uses_reported_usage(monkeypatch):
    calls = _capture(monkeypatch, chat)
    async for _ in chat.stream_chat_completion(
        request_id="r",
        model="m",
        bedrock_request=_REQUEST,
        bedrock_client=_Client(_CONVERSE_EVENTS),
        token=SimpleNamespace(id="t", user_id="u", name="n"),
        start_time=time.time(),
    ):
        pass
    assert (calls[0]["prompt_tokens"], calls[0]["completion_tokens"]) == (123, 456)


@pytest.mark.asyncio
async def test_messages_stream_aborted_before_message_delta_is_billed(monkeypatch):
    calls = _capture(monkeypatch, messages)
    events = [
        BedrockStreamEvent(
            type="message_start", usage=BedrockUsage(input_tokens=200, output_tokens=0)
        ),
        BedrockStreamEvent(
            type="content_block_start", index=0, content_block={"type": "text"}
        ),
        *[
            BedrockStreamEvent(
                type="content_block_delta", index=0, delta={"text": "x" * 40}
            )
            for _ in range(10)
        ],
        BedrockStreamEvent(
            type="message_delta",
            delta={"stop_reason": "end_turn"},
            usage=BedrockUsage(output_tokens=999),
        ),
    ]
    agen = messages.stream_anthropic_messages(
        request_id="r",
        model="m",
        bedrock_request=_REQUEST,
        bedrock_client=_Client(events),
        token=SimpleNamespace(id="t", user_id="u", name="n"),
        start_time=time.time(),
    )
    await _consume_then_disconnect(agen, stop_after=10)
    assert len(calls) == 1
    assert calls[0]["prompt_tokens"] == 200  # reported at message_start
    assert calls[0]["completion_tokens"] >= 100  # estimated, not 0


# --- Gemini streaming uses a short-lived session -------------------------


def test_gemini_stream_route_has_no_request_scoped_db():
    import inspect

    from app.api import deps
    from app.api.gemini.endpoints import generate

    params = inspect.signature(generate.stream_generate_content).parameters
    assert "db" not in params
    assert (
        params["token"].default.dependency
        is deps.get_current_token_from_gemini_key_streaming
    )


# --- trace store bounds ----------------------------------------------------


def test_tracing_off_by_default():
    from app.core.config import Settings

    assert Settings.model_fields["TRACE_ENABLED"].default is False


def test_trace_record_fields_are_truncated():
    from app.services import trace_store as ts

    store = ts.TraceStore()
    store.add(
        ts.TraceRecord(
            request_id="r",
            timestamp=1,
            model="m",
            token_id="t",
            messages=[
                {"content": "y" * (ts.MAX_FIELD_CHARS * 4)},
                {"source": {"data": "A" * 500_000}},
            ],
        )
    )
    rec = store.get("r")
    assert len(rec["messages"][0]["content"]) < ts.MAX_FIELD_CHARS + 100
    assert rec["messages"][1]["source"]["data"] == "[500000 bytes omitted]"


def test_trace_store_evicts_by_total_size():
    from app.services import trace_store as ts

    store = ts.TraceStore(max_size=1000, max_total_chars=50_000)
    for i in range(20):
        store.add(
            ts.TraceRecord(
                request_id=f"r{i}",
                timestamp=i,
                model="m",
                token_id="t",
                messages=[{"content": "z" * 10_000}],
            )
        )
    assert store.size <= 5
    assert store.get("r19") is not None
    assert store.get("r0") is None


# --- metric path dimension -------------------------------------------------


def test_metric_path_uses_route_template():
    from app.middleware.observability import UNMATCHED_PATH, metric_path

    route = SimpleNamespace(path_format="/v1beta/models/{model_path:path}")
    assert metric_path({"route": route, "path": "/v1beta/models/x/y"}) == (
        "/v1beta/models/{model_path:path}"
    )
    assert metric_path({"path": "/random-1234"}) == UNMATCHED_PATH


# --- /admin/auth/revoke ----------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_rejects_junk_before_hashing(monkeypatch):
    from app.api.admin.endpoints import auth
    from app.core import security

    def _boom(_t):
        raise AssertionError("hashed a non-JWT credential")

    monkeypatch.setattr(security, "hash_refresh_token", _boom)
    monkeypatch.setattr(auth, "_presented_refresh_credential", lambda *_a: "junk")
    with pytest.raises(HTTPException) as exc_info:
        await auth.revoke_refresh_token(
            http_request=SimpleNamespace(),
            response=SimpleNamespace(),
            request_body=None,
            refresh_token_service=None,
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_revoke_rejects_access_token_type(monkeypatch):
    from app.api.admin.endpoints import auth
    from app.core.security import create_access_token

    monkeypatch.setattr(
        auth,
        "_presented_refresh_credential",
        lambda *_a: create_access_token({"sub": "u"}),
    )
    with pytest.raises(HTTPException) as exc_info:
        await auth.revoke_refresh_token(
            http_request=SimpleNamespace(),
            response=SimpleNamespace(),
            request_body=None,
            refresh_token_service=None,
        )
    assert exc_info.value.status_code == 401

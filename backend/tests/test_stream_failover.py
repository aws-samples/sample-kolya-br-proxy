"""
Tests for two-level stream failover.

Level 1: same model, different region (cross-region profiles).
Level 2: model degradation to a fallback model.

All tests mock the Bedrock streaming layer — no real AWS calls.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.bedrock import BedrockContentBlock, BedrockStreamEvent, BedrockRequest
from app.services.bedrock import (
    BedrockClient,
    FirstContentTimeoutError,
    _ProfileCache,
    get_fallback_models,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _msg_start_bytes() -> dict:
    """Simulate a message_start chunk from Bedrock InvokeModelWithResponseStream."""
    return {
        "chunk": {
            "bytes": json.dumps({
                "type": "message_start",
                "message": {"id": "msg_1", "role": "assistant", "model": "test"},
            }).encode()
        }
    }


def _content_delta_bytes(text: str = "Hello") -> dict:
    """Simulate a content_block_delta chunk with text."""
    return {
        "chunk": {
            "bytes": json.dumps({
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": text},
            }).encode()
        }
    }


def _content_block_start_bytes() -> dict:
    """Simulate a content_block_start chunk."""
    return {
        "chunk": {
            "bytes": json.dumps({
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            }).encode()
        }
    }


def _msg_stop_bytes() -> dict:
    """Simulate a message_stop chunk."""
    return {"chunk": {"bytes": json.dumps({"type": "message_stop"}).encode()}}


async def _make_normal_stream():
    """Async generator that yields a complete, healthy stream."""
    yield _msg_start_bytes()
    yield _content_block_start_bytes()
    yield _content_delta_bytes("Hello world")
    yield _msg_stop_bytes()


async def _make_hanging_stream():
    """Async generator that yields message_start then hangs forever."""
    yield _msg_start_bytes()
    yield _content_block_start_bytes()
    # Simulate indefinite hang — no content arrives
    await asyncio.sleep(999)


async def _make_empty_stream():
    """Async generator that yields ZERO events — stream started but nothing comes."""
    # Real-world scenario: Bedrock accepts connection but sends nothing
    await asyncio.sleep(999)
    # yield is needed to make this an async generator (never reached)
    yield  # pragma: no cover


def _make_bedrock_request() -> BedrockRequest:
    return BedrockRequest(
        messages=[{"role": "user", "content": "Hi"}],
        max_tokens=100,
    )


# ---------------------------------------------------------------------------
# Mock factory for BedrockClient
# ---------------------------------------------------------------------------

def _build_mock_client(stream_factory):
    """Build a mock bedrock-runtime client that returns the given stream."""
    mock_client = AsyncMock()
    mock_client.invoke_model_with_response_stream = AsyncMock(
        return_value={"body": stream_factory()}
    )
    return mock_client


@asynccontextmanager
async def _mock_session_client(clients_by_region: dict):
    """Context manager that returns different mock clients based on region."""
    # We need to make __aenter__ return the mock client
    # This will be used as: async with self.session.client(..., region_name=r) as client:
    pass  # Placeholder — see _patch_bedrock_client below


def _patch_bedrock_client(
    bc: BedrockClient,
    primary_model_id: str,
    primary_region: str,
    alternative_profiles: list[str],
    stream_factories: dict[str, callable],
    fallback_models_resolution: dict[str, tuple[str, str]] | None = None,
):
    """Patch a BedrockClient instance for testing.

    Args:
        bc: BedrockClient instance.
        primary_model_id: What resolve_model returns for the primary model.
        primary_region: Region for the primary model.
        alternative_profiles: What get_alternative_profiles returns.
        stream_factories: model_id → async generator factory for the stream.
        fallback_models_resolution: fallback_name → (model_id, region).
    """
    fallback_models_resolution = fallback_models_resolution or {}

    def mock_resolve_model(model_name):
        if model_name in fallback_models_resolution:
            return fallback_models_resolution[model_name]
        return primary_model_id, primary_region

    bc.resolve_model = mock_resolve_model
    bc.is_anthropic_model = staticmethod(lambda mid: True)
    bc._profile_cache.get_alternative_profiles = lambda mid: alternative_profiles

    # Mock the session.client context manager
    @asynccontextmanager
    async def mock_client_cm(*args, **kwargs):
        mock_cl = AsyncMock()

        # We figure out the model_id from the invoke call — but we need to
        # return the right stream. Use a side_effect that captures the call.
        async def mock_invoke(**invoke_kwargs):
            mid = invoke_kwargs.get("modelId", primary_model_id)
            factory = stream_factories.get(mid, _make_normal_stream)
            return {"body": factory()}

        mock_cl.invoke_model_with_response_stream = mock_invoke
        yield mock_cl

    bc.session = MagicMock()
    bc.session.client = mock_client_cm

    # Mock build helpers to be pass-through
    bc._build_anthropic_body = lambda req: {"messages": [], "max_tokens": 100}
    bc._build_invoke_kwargs = staticmethod(
        lambda req, mid: {"modelId": mid, "contentType": "application/json", "accept": "application/json"}
    )


# ======================================================================
# Unit tests: _is_content_event
# ======================================================================


class TestIsContentEvent:
    def test_text_delta(self):
        event = BedrockStreamEvent(
            type="content_block_delta", delta={"text": "hello"}
        )
        assert BedrockClient._is_content_event(event) is True

    def test_partial_json_delta(self):
        event = BedrockStreamEvent(
            type="content_block_delta", delta={"partial_json": '{"key":'}
        )
        assert BedrockClient._is_content_event(event) is True

    def test_thinking_delta(self):
        event = BedrockStreamEvent(
            type="content_block_delta", delta={"thinking": "Let me think..."}
        )
        assert BedrockClient._is_content_event(event) is True

    def test_message_start_not_content(self):
        event = BedrockStreamEvent(
            type="message_start", message={"role": "assistant"}
        )
        assert BedrockClient._is_content_event(event) is False

    def test_content_block_start_not_content(self):
        event = BedrockStreamEvent(
            type="content_block_start",
            index=0,
            content_block=BedrockContentBlock(type="text"),
        )
        assert BedrockClient._is_content_event(event) is False

    def test_message_stop_not_content(self):
        event = BedrockStreamEvent(type="message_stop")
        assert BedrockClient._is_content_event(event) is False

    def test_empty_delta_not_content(self):
        event = BedrockStreamEvent(type="content_block_delta", delta={})
        assert BedrockClient._is_content_event(event) is False


# ======================================================================
# Unit tests: _ProfileCache.get_alternative_profiles
# ======================================================================


class TestGetAlternativeProfiles:
    def _make_cache(self, profile_ids: list[str]) -> _ProfileCache:
        cache = _ProfileCache()
        cache._local_profile_ids = set(profile_ids)
        # Build _all_profiles_by_bare manually
        all_by_bare: dict[str, list[tuple[int, str]]] = {}
        for pid in profile_ids:
            bare = pid
            pfx_str = ""
            for pfx in BedrockClient.INFERENCE_PROFILE_PREFIXES:
                if pid.startswith(pfx):
                    bare = pid[len(pfx):]
                    pfx_str = pfx
                    break
            prio = cache._GEO_PRIORITY.get(pfx_str, 5)
            all_by_bare.setdefault(bare, []).append((prio, pid))
        cache._all_profiles_by_bare = {
            k: [pid for _, pid in sorted(v)] for k, v in all_by_bare.items()
        }
        return cache

    def test_returns_alternatives_excluding_self(self):
        profiles = [
            "us.anthropic.claude-sonnet-4-20250514-v1:0",
            "eu.anthropic.claude-sonnet-4-20250514-v1:0",
            "apac.anthropic.claude-sonnet-4-20250514-v1:0",
        ]
        cache = self._make_cache(profiles)
        alts = cache.get_alternative_profiles("us.anthropic.claude-sonnet-4-20250514-v1:0")
        assert "us.anthropic.claude-sonnet-4-20250514-v1:0" not in alts
        assert "eu.anthropic.claude-sonnet-4-20250514-v1:0" in alts
        assert "apac.anthropic.claude-sonnet-4-20250514-v1:0" in alts

    def test_sorted_by_geo_priority(self):
        profiles = [
            "global.anthropic.claude-sonnet-4-20250514-v1:0",
            "eu.anthropic.claude-sonnet-4-20250514-v1:0",
            "us.anthropic.claude-sonnet-4-20250514-v1:0",
        ]
        cache = self._make_cache(profiles)
        alts = cache.get_alternative_profiles("us.anthropic.claude-sonnet-4-20250514-v1:0")
        # eu (priority 1) before global (priority 10)
        assert alts == [
            "eu.anthropic.claude-sonnet-4-20250514-v1:0",
            "global.anthropic.claude-sonnet-4-20250514-v1:0",
        ]

    def test_no_alternatives(self):
        profiles = ["us.anthropic.claude-sonnet-4-20250514-v1:0"]
        cache = self._make_cache(profiles)
        alts = cache.get_alternative_profiles("us.anthropic.claude-sonnet-4-20250514-v1:0")
        assert alts == []

    def test_unknown_model(self):
        cache = self._make_cache([])
        alts = cache.get_alternative_profiles("unknown-model")
        assert alts == []


# ======================================================================
# Unit tests: get_fallback_models
# ======================================================================


class TestGetFallbackModels:
    def test_returns_filtered_chain(self):
        with patch("app.services.bedrock.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                STREAM_MODEL_FALLBACK_CHAIN="model-a,model-b,model-c"
            )
            result = get_fallback_models(
                allowed_model_names=["model-a", "model-c", "model-d"],
                primary_model="model-a",
            )
            # model-a excluded (primary), model-b not allowed
            assert result == ["model-c"]

    def test_empty_chain(self):
        with patch("app.services.bedrock.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(STREAM_MODEL_FALLBACK_CHAIN="")
            result = get_fallback_models(["model-a"], "model-a")
            assert result is None

    def test_no_valid_fallbacks(self):
        with patch("app.services.bedrock.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                STREAM_MODEL_FALLBACK_CHAIN="model-x,model-y"
            )
            result = get_fallback_models(["model-a"], "model-a")
            assert result is None


# ======================================================================
# Integration tests: stream failover
# ======================================================================

def _mock_settings(**overrides):
    defaults = {
        "STREAM_FIRST_CONTENT_TIMEOUT": 1,  # 1 second for fast tests
        "STREAM_MODEL_FALLBACK_CHAIN": "",
        "AWS_REGION": "us-east-1",
        "BEDROCK_MAX_CONCURRENT_REQUESTS": 10,
        "BEDROCK_ACCOUNT_RPM": 1000,
        "BEDROCK_EXPECTED_PODS": 1,
        "BEDROCK_RATE_BURST": 10,
        "REDIS_URL": "",
        "JWT_SECRET_KEY": "test-secret",
        "PROMPT_CACHE_AUTO_INJECT": False,
        "PROMPT_CACHE_TTL": "5m",
    }
    defaults.update(overrides)

    class FakeSettings:
        pass

    s = FakeSettings()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


@pytest.fixture
def bedrock_client():
    """Create a BedrockClient with mocked internals."""
    with patch("app.services.bedrock.get_settings", return_value=_mock_settings()):
        bc = BedrockClient.__new__(BedrockClient)
        bc.session = MagicMock()
        bc.region_name = "us-east-1"
        bc.config = MagicMock()
        bc._profile_cache = _ProfileCache()
        bc._semaphore = asyncio.Semaphore(10)

        # Simple rate limiter mock
        rate_limiter = AsyncMock()
        rate_limiter.acquire = AsyncMock()
        bc._rate_limiter = rate_limiter

        yield bc


@pytest.mark.asyncio
async def test_no_failover_when_content_arrives(bedrock_client):
    """Primary returns content within timeout — no failover attempted."""
    bc = bedrock_client

    _patch_bedrock_client(
        bc,
        primary_model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
        primary_region="us-east-1",
        alternative_profiles=["eu.anthropic.claude-sonnet-4-20250514-v1:0"],
        stream_factories={
            "us.anthropic.claude-sonnet-4-20250514-v1:0": _make_normal_stream,
        },
    )

    events = []
    with patch("app.services.bedrock.get_settings", return_value=_mock_settings()):
        async for event in bc.invoke_stream(
            "us.anthropic.claude-sonnet-4-20250514-v1:0",
            _make_bedrock_request(),
        ):
            events.append(event)

    assert len(events) >= 2  # message_start + content_block_delta + ...
    # No actual_model set (no degradation)
    assert all(e.actual_model is None for e in events)


@pytest.mark.asyncio
async def test_level1_cross_region_failover(bedrock_client):
    """Primary region hangs; L1 failover to EU succeeds."""
    bc = bedrock_client

    _patch_bedrock_client(
        bc,
        primary_model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
        primary_region="us-east-1",
        alternative_profiles=["eu.anthropic.claude-sonnet-4-20250514-v1:0"],
        stream_factories={
            "us.anthropic.claude-sonnet-4-20250514-v1:0": _make_hanging_stream,
            "eu.anthropic.claude-sonnet-4-20250514-v1:0": _make_normal_stream,
        },
    )

    events = []
    with patch("app.services.bedrock.get_settings", return_value=_mock_settings()):
        async for event in bc.invoke_stream(
            "us.anthropic.claude-sonnet-4-20250514-v1:0",
            _make_bedrock_request(),
        ):
            events.append(event)

    # Should have received events from the EU stream
    assert len(events) >= 2
    # No actual_model set (L1 is transparent — same model, different region)
    assert all(e.actual_model is None for e in events)


@pytest.mark.asyncio
async def test_level2_model_degradation(bedrock_client):
    """All regions for primary timeout; L2 fallback model succeeds."""
    bc = bedrock_client

    fallback_mid = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

    _patch_bedrock_client(
        bc,
        primary_model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
        primary_region="us-east-1",
        alternative_profiles=["eu.anthropic.claude-sonnet-4-20250514-v1:0"],
        stream_factories={
            "us.anthropic.claude-sonnet-4-20250514-v1:0": _make_hanging_stream,
            "eu.anthropic.claude-sonnet-4-20250514-v1:0": _make_hanging_stream,
            fallback_mid: _make_normal_stream,
        },
        fallback_models_resolution={
            "anthropic.claude-haiku-4-5-20251001-v1:0": (fallback_mid, "us-east-1"),
        },
    )

    events = []
    with patch("app.services.bedrock.get_settings", return_value=_mock_settings()):
        async for event in bc.invoke_stream(
            "us.anthropic.claude-sonnet-4-20250514-v1:0",
            _make_bedrock_request(),
            fallback_models=["anthropic.claude-haiku-4-5-20251001-v1:0"],
        ):
            events.append(event)

    # Should have events from the fallback model
    assert len(events) >= 2
    # First event should have actual_model set (L2 degradation)
    assert events[0].actual_model == fallback_mid


@pytest.mark.asyncio
async def test_all_targets_exhausted(bedrock_client):
    """All targets timeout — raises FirstContentTimeoutError."""
    bc = bedrock_client

    _patch_bedrock_client(
        bc,
        primary_model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
        primary_region="us-east-1",
        alternative_profiles=["eu.anthropic.claude-sonnet-4-20250514-v1:0"],
        stream_factories={
            "us.anthropic.claude-sonnet-4-20250514-v1:0": _make_hanging_stream,
            "eu.anthropic.claude-sonnet-4-20250514-v1:0": _make_hanging_stream,
        },
    )

    with pytest.raises(FirstContentTimeoutError):
        with patch("app.services.bedrock.get_settings", return_value=_mock_settings()):
            async for _ in bc.invoke_stream(
                "us.anthropic.claude-sonnet-4-20250514-v1:0",
                _make_bedrock_request(),
            ):
                pass


@pytest.mark.asyncio
async def test_validation_error_no_failover(bedrock_client):
    """ValidationException raises immediately without trying other targets."""
    from botocore.exceptions import ClientError

    bc = bedrock_client

    async def _raise_validation():
        raise ClientError(
            {"Error": {"Code": "ValidationException", "Message": "Bad request"}},
            "InvokeModelWithResponseStream",
        )
        yield  # make it a generator  # noqa: E305

    _patch_bedrock_client(
        bc,
        primary_model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
        primary_region="us-east-1",
        alternative_profiles=["eu.anthropic.claude-sonnet-4-20250514-v1:0"],
        stream_factories={
            "us.anthropic.claude-sonnet-4-20250514-v1:0": _raise_validation,
            "eu.anthropic.claude-sonnet-4-20250514-v1:0": _make_normal_stream,
        },
    )

    with pytest.raises(ClientError) as exc_info:
        with patch("app.services.bedrock.get_settings", return_value=_mock_settings()):
            async for _ in bc.invoke_stream(
                "us.anthropic.claude-sonnet-4-20250514-v1:0",
                _make_bedrock_request(),
            ):
                pass
    assert "ValidationException" in str(exc_info.value)


@pytest.mark.asyncio
async def test_failover_disabled(bedrock_client):
    """When STREAM_FIRST_CONTENT_TIMEOUT=0, uses original _invoke_stream_inner."""
    bc = bedrock_client

    # Mock _invoke_stream_inner to verify it's called
    events_from_inner = [
        BedrockStreamEvent(type="message_start", message={"role": "assistant"}),
        BedrockStreamEvent(type="content_block_delta", delta={"text": "test"}),
    ]

    async def mock_inner(model_name, request):
        for e in events_from_inner:
            yield e

    bc._invoke_stream_inner = mock_inner

    events = []
    settings = _mock_settings(STREAM_FIRST_CONTENT_TIMEOUT=0)
    with patch("app.services.bedrock.get_settings", return_value=settings):
        async for event in bc.invoke_stream(
            "test-model", _make_bedrock_request()
        ):
            events.append(event)

    assert len(events) == 2
    assert events[0].type == "message_start"
    assert events[1].type == "content_block_delta"


@pytest.mark.asyncio
async def test_throttling_error_triggers_failover(bedrock_client):
    """ThrottlingException triggers failover to next target."""
    from botocore.exceptions import ClientError

    bc = bedrock_client

    async def _raise_throttling():
        raise ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            "InvokeModelWithResponseStream",
        )
        yield  # noqa: E305

    _patch_bedrock_client(
        bc,
        primary_model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
        primary_region="us-east-1",
        alternative_profiles=["eu.anthropic.claude-sonnet-4-20250514-v1:0"],
        stream_factories={
            "us.anthropic.claude-sonnet-4-20250514-v1:0": _raise_throttling,
            "eu.anthropic.claude-sonnet-4-20250514-v1:0": _make_normal_stream,
        },
    )

    events = []
    with patch("app.services.bedrock.get_settings", return_value=_mock_settings()):
        async for event in bc.invoke_stream(
            "us.anthropic.claude-sonnet-4-20250514-v1:0",
            _make_bedrock_request(),
        ):
            events.append(event)

    assert len(events) >= 2


@pytest.mark.asyncio
async def test_zero_events_stream_triggers_failover(bedrock_client):
    """Stream starts but yields ZERO events — should timeout and failover.

    This is the most common real-world scenario: Bedrock accepts the
    connection but never sends any data (not even message_start).
    """
    bc = bedrock_client

    _patch_bedrock_client(
        bc,
        primary_model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
        primary_region="us-east-1",
        alternative_profiles=["eu.anthropic.claude-sonnet-4-20250514-v1:0"],
        stream_factories={
            "us.anthropic.claude-sonnet-4-20250514-v1:0": _make_empty_stream,
            "eu.anthropic.claude-sonnet-4-20250514-v1:0": _make_normal_stream,
        },
    )

    events = []
    with patch("app.services.bedrock.get_settings", return_value=_mock_settings()):
        async for event in bc.invoke_stream(
            "us.anthropic.claude-sonnet-4-20250514-v1:0",
            _make_bedrock_request(),
        ):
            events.append(event)

    # Should have received events from EU stream after primary timeout
    assert len(events) >= 2
    assert all(e.actual_model is None for e in events)

"""Ultrafast service tier: validation, Mantle region pinning, and billing."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import mantle_client, mantle_models
from app.services.mantle_client import (
    MantleClient,
    ServiceTierValidationError,
    _openai_to_responses,
    validate_responses_cache_markers,
)
from app.services.openai_gpt_catalog import resolve_gpt_route
from app.services.pricing import ModelPricing, get_official_profile_pricing

MILLION = Decimal(1_000_000)


def _d(*values):
    return tuple(Decimal(v).normalize() for v in values)


def _per_million(rates):
    return tuple(
        (v * MILLION).normalize()
        for v in (rates.input, rates.cache_write, rates.cache_read, rates.output)
    )


@pytest.mark.parametrize(
    ("model_id", "short", "long"),
    [
        # GPT-6.1 Sol Ultrafast table (model card)
        (
            "openai.gpt-6.1-sol",
            _d("13.20", "16.50", "0.66", "66"),
            _d("26.40", "33", "1.32", "99"),
        ),
        (
            "us.openai.gpt-6.1-sol",
            _d("13.20", "16.50", "0.66", "66"),
            _d("26.40", "33", "1.32", "99"),
        ),
        (
            "global.openai.gpt-6.1-sol",
            _d("12", "15", "0.60", "60"),
            _d("24", "30", "1.20", "90"),
        ),
        # GPT-6 Astra Ultrafast table (model card)
        (
            "openai.gpt-6-astra",
            _d("66", "82.50", "6.60", "330"),
            _d("132", "165", "13.20", "495"),
        ),
        (
            "global.openai.gpt-6-astra",
            _d("60", "75", "6", "300"),
            _d("120", "150", "12", "450"),
        ),
    ],
)
def test_ultrafast_rates_match_model_card(model_id, short, long):
    pricing = get_official_profile_pricing(model_id, "ultrafast")

    assert _per_million(pricing.short) == short
    assert _per_million(pricing.long) == long


def test_other_tiers_and_models_bill_standard():
    standard = get_official_profile_pricing("openai.gpt-6.1-sol")
    assert get_official_profile_pricing("openai.gpt-6.1-sol", "default") is standard
    assert get_official_profile_pricing("openai.gpt-6.1-sol", None) is standard
    assert resolve_gpt_route("openai.gpt-6-sol").ultrafast_pricing is None


@pytest.mark.asyncio
async def test_calculate_cost_uses_ultrafast_rates():
    cost = await ModelPricing().calculate_cost(
        model="global.openai.gpt-6.1-sol",
        prompt_tokens=1_000,
        completion_tokens=100,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=2_000,
        service_tier="ultrafast",
    )
    expected = (
        Decimal(1_000) * Decimal("12")
        + Decimal(100) * Decimal("60")
        + Decimal(2_000) * Decimal("0.60")
    ) / MILLION
    assert cost == expected


def test_ultrafast_is_rejected_where_unsupported():
    payload = {
        "model": "openai.gpt-6-sol",
        "service_tier": "ultrafast",
        "messages": [{"role": "user", "content": "hi"}],
    }
    with pytest.raises(ServiceTierValidationError, match="ultrafast"):
        validate_responses_cache_markers(payload)


def test_service_tier_is_forwarded_to_responses():
    body = _openai_to_responses(
        {
            "model": "us.openai.gpt-6.1-sol",
            "service_tier": "ultrafast",
            "messages": [{"role": "user", "content": "hi"}],
        }
    )
    assert body["service_tier"] == "ultrafast"


def test_canonical_ultrafast_is_pinned_to_supported_mantle_region(monkeypatch):
    settings = SimpleNamespace(AWS_REGION="us-west-2", MANTLE_SIGV4_SERVICE="bedrock")
    monkeypatch.setattr(mantle_client, "get_settings", lambda: settings)
    monkeypatch.setattr(mantle_models, "get_settings", lambda: settings)
    monkeypatch.setattr(
        mantle_models,
        "_model_regions",
        {
            **mantle_models._model_regions,
            "openai.gpt-6-astra": ["us-east-1", "us-west-2"],
        },
    )

    standard = MantleClient._endpoint("openai.gpt-6-astra")
    ultrafast = MantleClient._endpoint("openai.gpt-6-astra", "ultrafast")

    assert standard.region == "us-west-2"
    assert ultrafast.region == "us-east-1"
    assert "bedrock-mantle.us-east-1" in ultrafast.url


@pytest.mark.asyncio
async def test_chat_bills_the_tier_aws_reports():
    from app.api.v1.endpoints import chat as chat_module
    from app.schemas.openai import ChatCompletionRequest

    request = ChatCompletionRequest.model_validate(
        {
            "model": "us.openai.gpt-6.1-sol",
            "service_tier": "ultrafast",
            "messages": [{"role": "user", "content": "hi"}],
        }
    )
    response = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        "service_tier": "ultrafast",
    }
    record = MagicMock()
    with (
        patch.object(
            chat_module.MantleClient, "invoke", new=AsyncMock(return_value=response)
        ),
        patch.object(chat_module, "record_usage", new=record),
        patch.object(chat_module.background_tasks, "create_task"),
    ):
        await chat_module._handle_mantle_request(
            request_data=request,
            request_id="req",
            token=SimpleNamespace(id="tok", user_id="usr"),
            start_time=0.0,
        )

    assert record.call_args.kwargs["service_tier"] == "ultrafast"

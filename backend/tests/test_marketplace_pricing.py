"""Marketplace-sold models are priced from the AmazonBedrockFoundationModels
offer, as a gap filler only."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.pricing_updater import PricingUpdater


def _product(sku, model, provider, inference, usagetype, region="us-west-2"):
    return sku, {
        "attributes": {
            "model": model,
            "provider": provider,
            "regionCode": region,
            "feature": "On-demand Inference",
            "inferenceType": inference,
            "usagetype": usagetype,
        }
    }


def _term(price):
    return {
        "t": {
            "priceDimensions": {
                "d": {"pricePerUnit": {"USD": price}, "unit": "1M tokens"}
            }
        }
    }


OFFER = {
    "products": dict(
        [
            _product(
                "p4i",
                "Palmyra X4",
                "Writer",
                "Input tokens",
                "USW2-MP:USW2_InputTokenCount-Units",
            ),
            _product(
                "p4o",
                "Palmyra X4",
                "Writer",
                "Output tokens",
                "USW2-MP:USW2_OutputTokenCount-Units",
            ),
            _product(
                "gi",
                "OpenAI GPT-5.5",
                "OpenAI",
                "Input tokens",
                "USW2-MP:USW2_input_tokens_standard-Units",
            ),
            _product(
                "go",
                "OpenAI GPT-5.5",
                "OpenAI",
                "Output tokens",
                "USW2-MP:USW2_output_tokens_standard-Units",
            ),
            _product(
                "ci",
                "Claude Opus 4.5",
                "Anthropic",
                "Input tokens",
                "USW2-MP:USW2_InputTokenCount-Units",
            ),
            _product(
                "co",
                "Claude Opus 4.5",
                "Anthropic",
                "Output tokens",
                "USW2-MP:USW2_OutputTokenCount-Units",
            ),
            _product(
                "li",
                "Palmyra X4",
                "Writer",
                "Input tokens",
                "USW2-MP:USW2_input_tokens_long_ctx-Units",
            ),
            _product(
                "ei",
                "Palmyra X5",
                "Writer",
                "Input tokens",
                "USE1-MP:USE1_InputTokenCount-Units",
                region="us-east-1",
            ),
            _product(
                "eo",
                "Palmyra X5",
                "Writer",
                "Output tokens",
                "USE1-MP:USE1_OutputTokenCount-Units",
                region="us-east-1",
            ),
        ]
    ),
    "terms": {
        "OnDemand": {
            "p4i": _term("2.50"),
            "p4o": _term("10.00"),
            "gi": _term("5.50"),
            "go": _term("33.00"),
            "ci": _term("5.50"),
            "co": _term("27.50"),
            "li": _term("99.00"),
            "ei": _term("0.60"),
            "eo": _term("6.00"),
        }
    },
}


async def _rows():
    settings = MagicMock(AWS_REGION="us-west-2")
    response = MagicMock(json=lambda: OFFER, raise_for_status=lambda: None)
    client = MagicMock(get=AsyncMock(return_value=response))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    updater = PricingUpdater.__new__(PricingUpdater)
    updater._dynamic_mapping = None
    with (
        patch("app.services.pricing_updater.get_settings", return_value=settings),
        patch("app.services.pricing_updater.httpx.AsyncClient", return_value=client),
        patch.object(PricingUpdater, "_build_dynamic_mapping", return_value={}),
    ):
        return await updater._fetch_marketplace_offer_pricing()


@pytest.mark.asyncio
async def test_palmyra_priced_for_base_and_geo_profile():
    rows = {r["model_id"]: r for r in await _rows()}
    assert set(rows) == {"writer.palmyra-x4-v1:0", "us.writer.palmyra-x4-v1:0"}
    row = rows["us.writer.palmyra-x4-v1:0"]
    # $2.50 / $10.00 per 1M tokens, the Region's standard rate (not long-context)
    assert row["input_price_per_token"] == Decimal("2.50") / Decimal(1_000_000)
    assert row["output_price_per_token"] == Decimal("10.00") / Decimal(1_000_000)


@pytest.mark.asyncio
async def test_openai_and_anthropic_never_priced_from_this_offer():
    ids = {r["model_id"] for r in await _rows()}
    assert not any("openai" in i or "anthropic" in i for i in ids)

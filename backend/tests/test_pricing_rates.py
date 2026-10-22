# pyright: reportCallIssue=false, reportArgumentType=false, reportAttributeAccessIssue=false
"""Published cache rates, long-context bands and SKU selection in pricing."""

import html
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.model_pricing import ModelPricing
from app.services.gemini_pricing_updater import GeminiPricingUpdater
from app.services.pricing import ModelPricing as PricingService
from app.services.pricing_updater import PricingUpdater

M = Decimal(1_000_000)


def per_m(value: str) -> Decimal:
    return Decimal(value) / M


@pytest.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(ModelPricing.__table__.create, checkfirst=True)
    maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


# ── AWS Price List API ──────────────────────────────────────────────────────


def _offer(skus):
    """skus: [(sku, attributes, price, unit)] → Price List offer JSON."""
    products, on_demand = {}, {}
    for sku, attrs, price, unit in skus:
        products[sku] = {"attributes": {"regionCode": "us-west-2", **attrs}}
        on_demand[sku] = {
            "T": {
                "priceDimensions": {"D": {"unit": unit, "pricePerUnit": {"USD": price}}}
            }
        }
    return {"products": products, "terms": {"OnDemand": on_demand}}


def _legacy(model, inference_type, usagetype, feature="On-demand Inference"):
    return {
        "model": model,
        "inferenceType": inference_type,
        "usagetype": usagetype,
        "feature": feature,
    }


async def _fetch_price_list(offer, mapping):
    updater = PricingUpdater(MagicMock())
    response = MagicMock(
        raise_for_status=MagicMock(), json=MagicMock(return_value=offer)
    )
    with (
        patch(
            "app.services.pricing_updater.get_settings",
            return_value=MagicMock(AWS_REGION="us-west-2"),
        ),
        patch("httpx.AsyncClient") as client,
        patch.object(PricingUpdater, "_dynamic_mapping_cache", mapping),
    ):
        client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=response
        )
        rows = await updater._fetch_from_price_list_api()
    return {row["model_id"]: row for row in rows}


@pytest.mark.asyncio
async def test_price_list_ignores_batch_latency_flex_and_priority_skus():
    offer = _offer(
        [
            # Standard on-demand vs latency-optimized (same model/inferenceType).
            (
                "a",
                _legacy("Llama X", "Input tokens", "USW2-llx-input-tokens"),
                "0.00072",
                "1K tokens",
            ),
            (
                "b",
                _legacy("Llama X", "Output tokens", "USW2-llx-output-tokens"),
                "0.00072",
                "1K tokens",
            ),
            (
                "c",
                _legacy(
                    "Llama X", "Input tokens", "USW2-llx-input-tokens-latency-optimized"
                ),
                "0.0009",
                "1K tokens",
            ),
            (
                "d",
                _legacy(
                    "Llama X",
                    "Output tokens",
                    "USW2-llx-output-tokens-latency-optimized",
                ),
                "0.0009",
                "1K tokens",
            ),
            # Global CRIS on-demand vs batch (batch listed last wins without the filter).
            (
                "e",
                _legacy(
                    "Nova P",
                    "Text Input Tokens",
                    "USW2-np-text-input-tokens-cross-region-global",
                    None,
                ),
                "0.00125",
                "1K tokens",
            ),
            (
                "f",
                _legacy(
                    "Nova P",
                    "Text Output Tokens",
                    "USW2-np-text-output-tokens-cross-region-global",
                    None,
                ),
                "0.01",
                "1K tokens",
            ),
            (
                "g",
                _legacy(
                    "Nova P",
                    "Text Output Tokens",
                    "USW2-np-text-output-tokens-cross-region-global-batch",
                    None,
                ),
                "0.005",
                "1K tokens",
            ),
            # Cache SKUs: Flex/Priority variants must not replace Standard.
            (
                "h",
                _legacy(
                    "Llama X",
                    "Prompt cache read input tokens",
                    "USW2-llx-cache-read-input-token-count",
                ),
                "0.000072",
                "1K tokens",
            ),
            (
                "i",
                _legacy(
                    "Llama X",
                    "Prompt cache read input tokens",
                    "USW2-llx-cache-read-input-token-count-priority",
                ),
                "0.0005",
                "1K tokens",
            ),
        ]
    )
    rows = await _fetch_price_list(
        offer, {"Llama X": "meta.llx", "Nova P": "amazon.np"}
    )

    assert rows["meta.llx"]["input_price_per_token"] == per_m("0.72")
    assert rows["meta.llx"]["output_price_per_token"] == per_m("0.72")
    assert rows["meta.llx"]["cached_input_price_per_token"] == per_m("0.072")
    assert rows["us.amazon.np"]["output_price_per_token"] == per_m("10")


@pytest.mark.asyncio
async def test_price_list_honours_per_1m_units_and_free_cache_writes():
    offer = _offer(
        [
            # Marketplace SKU priced per 1M tokens (was read as per 1K → ×1000).
            (
                "a",
                {
                    "model": "xai.grok-4.3",
                    "service_tier": "standard",
                    "tokenType": "input_tokens_mantle",
                    "usagetype": "x-in-standard",
                },
                "1.25",
                "1M tokens",
            ),
            (
                "b",
                {
                    "model": "xai.grok-4.3",
                    "service_tier": "standard",
                    "tokenType": "output_tokens_mantle",
                    "usagetype": "x-out-standard",
                },
                "2.50",
                "1M tokens",
            ),
            # Nova: $0 cache write is a real published price.
            (
                "c",
                _legacy("Nova Pro", "Input tokens", "USW2-NovaPro-input-tokens"),
                "0.0008",
                "1K tokens",
            ),
            (
                "d",
                _legacy("Nova Pro", "Output tokens", "USW2-NovaPro-output-tokens"),
                "0.0032",
                "1K tokens",
            ),
            (
                "e",
                _legacy(
                    "Nova Pro",
                    "Prompt cache read input tokens",
                    "USW2-NovaPro-cache-read-input-token-count",
                ),
                "0.0002",
                "1K tokens",
            ),
            (
                "f",
                _legacy(
                    "Nova Pro",
                    "Prompt cache write input tokens",
                    "USW2-NovaPro-cache-write-input-token-count",
                ),
                "0.0000000000",
                "1K tokens",
            ),
        ]
    )
    rows = await _fetch_price_list(
        offer, {"xai.grok-4.3": "xai.grok-4.3", "Nova Pro": "amazon.nova-pro-v1:0"}
    )

    assert rows["us.xai.grok-4.3"]["input_price_per_token"] == per_m("1.25")
    assert rows["us.xai.grok-4.3"]["output_price_per_token"] == per_m("2.50")
    nova = rows["amazon.nova-pro-v1:0"]
    assert nova["cached_input_price_per_token"] == per_m("0.2")
    assert nova["cache_write_price_per_token"] == Decimal(0)


@pytest.mark.asyncio
async def test_price_list_parses_inference_type_marketplace_dimensions():
    def sku(kind, scope, price):
        tier = "global-standard" if scope == "global" else "standard"
        suffix = " global" if scope == "global" else ""
        return (
            f"{kind}-{scope}",
            {
                "model": "Kimi K3",
                "service_tier": tier,
                "inferenceType": f"{kind}{suffix}",
                "usagetype": f"USW2-kimi-{kind}-{tier}",
            },
            price,
            "1K tokens",
        )

    offer = _offer(
        [
            sku("Input tokens", "global", "0.003"),
            sku("Output tokens", "global", "0.015"),
            sku("Cache read tokens", "global", "0.0003"),
            sku("Cache write tokens 30m", "global", "0.00375"),
        ]
    )
    rows = await _fetch_price_list(offer, {"Kimi K3": "moonshotai.kimi-k3"})

    kimi = rows["global.moonshotai.kimi-k3"]
    assert kimi["input_price_per_token"] == per_m("3")
    assert kimi["output_price_per_token"] == per_m("15")
    assert kimi["cached_input_price_per_token"] == per_m("0.3")
    assert kimi["cache_write_price_per_token"] == per_m("3.75")


def test_static_mapping_fixes():
    updater = PricingUpdater(MagicMock())
    with patch.object(PricingUpdater, "_dynamic_mapping_cache", {}):
        m = updater._map_model_name_to_id
        assert m("NVIDIA Nemotron Nano 2") == "nvidia.nemotron-nano-9b-v2"
        assert m("NVIDIA Nemotron Nano 2 VL") == "nvidia.nemotron-nano-12b-v2"
        assert m("GPT OSS Safeguard 20B") == "openai.gpt-oss-safeguard-20b"
        assert m("GPT OSS Safeguard 120B") == "openai.gpt-oss-safeguard-120b"
        assert m("Nova Pro Latency Optimized") is None
        assert m("Llama 3.1 70B Latency Optimized") is None


# ── AWS Bedrock pricing page scraper ────────────────────────────────────────

_FM_TABLE = """<table><thead><tr><th>Anthropic models</th>
<th>Price per 1M input tokens</th><th>Price per 1M output tokens</th>
<th>Price per 1M input tokens (batch)</th><th>Price per 1M output tokens (batch)</th>
<th>Price per 1M input tokens (5m cache write)</th>
<th>Price per 1M input tokens (1h cache write)</th>
<th>Price per 1M input tokens (cache read)</th></tr></thead>
<tr><td>Claude Haiku 5.5</td><td>{priceOf!bedrockfoundationmodels/x!h_in}</td>
<td>{priceOf!bedrockfoundationmodels/x!h_out}</td><td>N/A</td><td>N/A</td>
<td>{priceOf!bedrockfoundationmodels/x!h_w5}</td><td>{priceOf!bedrockfoundationmodels/x!h_w1}</td>
<td>{priceOf!bedrockfoundationmodels/x!h_cr}</td></tr>
<tr><td>Claude Haiku 5.5 - Long Context</td><td>{priceOf!bedrockfoundationmodels/x!l_in}</td>
<td>{priceOf!bedrockfoundationmodels/x!l_out}</td><td>N/A</td><td>N/A</td>
<td>{priceOf!bedrockfoundationmodels/x!l_w5}</td><td>{priceOf!bedrockfoundationmodels/x!l_w1}</td>
<td>{priceOf!bedrockfoundationmodels/x!l_cr}</td></tr>
<tr><td>Claude Sonnet 5.5</td><td>{priceOf!bedrockfoundationmodels/x!s_in}</td>
<td>{priceOf!bedrockfoundationmodels/x!s_out}</td><td>N/A</td><td>N/A</td>
<td>{priceOf!bedrockfoundationmodels/x!s_w5}</td><td>{priceOf!bedrockfoundationmodels/x!s_w1}</td>
<td>{priceOf!bedrockfoundationmodels/x!s_cr}</td></tr>
<tr><td>Claude Sonnet 5.5 - Long Context</td><td>{priceOf!bedrockfoundationmodels/x!s_in}</td>
<td>{priceOf!bedrockfoundationmodels/x!s_out}</td><td>N/A</td><td>N/A</td>
<td>N/A</td><td>N/A</td><td>N/A</td></tr>
</table>"""

_FM_PRICES = {
    "h_in": "0.1",
    "h_out": "0.5",
    "h_w5": "0.125",
    "h_w1": "0.2",
    "h_cr": "0.01",
    "l_in": "0.5",
    "l_out": "2.5",
    "l_w5": "0.625",
    "l_w1": "1.0",
    "l_cr": "0.05",
    "s_in": "2.0",
    "s_out": "10.0",
    "s_w5": "2.5",
    "s_w1": "4.0",
    "s_cr": "0.1",
}


async def _scrape(markup, prices):
    updater = PricingUpdater(MagicMock())
    page = (
        '<div data-pricing-markup="'
        + html.escape("<h3>Global Cross-region Inference</h3>" + markup, quote=True)
        + '"></div>'
    )
    fm = {"regions": {"US West (Oregon)": {k: {"price": v} for k, v in prices.items()}}}

    def response(url):
        r = MagicMock(raise_for_status=MagicMock())
        r.text = page
        r.json = MagicMock(
            return_value=fm if "foundationmodels" in url else {"regions": {}}
        )
        return r

    with (
        patch(
            "app.services.pricing_updater.get_settings",
            return_value=MagicMock(AWS_REGION="us-west-2"),
        ),
        patch("httpx.AsyncClient") as client,
        patch.object(
            PricingUpdater,
            "_dynamic_mapping_cache",
            {
                "Claude Haiku 5.5": "anthropic.claude-haiku-5-5",
                "Claude Sonnet 5.5": "anthropic.claude-sonnet-5-5",
            },
        ),
        patch.object(
            PricingUpdater,
            "_parse_token_ref",
            staticmethod(
                lambda ref: (ref.split("/")[0], ref.split("!")[-1], Decimal(1))
            ),
        ),
        patch.object(updater, "_scrape_openai_text_pricing", return_value=[]),
    ):
        client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=lambda url, *a, **k: response(url)
        )
        rows = await updater._scrape_aws_pricing_page()
    return {row["model_id"]: row for row in rows}


@pytest.mark.asyncio
async def test_scraper_reads_cache_read_column_and_long_context_band():
    rows = await _scrape(_FM_TABLE, _FM_PRICES)

    haiku = rows["global.anthropic.claude-haiku-5-5"]
    assert haiku["input_price_per_token"] == per_m("0.1")
    assert haiku["output_price_per_token"] == per_m("0.5")
    assert haiku["cached_input_price_per_token"] == per_m("0.01")
    assert haiku["long_context_threshold"] == 100_000
    assert haiku["long_input_price_per_token"] == per_m("0.5")
    assert haiku["long_output_price_per_token"] == per_m("2.5")
    assert haiku["long_cached_input_price_per_token"] == per_m("0.05")

    # Sonnet 5.5 cache read is 5% of input, not the 10% default.
    sonnet = rows["global.anthropic.claude-sonnet-5-5"]
    assert sonnet["cached_input_price_per_token"] == per_m("0.1")
    # Long-context row without a documented threshold is not guessed.
    assert "long_context_threshold" not in sonnet


# ── Billing ─────────────────────────────────────────────────────────────────


async def _seed(db, model_id, **fields):
    db.add(
        ModelPricing(
            model_id=model_id,
            region="us-west-2",
            currency="USD",
            source="test",
            **fields,
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_long_context_band_bills_the_whole_request(db):
    model = "global.anthropic.claude-haiku-5-5"
    await _seed(
        db,
        model,
        input_price_per_token=per_m("0.1"),
        output_price_per_token=per_m("0.5"),
        cached_input_price_per_token=per_m("0.01"),
        long_context_threshold=100_000,
        long_input_price_per_token=per_m("0.5"),
        long_output_price_per_token=per_m("2.5"),
        long_cached_input_price_per_token=per_m("0.05"),
    )
    pricing = PricingService(db)

    async def cost(prompt, write, read):
        return await pricing.calculate_cost(
            model=model,
            prompt_tokens=prompt,
            completion_tokens=1000,
            cache_creation_input_tokens=write,
            cache_read_input_tokens=read,
            cache_ttl="5m",
            region="us-west-2",
        )

    # Exactly at the threshold → short band.
    assert await cost(40_000, 10_000, 50_000) == (
        40_000 * per_m("0.1")
        + 1000 * per_m("0.5")
        + 10_000 * per_m("0.1") * Decimal("1.25")
        + 50_000 * per_m("0.01")
    )
    # Uncached + write + read above the threshold → every token at long rates.
    assert await cost(40_000, 10_000, 50_001) == (
        40_000 * per_m("0.5")
        + 1000 * per_m("2.5")
        + 10_000 * per_m("0.5") * Decimal("1.25")
        + 50_001 * per_m("0.05")
    )


@pytest.mark.asyncio
async def test_published_cache_rates_override_default_ratios(db):
    await _seed(
        db,
        "amazon.nova-pro-v1:0",
        input_price_per_token=per_m("0.8"),
        output_price_per_token=per_m("3.2"),
        cached_input_price_per_token=per_m("0.2"),
        cache_write_price_per_token=Decimal(0),
    )
    cost = await PricingService(db).calculate_cost(
        model="amazon.nova-pro-v1:0",
        prompt_tokens=0,
        completion_tokens=0,
        cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
        region="us-west-2",
    )
    # $0 write (not 1.25x) + 25% read (not 10%).
    assert cost == Decimal("0.2")


@pytest.mark.asyncio
async def test_prefix_fallback_keeps_the_fallback_rows_cache_rate(db):
    await _seed(
        db,
        "anthropic.claude-sonnet-5-5",
        input_price_per_token=per_m("2"),
        output_price_per_token=per_m("10"),
        cached_input_price_per_token=per_m("0.1"),
    )
    cost = await PricingService(db).calculate_cost(
        model="us.anthropic.claude-sonnet-5-5",
        prompt_tokens=0,
        completion_tokens=0,
        cache_read_input_tokens=1_000_000,
        region="us-west-2",
    )
    assert cost == Decimal("0.1")


@pytest.mark.asyncio
async def test_refresh_without_long_band_clears_it(db):
    updater = PricingUpdater(db)
    row = {
        "model_id": "m",
        "region": "us-west-2",
        "input_price_per_token": per_m("1"),
        "output_price_per_token": per_m("2"),
        "cache_write_price_per_token": Decimal(0),
        "long_context_threshold": 100_000,
        "long_input_price_per_token": per_m("2"),
        "long_output_price_per_token": per_m("4"),
    }
    await updater._save_pricing_data([row], "test")
    record = await updater.get_pricing_record("m", "us-west-2")
    assert record.long_context_threshold == 100_000
    assert record.cache_write_price_per_token == 0

    await updater._save_pricing_data(
        [
            {
                k: row[k]
                for k in (
                    "model_id",
                    "region",
                    "input_price_per_token",
                    "output_price_per_token",
                )
            }
        ],
        "test",
    )
    await db.refresh(record)
    assert record.long_context_threshold is None
    assert record.long_input_price_per_token is None
    assert record.cache_write_price_per_token is None


# ── Gemini (Google pricing page) ────────────────────────────────────────────


def _gemini_page(*sections):
    return "".join(
        f"<h2>{heading}</h2><h3>Standard</h3><table><tbody>"
        f"<tr><td>Input price</td><td>Free of charge</td><td>{inp}</td></tr>"
        f"<tr><td>Output price (including thinking tokens)</td><td>Free of charge</td><td>{out}</td></tr>"
        f"<tr><td>Context caching price</td><td>Not available</td><td>{cache}</td></tr>"
        "</tbody></table>"
        for heading, inp, out, cache in sections
    )


def test_gemini_page_parses_long_context_band():
    page = _gemini_page(
        (
            "Gemini 2.5 Pro",
            "$1.25, prompts <= 200k tokens<br>$2.50, prompts > 200k tokens",
            "$10.00, prompts <= 200k tokens<br>$15.00, prompts > 200k",
            "$0.125, prompts <= 200k tokens<br>$0.25, prompts > 200k<br>"
            "$4.50 / 1,000,000 tokens per hour (storage price)",
        )
    )
    [entry] = GeminiPricingUpdater(MagicMock())._parse_google_html(page)
    assert entry["model_id"] == "gemini-2.5-pro"
    assert entry["input_price_per_token"] == per_m("1.25")
    assert entry["output_price_per_token"] == per_m("10")
    assert entry["cached_input_price_per_token"] == per_m("0.125")
    assert entry["long_context_threshold"] == 200_000
    assert entry["long_input_price_per_token"] == per_m("2.50")
    assert entry["long_output_price_per_token"] == per_m("15")
    assert entry["long_cached_input_price_per_token"] == per_m("0.25")


def test_gemini_page_applies_scheduled_price_changes():
    page = _gemini_page(
        (
            "Gemini 4 Argon",
            "$2.00 through November 30, 2026.<br>$4.00 starting December 1, 2026.",
            "$10.00 through November 30, 2026.<br>$20.00 starting December 1, 2026.",
            "$0.10 through November 30, 2026.<br>$0.20 starting December 1, 2026.",
        )
    )
    parser = GeminiPricingUpdater(MagicMock())
    [before] = parser._parse_google_html(page, today=date(2026, 11, 30))
    [after] = parser._parse_google_html(page, today=date(2026, 12, 1))
    assert before["input_price_per_token"] == per_m("2")
    assert before["output_price_per_token"] == per_m("10")
    assert after["input_price_per_token"] == per_m("4")
    assert after["output_price_per_token"] == per_m("20")
    assert after["cached_input_price_per_token"] == per_m("0.2")


def test_gemini_page_splits_multi_model_headings():
    page = _gemini_page(
        (
            "Gemini 3.8 Live, Gemini 3.8 Live Extended Thinking, and Gemini 3.1 Flash Live Preview",
            "$0.75 (text) $3.00 or $0.005/min (audio)",
            "$4.50 (text) $12.00 or $0.018/min (audio)",
            "Not available",
        )
    )
    ids = [
        e["model_id"]
        for e in GeminiPricingUpdater(MagicMock())._parse_google_html(page)
    ]
    assert ids == [
        "gemini-3.8-live",
        "gemini-3.8-live-extended-thinking",
        "gemini-3.1-flash-live-preview",
    ]


@pytest.mark.asyncio
async def test_litellm_tiers_are_never_used_for_billing():
    data = {
        "gemini-x-preview": {
            "input_cost_per_token": 1e-6,
            "output_cost_per_token": 4e-6,
            "input_cost_per_token_above_200k_tokens": 2e-6,
            "output_cost_per_token_above_200k_tokens": 8e-6,
        }
    }
    response = MagicMock(
        raise_for_status=MagicMock(), json=MagicMock(return_value=data)
    )
    with patch("httpx.AsyncClient") as client:
        client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=response
        )
        entries, tiered = await GeminiPricingUpdater(
            MagicMock()
        )._fetch_litellm_prices()
    [entry] = entries
    assert "long_context_threshold" not in entry
    assert tiered == ["gemini-x-preview"]

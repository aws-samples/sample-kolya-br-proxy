"""Pricing-table responses must not write per-request fields into the cache."""

from datetime import datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.endpoints import monitor
from app.models.user import User

# The pricing fetch is patched, so neither stand-in is touched.
DB = cast(AsyncSession, SimpleNamespace())
ADMIN = cast(User, SimpleNamespace())


@pytest.mark.asyncio
async def test_cached_reads_do_not_mutate_shared_cache():
    row = {"model_id": "m", "region": "us-west-2", "last_updated": None}
    with patch.object(monitor, "_fetch_pricing_table", AsyncMock(return_value=[row])):
        monitor._pricing_cache = None
        monitor._cache_timestamp = None

        fresh = await monitor.get_pricing_table(
            force_refresh=True, db=DB, current_user=ADMIN
        )
        cached = await monitor.get_pricing_table(
            force_refresh=False, db=DB, current_user=ADMIN
        )

    assert fresh["cache_info"]["is_cached"] is False
    assert cached["cache_info"]["is_cached"] is True
    assert cached["total_records"] == 1
    # Per-request fields stay out of the shared cache.
    assert monitor._pricing_cache is not None
    assert "is_cached" not in monitor._pricing_cache["cache_info"]
    assert "cache_age_seconds" not in monitor._pricing_cache["cache_info"]
    assert isinstance(monitor._cache_timestamp, datetime)


def _db_returning(records):
    from unittest.mock import MagicMock

    result = MagicMock()
    result.scalars.return_value.all.return_value = records
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


def _db_record(
    model_id,
    region,
    input_per_m,
    output_per_m,
    cached_per_m=None,
    *,
    cache_write_per_m=None,
    long_threshold=None,
    long_rates_per_m=(None, None, None),
):
    from decimal import Decimal

    million = Decimal(1_000_000)

    def per_token(value):
        return None if value is None else Decimal(value) / million

    long_in, long_out, long_cached = long_rates_per_m
    return SimpleNamespace(
        model_id=model_id,
        region=region,
        input_price_per_token=Decimal(input_per_m) / million,
        output_price_per_token=Decimal(output_per_m) / million,
        cached_input_price_per_token=per_token(cached_per_m),
        cache_write_price_per_token=per_token(cache_write_per_m),
        long_context_threshold=long_threshold,
        long_input_price_per_token=per_token(long_in),
        long_output_price_per_token=per_token(long_out),
        long_cached_input_price_per_token=per_token(long_cached),
        source="aws-scraper",
        last_updated=None,
    )


@pytest.mark.asyncio
async def test_gpt_rows_come_from_the_billing_catalog_with_context_tiers():
    stale = _db_record("openai.gpt-5.6-sol", "us-east-1", "5.50", "33")
    claude = _db_record("anthropic.claude-x", "us-west-2", "3", "15", "0.30")

    rows = await monitor._fetch_pricing_table(_db_returning([stale, claude]))
    by_id = {}
    for row in rows:
        by_id.setdefault(row["model_id"], []).append(row)

    # Stale scraper rows for catalog models are replaced, not duplicated.
    [canonical] = by_id["openai.gpt-5.6-sol"]
    assert canonical["source"] == "aws-model-card"
    assert canonical["endpoint_family"] == "mantle"
    assert canonical["api"] == "responses"
    tiers = canonical["context_tiers"]
    assert [tier["label"] for tier in tiers] == ["≤272K", ">272K"]
    assert float(tiers[0]["input_price_per_1m"]) == 4.40
    assert float(tiers[0]["cache_write_price_per_1m"]) == 5.50
    assert float(tiers[0]["cache_read_price_per_1m"]) == 0.44
    assert float(tiers[0]["output_price_per_1m"]) == 22.0
    assert float(tiers[1]["output_price_per_1m"]) == 33.0
    assert canonical["prompt_cache"]["explicit"] is True
    assert set(canonical["prompt_cache"]["explicit_content_types"]) == {
        "input_text",
        "input_image",
        "input_file",
    }

    [global_sol] = by_id["global.openai.gpt-5.6-sol"]
    assert global_sol["endpoint_family"] == "runtime"
    assert global_sol["scope"] == "global"
    assert float(global_sol["context_tiers"][0]["input_price_per_1m"]) == 4.0

    [gpt55] = by_id["openai.gpt-5.5"]
    assert gpt55["prompt_cache"]["explicit"] is False
    assert gpt55["prompt_cache"]["implicit"] is True

    # Non-GPT rows keep DB pricing and expose their cache-read rate.
    [claude_row] = by_id["anthropic.claude-x"]
    assert claude_row["source"] == "aws-scraper"
    assert float(claude_row["cache_read_price_per_1m"]) == 0.30
    # 5m cache write billed at 1.25x input
    assert float(claude_row["cache_write_price_per_1m"]) == 3.75
    assert claude_row["context_tiers"] is None


@pytest.mark.asyncio
async def test_db_rows_show_the_rates_billing_applies():
    haiku = _db_record(
        "global.anthropic.claude-haiku-5-5",
        "us-west-2",
        "0.10",
        "0.50",
        "0.01",
        long_threshold=100_000,
        long_rates_per_m=("0.50", "2.50", "0.05"),
    )
    nova = _db_record(
        "amazon.nova-pro-v1:0",
        "us-west-2",
        "0.80",
        "3.20",
        "0.20",
        cache_write_per_m="0",
    )
    llama = _db_record("meta.llama3-1-70b-instruct-v1:0", "us-west-2", "0.72", "0.72")
    gemini = _db_record(
        "gemini-2.5-pro",
        "global",
        "1.25",
        "10",
        "0.125",
        long_threshold=200_000,
        long_rates_per_m=("2.50", "15", None),
    )

    rows = await monitor._fetch_pricing_table(
        _db_returning([haiku, nova, llama, gemini])
    )
    by_id = {row["model_id"]: row for row in rows}

    tiers = by_id["global.anthropic.claude-haiku-5-5"]["context_tiers"]
    assert [t["label"] for t in tiers] == ["≤100K", ">100K"]
    assert tiers[0]["max_input_tokens"] == 100_000
    assert [
        float(tiers[1][k])
        for k in (
            "input_price_per_1m",
            "cache_write_price_per_1m",
            "cache_read_price_per_1m",
            "output_price_per_1m",
        )
    ] == [0.5, 0.625, 0.05, 2.5]

    # Published $0 write wins over the 1.25x multiplier.
    assert float(by_id["amazon.nova-pro-v1:0"]["cache_write_price_per_1m"]) == 0
    # No published cache-read rate: show the 10% fallback billing uses.
    llama_row = by_id["meta.llama3-1-70b-instruct-v1:0"]
    assert float(llama_row["cache_read_price_per_1m"]) == 0.072

    gemini_tiers = by_id["gemini-2.5-pro"]["context_tiers"]
    assert gemini_tiers[0]["cache_write_price_per_1m"] is None
    # Long band has no published cache rate: Gemini's 25% fallback.
    assert float(gemini_tiers[1]["cache_read_price_per_1m"]) == 0.625


@pytest.mark.asyncio
async def test_ultrafast_tiers_are_listed_for_supported_routes():
    rows = await monitor._fetch_pricing_table(_db_returning([]))
    [sol61] = [row for row in rows if row["model_id"] == "global.openai.gpt-6.1-sol"]

    assert sol61["service_tiers"] == ["standard", "ultrafast"]
    labels = [tier["label"] for tier in sol61["context_tiers"]]
    assert labels == ["≤272K", ">272K", "Ultrafast ≤272K", "Ultrafast >272K"]
    assert float(sol61["context_tiers"][2]["output_price_per_1m"]) == 60.0

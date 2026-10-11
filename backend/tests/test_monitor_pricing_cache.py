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


def _db_record(model_id, region, input_per_m, output_per_m, cached_per_m=None):
    from decimal import Decimal

    million = Decimal(1_000_000)
    return SimpleNamespace(
        model_id=model_id,
        region=region,
        input_price_per_token=Decimal(input_per_m) / million,
        output_price_per_token=Decimal(output_per_m) / million,
        cached_input_price_per_token=(
            None if cached_per_m is None else Decimal(cached_per_m) / million
        ),
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
    assert claude_row["context_tiers"] is None

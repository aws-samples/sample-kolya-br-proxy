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

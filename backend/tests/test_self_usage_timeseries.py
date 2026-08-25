"""Tests for API-key self usage time-series aggregation."""

import uuid
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.usage_stats import UsageStatsService


@pytest.mark.asyncio
async def test_quota_timeseries_returns_usage_adjustment_and_quota_impact():
    token_id = uuid.uuid4()
    row = SimpleNamespace(
        time_bucket=datetime(2026, 8, 24),
        call_count=3,
        total_prompt_tokens=120,
        total_completion_tokens=30,
        total_tokens=150,
        usage_cost=Decimal("4.2500"),
        adjustment=Decimal("-1.0000"),
        quota_impact=Decimal("3.2500"),
        unpriced_request_count=1,
    )
    result = MagicMock()
    result.all.return_value = [row]
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    data = await UsageStatsService(db).get_quota_timeseries(
        token_id=token_id,
        start_date=datetime(2026, 8, 1),
        end_date=datetime(2026, 9, 1),
    )

    assert data == [
        {
            "time_bucket": "2026-08-24T00:00:00",
            "call_count": 3,
            "total_prompt_tokens": 120,
            "total_completion_tokens": 30,
            "total_tokens": 150,
            "usage_cost_usd": "4.2500",
            "adjustment_usd": "-1.0000",
            "quota_impact_usd": "3.2500",
            "unpriced_request_count": 1,
        }
    ]

    statement = db.execute.await_args.args[0]
    assert token_id in statement.compile().params.values()


@pytest.mark.asyncio
async def test_quota_timeseries_returns_empty_list_when_no_records_exist():
    result = MagicMock()
    result.all.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    data = await UsageStatsService(db).get_quota_timeseries(
        token_id=uuid.uuid4(),
        start_date=datetime(2026, 8, 1),
        end_date=datetime(2026, 9, 1),
    )

    assert data == []

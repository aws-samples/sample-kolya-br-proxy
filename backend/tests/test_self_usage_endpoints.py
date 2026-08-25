"""Tests for API-key-authenticated self usage endpoints."""

import inspect
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.router import gateway_router
from app.api.v1.endpoints.usage import (
    get_self_quota,
    get_self_usage_timeseries,
    router,
)


def _snapshot():
    return SimpleNamespace(
        scope="personal",
        reset_policy="reset",
        usage_window_start=datetime(2026, 8, 1),
        next_allowance_at=datetime(2026, 9, 1),
        rollover_months=1,
        monthly_base_limit_usd=Decimal("100.00"),
        monthly_effective_allowance_usd=Decimal("100.00"),
        monthly_usage_cost_usd=Decimal("70.00"),
        monthly_adjustment_usd=Decimal("5.00"),
        monthly_quota_impact_usd=Decimal("75.00"),
        monthly_remaining_usd=Decimal("25.00"),
        daily_limit_enabled=True,
        daily_limit_usd=Decimal("3.2258"),
        daily_usage_cost_usd=Decimal("1.00"),
        daily_adjustment_usd=Decimal("0.00"),
        daily_quota_impact_usd=Decimal("1.00"),
        lifetime_limit_usd=None,
        lifetime_usage_cost_usd=None,
        lifetime_adjustment_usd=None,
        lifetime_quota_impact_usd=None,
        lifetime_remaining_usd=None,
        is_monthly_exceeded=False,
        is_daily_exceeded=False,
        is_lifetime_exceeded=False,
        unpriced_request_count=0,
        as_of=datetime(2026, 8, 24, 12, 0),
    )


@pytest.mark.asyncio
async def test_quota_endpoint_serializes_authoritative_snapshot():
    token = SimpleNamespace(id=uuid.uuid4())
    db = MagicMock()

    with patch(
        "app.api.v1.endpoints.usage.get_quota_snapshot",
        AsyncMock(return_value=_snapshot()),
    ) as get_snapshot:
        result = await get_self_quota(token=token, db=db)

    get_snapshot.assert_awaited_once_with(token, db)
    assert result.monthly_remaining_usd == "25.00"
    assert result.monthly_quota_impact_usd == "75.00"
    assert result.scope == "personal"
    assert not hasattr(result, "token_id")


@pytest.mark.asyncio
async def test_timeseries_endpoint_scopes_query_to_authenticated_token():
    token = SimpleNamespace(id=uuid.uuid4())
    service = MagicMock()
    service.get_quota_timeseries = AsyncMock(
        return_value=[
            {
                "time_bucket": "2026-08-24T00:00:00",
                "call_count": 2,
                "total_prompt_tokens": 100,
                "total_completion_tokens": 20,
                "total_tokens": 120,
                "usage_cost_usd": "2.0000",
                "adjustment_usd": "0.0000",
                "quota_impact_usd": "2.0000",
                "unpriced_request_count": 0,
            }
        ]
    )

    with patch("app.api.v1.endpoints.usage.UsageStatsService", return_value=service):
        result = await get_self_usage_timeseries(
            start_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
            token=token,
            db=MagicMock(),
        )

    service.get_quota_timeseries.assert_awaited_once_with(
        token_id=token.id,
        start_date=datetime(2026, 8, 1),
        end_date=datetime(2026, 9, 1),
    )
    assert result.timezone == "UTC"
    assert result.data[0].quota_impact_usd == "2.0000"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        (datetime(2026, 9, 1), datetime(2026, 8, 1), "before end_date"),
        (datetime(2026, 1, 1), datetime(2026, 5, 1), "90 days"),
    ],
)
async def test_timeseries_endpoint_rejects_invalid_ranges(start, end, message):
    with pytest.raises(HTTPException, match=message) as exc:
        await get_self_usage_timeseries(
            start_date=start,
            end_date=end,
            token=SimpleNamespace(id=uuid.uuid4()),
            db=MagicMock(),
        )

    assert exc.value.status_code == 400


def test_self_usage_contract_never_accepts_caller_supplied_token_id():
    assert "token_id" not in inspect.signature(get_self_quota).parameters
    assert "token_id" not in inspect.signature(get_self_usage_timeseries).parameters
    assert {route.path for route in router.routes} == {
        "/usage/quota",
        "/usage/timeseries",
    }
    gateway_paths = {route.path for route in gateway_router.routes}
    assert {"/usage/quota", "/usage/timeseries"} <= gateway_paths

"""Authoritative quota snapshot tests.

The snapshot is the shared contract between request enforcement and the
self-service usage API. All database and team membership access is mocked.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.quota import get_quota_snapshot


NOW = datetime(2026, 8, 24, 12, 0, 0)


def _token(
    *,
    quota_usd=None,
    monthly_quota_usd=None,
    reset_policy="reset",
    quota_start=None,
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        quota_usd=quota_usd,
        monthly_quota_usd=monthly_quota_usd,
        monthly_reset_policy=reset_policy,
        monthly_quota_start=quota_start,
    )


def _usage_row(
    *,
    lifetime_usage="0.00",
    lifetime_adjustment="0.00",
    lifetime_impact="0.00",
    monthly_usage="0.00",
    monthly_adjustment="0.00",
    monthly_impact="0.00",
    daily_usage="0.00",
    daily_adjustment="0.00",
    daily_impact="0.00",
    unpriced=0,
):
    return SimpleNamespace(
        lifetime_usage_cost=Decimal(lifetime_usage),
        lifetime_adjustment=Decimal(lifetime_adjustment),
        lifetime_quota_impact=Decimal(lifetime_impact),
        monthly_usage_cost=Decimal(monthly_usage),
        monthly_adjustment=Decimal(monthly_adjustment),
        monthly_quota_impact=Decimal(monthly_impact),
        daily_usage_cost=Decimal(daily_usage),
        daily_adjustment=Decimal(daily_adjustment),
        daily_quota_impact=Decimal(daily_impact),
        unpriced_request_count=unpriced,
    )


def _db(row):
    result = MagicMock()
    result.one.return_value = row
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_personal_monthly_snapshot_separates_usage_and_adjustments():
    token = _token(monthly_quota_usd=Decimal("100.00"))
    db = _db(
        _usage_row(
            monthly_usage="70.00",
            monthly_adjustment="5.00",
            monthly_impact="75.00",
            daily_usage="3.00",
            daily_adjustment="1.00",
            daily_impact="4.00",
            unpriced=2,
        )
    )

    with patch("app.services.team.get_team_membership", AsyncMock(return_value=None)):
        snapshot = await get_quota_snapshot(token, db, now=NOW)

    assert snapshot.scope == "personal"
    assert snapshot.reset_policy == "reset"
    assert snapshot.usage_window_start == datetime(2026, 8, 1)
    assert snapshot.next_allowance_at == datetime(2026, 9, 1)
    assert snapshot.monthly_base_limit_usd == Decimal("100.00")
    assert snapshot.monthly_effective_allowance_usd == Decimal("100.00")
    assert snapshot.monthly_usage_cost_usd == Decimal("70.00")
    assert snapshot.monthly_adjustment_usd == Decimal("5.00")
    assert snapshot.monthly_quota_impact_usd == Decimal("75.00")
    assert snapshot.monthly_remaining_usd == Decimal("25.00")
    assert snapshot.daily_limit_usd == Decimal("100.00") / Decimal("31")
    assert snapshot.daily_quota_impact_usd == Decimal("4.00")
    assert snapshot.is_monthly_exceeded is False
    assert snapshot.is_daily_exceeded is True
    assert snapshot.unpriced_request_count == 2


@pytest.mark.asyncio
async def test_team_zero_allocation_is_exceeded_even_at_zero_usage():
    token = _token()
    membership = SimpleNamespace(
        allocated_usd=Decimal("0.00"),
        team=SimpleNamespace(
            monthly_reset_policy="reset",
            monthly_budget_start=datetime(2026, 8, 1),
            daily_limit_enabled=False,
        ),
    )

    with patch(
        "app.services.team.get_team_membership", AsyncMock(return_value=membership)
    ):
        snapshot = await get_quota_snapshot(token, _db(_usage_row()), now=NOW)

    assert snapshot.scope == "team"
    assert snapshot.monthly_effective_allowance_usd == Decimal("0.00")
    assert snapshot.monthly_remaining_usd == Decimal("0.00")
    assert snapshot.is_monthly_exceeded is True
    assert snapshot.daily_limit_enabled is False
    assert snapshot.daily_limit_usd is None
    assert snapshot.is_daily_exceeded is False


@pytest.mark.asyncio
async def test_rollover_snapshot_uses_cumulative_allowance_and_start_boundary():
    start = datetime(2026, 6, 15, 8, 30)
    token = _token(
        monthly_quota_usd=Decimal("100.00"),
        reset_policy="rollover",
        quota_start=start,
    )
    db = _db(
        _usage_row(
            monthly_usage="245.00",
            monthly_adjustment="5.00",
            monthly_impact="250.00",
        )
    )

    with patch("app.services.team.get_team_membership", AsyncMock(return_value=None)):
        snapshot = await get_quota_snapshot(token, db, now=NOW)

    assert snapshot.usage_window_start == start
    assert snapshot.monthly_base_limit_usd == Decimal("100.00")
    assert snapshot.monthly_effective_allowance_usd == Decimal("300.00")
    assert snapshot.monthly_remaining_usd == Decimal("50.00")
    assert snapshot.rollover_months == 3
    assert snapshot.is_monthly_exceeded is False


@pytest.mark.asyncio
async def test_unlimited_personal_token_still_reports_current_month_usage():
    token = _token()
    db = _db(
        _usage_row(
            monthly_usage="12.00",
            monthly_impact="12.00",
            daily_usage="2.00",
            daily_impact="2.00",
        )
    )

    with patch("app.services.team.get_team_membership", AsyncMock(return_value=None)):
        snapshot = await get_quota_snapshot(token, db, now=NOW)

    assert snapshot.monthly_effective_allowance_usd is None
    assert snapshot.monthly_remaining_usd is None
    assert snapshot.daily_limit_usd is None
    assert snapshot.is_monthly_exceeded is False
    assert snapshot.is_daily_exceeded is False
    assert snapshot.monthly_usage_cost_usd == Decimal("12.00")

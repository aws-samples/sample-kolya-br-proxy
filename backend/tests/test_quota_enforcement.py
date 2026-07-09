"""
Tests for quota enforcement, focused on the team-allocation edge cases.

Regression guard for a real quota-bypass bug: a team member whose
``allocated_usd`` is ``$0`` used to slip past ``enforce_quota`` entirely,
because the "has a monthly limit" check was ``effective_monthly > 0`` — and
``0 > 0`` is false. An allocation of $0 means "no budget", so every request
must be blocked, not silently allowed through as if unlimited.

All DB / team-membership access is mocked — no real database calls.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.quota import enforce_quota


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(quota_usd=None, monthly_quota_usd=None):
    token = MagicMock()
    token.id = uuid.uuid4()
    token.quota_usd = quota_usd
    token.monthly_quota_usd = monthly_quota_usd
    token.monthly_reset_policy = "reset"
    token.monthly_quota_start = None
    # calculate_used_usd is a plain setter on the real model; keep it a no-op.
    token.calculate_used_usd = MagicMock()
    return token


def _make_membership(allocated_usd, reset_policy="reset", daily_limit_enabled=False):
    membership = MagicMock()
    membership.allocated_usd = Decimal(str(allocated_usd))
    membership.team.monthly_reset_policy = reset_policy
    membership.team.monthly_budget_start = None
    membership.team.daily_limit_enabled = daily_limit_enabled
    return membership


def _mock_db(total=Decimal("0.00"), monthly=Decimal("0.00"), daily=Decimal("0.00")):
    """A db whose single aggregate query returns the given usage sums."""
    row = MagicMock()
    row.total = total
    row.monthly = monthly
    row.daily = daily
    result = MagicMock()
    result.one.return_value = row
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


# ---------------------------------------------------------------------------
# The bug: $0 team allocation must block, not bypass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_team_allocation_blocks_even_with_no_usage():
    """allocated_usd == $0 means no budget: every request is 429, even at $0 used."""
    token = _make_token()  # team token has no personal/lifetime quota
    db = _mock_db(monthly=Decimal("0.00"), daily=Decimal("0.00"))

    with patch(
        "app.services.team.get_team_membership",
        AsyncMock(return_value=_make_membership("0.00")),
    ):
        with pytest.raises(HTTPException) as exc:
            await enforce_quota(token, db)

    assert exc.value.status_code == 429
    assert "Monthly quota exceeded" in exc.value.detail


@pytest.mark.asyncio
async def test_team_allocation_blocks_when_monthly_usage_exceeds():
    """Normal team case: monthly usage over the allocation raises 429."""
    token = _make_token()
    db = _mock_db(monthly=Decimal("500.01"))

    with patch(
        "app.services.team.get_team_membership",
        AsyncMock(return_value=_make_membership("500.00")),
    ):
        with pytest.raises(HTTPException) as exc:
            await enforce_quota(token, db)

    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_lowered_allocation_below_existing_usage_blocks():
    """Reproduces the reported scenario: budget was $1, member spent $1 this
    month, then the allocation is lowered to $0.10. The next request must be
    blocked — this month's usage ($1.00) already exceeds the new $0.10 cap.

    (The dashboard badge is a *separate*, still-buggy code path; this test only
    proves real request enforcement is correct.)
    """
    token = _make_token()
    db = _mock_db(monthly=Decimal("1.00"))

    with patch(
        "app.services.team.get_team_membership",
        AsyncMock(return_value=_make_membership("0.10")),
    ):
        with pytest.raises(HTTPException) as exc:
            await enforce_quota(token, db)

    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_team_allocation_allows_when_under_budget():
    """Team member under the allocation is allowed through."""
    token = _make_token()
    db = _mock_db(monthly=Decimal("100.00"))

    with patch(
        "app.services.team.get_team_membership",
        AsyncMock(return_value=_make_membership("500.00")),
    ):
        # Should not raise.
        await enforce_quota(token, db)


# ---------------------------------------------------------------------------
# Personal-token semantics must be unchanged: 0 / None == "no monthly limit"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_personal_token_zero_monthly_is_unlimited():
    """A non-team token with monthly_quota_usd == 0 has no monthly limit."""
    token = _make_token(monthly_quota_usd=Decimal("0.00"))
    db = _mock_db()

    with patch("app.services.team.get_team_membership", AsyncMock(return_value=None)):
        # No quota of any kind -> early return, no DB query, no raise.
        await enforce_quota(token, db)
        db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_personal_token_none_monthly_is_unlimited():
    """A non-team token with no quotas set is unrestricted."""
    token = _make_token()
    db = _mock_db()

    with patch("app.services.team.get_team_membership", AsyncMock(return_value=None)):
        await enforce_quota(token, db)
        db.execute.assert_not_called()

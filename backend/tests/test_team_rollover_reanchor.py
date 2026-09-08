"""Regression tests for rollover window re-anchoring on policy switch.

`monthly_budget_start` is set once at team creation. When a team switches from
`reset` to `rollover`, the rollover window must re-anchor to the start of the
current month so accumulation begins at the switch instead of retroactively
pulling in the team's entire history (see quota._build_quota_snapshot).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.team import TeamService


CREATED_AT = datetime(2026, 5, 3, 9, 0, 0)  # months before "now"


def _service_with_team(*, reset_policy: str):
    team = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="team",
        monthly_budget_usd=Decimal("100.00"),
        monthly_reset_policy=reset_policy,
        daily_limit_enabled=True,
        monthly_budget_start=CREATED_AT,
    )
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    service = TeamService(db)
    return service, team


@pytest.mark.asyncio
async def test_switch_reset_to_rollover_reanchors_to_current_month_start():
    service, team = _service_with_team(reset_policy="reset")
    now = datetime(2026, 8, 24, 12, 0, 0)

    with (
        patch.object(
            TeamService,
            "_lock_team_and_members",
            AsyncMock(return_value=(team, [], Decimal("0.00"))),
        ),
        patch("app.services.team.datetime") as dt,
    ):
        dt.utcnow.return_value = now
        dt.side_effect = lambda *a, **k: datetime(*a, **k)
        await service.update_team(team_id=team.id, monthly_reset_policy="rollover")

    assert team.monthly_reset_policy == "rollover"
    assert team.monthly_budget_start == datetime(2026, 8, 1)


@pytest.mark.asyncio
async def test_rollover_stays_rollover_preserves_existing_window():
    service, team = _service_with_team(reset_policy="rollover")

    with patch.object(
        TeamService,
        "_lock_team_and_members",
        AsyncMock(return_value=(team, [], Decimal("0.00"))),
    ):
        await service.update_team(team_id=team.id, monthly_reset_policy="rollover")

    # Re-saving an already-rollover team must NOT wipe accumulated window.
    assert team.monthly_budget_start == CREATED_AT


@pytest.mark.asyncio
async def test_unrelated_update_leaves_window_untouched():
    service, team = _service_with_team(reset_policy="reset")

    with patch.object(
        TeamService,
        "_lock_team_and_members",
        AsyncMock(return_value=(team, [], Decimal("0.00"))),
    ):
        await service.update_team(team_id=team.id, name="renamed")

    assert team.monthly_reset_policy == "reset"
    assert team.monthly_budget_start == CREATED_AT

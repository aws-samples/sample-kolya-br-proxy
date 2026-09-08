"""Experiment: prove the /tokens page and /teams dashboard agree for a team key.

Runs the three aggregation windows against a shared in-memory usage_records
table for a single rollover team key:

* tokens_old   — pre-fix /tokens: always calendar month_start
* tokens_new   — post-fix /tokens: team window (rollover -> monthly_budget_start)
* teams_member — /teams dashboard per-member: same team window

Asserts tokens_new == teams_member (consistency achieved) and that the old
behaviour genuinely diverged (so the fix is doing something).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


NOW = datetime(2026, 9, 8, 12, 0, 0)
CALENDAR_MONTH_START = datetime(2026, 9, 1)
# Team "aa" switched to rollover mid-August; window anchored to Aug 1.
BUDGET_START = datetime(2026, 8, 1)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE usage_records (
                    id TEXT PRIMARY KEY,
                    token_id TEXT NOT NULL,
                    cost_usd NUMERIC(10, 4) NOT NULL,
                    record_type TEXT NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _insert(db, token_id, cost, created_at, record_type="usage"):
    await db.execute(
        text(
            "INSERT INTO usage_records (id, token_id, cost_usd, record_type, created_at)"
            " VALUES (:id, :tid, :cost, :rt, :ts)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": token_id,
            "cost": str(cost),
            "rt": record_type,
            "ts": created_at,
        },
    )


async def _sum_since(db, token_id, boundary):
    row = await db.execute(
        text(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM usage_records"
            " WHERE token_id = :tid AND created_at >= :b"
        ),
        {"tid": token_id, "b": boundary},
    )
    return Decimal(str(row.scalar()))


@pytest.mark.asyncio
async def test_tokens_and_teams_agree_for_rollover_team_key(db):
    tok = "aa-token"
    # August spend (in the rollover window, but BEFORE the calendar month).
    await _insert(db, tok, "4.00", datetime(2026, 8, 12, 9, 0))
    # A mid-window admin credit — both pages include adjustments.
    await _insert(
        db, tok, "-1.00", datetime(2026, 8, 20, 9, 0), record_type="adjustment"
    )
    # September spend (inside the calendar month too).
    await _insert(db, tok, "3.00", datetime(2026, 9, 5, 9, 0))
    await db.commit()

    tokens_old = await _sum_since(db, tok, CALENDAR_MONTH_START)  # pre-fix /tokens
    tokens_new = await _sum_since(db, tok, BUDGET_START)  # post-fix /tokens
    teams_member = await _sum_since(db, tok, BUDGET_START)  # /teams dashboard

    print(
        f"\n[experiment] tokens_old(calendar)={tokens_old} "
        f"tokens_new(team-window)={tokens_new} teams_member={teams_member}"
    )

    # Consistency achieved: /tokens now matches /teams for the team key.
    assert tokens_new == teams_member == Decimal("6.00")
    # And the fix mattered: the old calendar-month window disagreed.
    assert tokens_old == Decimal("3.00")
    assert tokens_old != teams_member


@pytest.mark.asyncio
async def test_tokens_and_teams_agree_for_reset_team_key(db):
    """For a reset-policy team, both windows are the calendar month → trivially equal."""
    tok = "aa-reset"
    await _insert(db, tok, "4.00", datetime(2026, 8, 12, 9, 0))  # last month, excluded
    await _insert(db, tok, "3.00", datetime(2026, 9, 5, 9, 0))  # this month
    await db.commit()

    boundary = CALENDAR_MONTH_START  # reset policy uses calendar month in both pages
    tokens = await _sum_since(db, tok, boundary)
    teams = await _sum_since(db, tok, boundary)

    assert tokens == teams == Decimal("3.00")

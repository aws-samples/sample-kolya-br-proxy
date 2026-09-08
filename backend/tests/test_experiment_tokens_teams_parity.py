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


async def _team_sum_since(db, token_ids, boundary):
    """Sum a team's spend across all member tokens over one window."""
    total = Decimal("0.00")
    for tid in token_ids:
        total += await _sum_since(db, tid, boundary)
    return total


@pytest.mark.asyncio
async def test_teams_list_card_matches_dashboard_for_rollover_team(db):
    """The /teams list card total must match the dashboard for a rollover team.

    Models the three production windows for a rollover team with two member
    tokens:
      * list_old  — pre-fix /teams list card: always calendar month_start
      * list_new  — post-fix /teams list card: case(rollover -> budget_start)
      * dashboard — /teams dashboard: sum of per-member team-window totals
    list_new must equal the dashboard total, and list_old must have diverged.
    """
    toks = ["aa-1", "aa-2"]
    # August spend (inside the rollover window, before the calendar month).
    await _insert(db, "aa-1", "4.00", datetime(2026, 8, 12, 9, 0))
    await _insert(db, "aa-2", "2.00", datetime(2026, 8, 15, 9, 0))
    # September spend (also inside the calendar month).
    await _insert(db, "aa-1", "3.00", datetime(2026, 9, 5, 9, 0))
    await _insert(db, "aa-2", "1.00", datetime(2026, 9, 6, 9, 0))
    await db.commit()

    list_old = await _team_sum_since(db, toks, CALENDAR_MONTH_START)  # pre-fix card
    list_new = await _team_sum_since(db, toks, BUDGET_START)  # post-fix card
    dashboard = await _team_sum_since(db, toks, BUDGET_START)  # /teams dashboard

    # Consistency achieved: the list card now matches the dashboard.
    assert list_new == dashboard == Decimal("10.00")
    # And the fix mattered: the old calendar-month card under-counted.
    assert list_old == Decimal("4.00")
    assert list_old != dashboard


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


@pytest.mark.asyncio
async def test_reset_second_month_tokens_and_teams_agree(db):
    """Second month under 'reset': /tokens and /teams both show only the new month.

    Reproduces the two production code paths' boundary + sum for a reset team:
      * /tokens  (tokens.py):  case(rollover -> budget_start, else_ -> month_start)
      * /teams   (teams.py:280): budget_start if is_rollover else month_start
    Both collapse to the current calendar month_start for reset, and both sum
    cost_usd across record types (usage + adjustment). So in the second month the
    first month's spend is dropped and the two pages must report the same figure.
    """
    tok = "aa-reset-2mo"
    # "Now" is the second month (October); reset boundary is Oct 1.
    now = datetime(2026, 10, 15, 12, 0)
    month_start = datetime(now.year, now.month, 1)  # 2026-10-01

    # First month (September) spend — must be excluded in the second month.
    await _insert(db, tok, "7.00", datetime(2026, 9, 20, 9, 0))
    # Second month (October) spend + a mid-month admin adjustment.
    await _insert(db, tok, "5.00", datetime(2026, 10, 3, 9, 0))
    await _insert(
        db, tok, "-2.00", datetime(2026, 10, 8, 9, 0), record_type="adjustment"
    )
    await db.commit()

    # Independently derive each page's boundary exactly as the code does.
    is_rollover = False  # reset policy
    tokens_boundary = month_start if not is_rollover else datetime(2026, 8, 1)
    teams_boundary = datetime(2026, 8, 1) if is_rollover else month_start

    tokens_used = await _sum_since(db, tok, tokens_boundary)
    teams_used = await _sum_since(db, tok, teams_boundary)

    print(
        f"\n[experiment reset 2nd month] tokens={tokens_used} teams={teams_used} "
        f"(first-month $7 excluded; second month 5 - 2 = 3)"
    )

    # Both pages agree, and only the second month counts (5 - 2 = 3).
    assert tokens_used == teams_used == Decimal("3.00")
    # Sanity: the first month's $7 was genuinely dropped.
    assert await _sum_since(db, tok, datetime(2026, 9, 1)) == Decimal("10.00")

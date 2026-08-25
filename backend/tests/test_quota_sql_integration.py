"""SQLite-backed integration tests for the authoritative quota SQL.

These tests execute the real SQLAlchemy aggregate query against an in-memory
database. The minimal table avoids unrelated PostgreSQL-only model columns
while preserving every column read by ``app.services.quota``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.services.quota import enforce_quota, get_quota_snapshot


NOW = datetime(2026, 8, 24, 12, 0, 0)


class FrozenDateTime(datetime):
    @classmethod
    def utcnow(cls):
        return cls.fromtimestamp(NOW.timestamp())


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                CREATE TABLE usage_records (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_creation_input_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_read_input_tokens INTEGER NOT NULL DEFAULT 0,
                    cost_usd NUMERIC(10, 4) NOT NULL,
                    record_type TEXT NOT NULL,
                    note TEXT,
                    request_metadata JSON,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


def _token(
    *,
    token_id=None,
    quota_usd=None,
    monthly_quota_usd=None,
    reset_policy="reset",
    quota_start=None,
):
    return SimpleNamespace(
        id=token_id or uuid.uuid4(),
        quota_usd=quota_usd,
        monthly_quota_usd=monthly_quota_usd,
        monthly_reset_policy=reset_policy,
        monthly_quota_start=quota_start,
        calculate_used_usd=lambda _amount: None,
    )


async def _insert_record(
    db_session,
    token_id,
    cost,
    created_at,
    *,
    record_type="usage",
    note=None,
):
    await db_session.execute(
        text(
            """
            INSERT INTO usage_records (
                id, user_id, token_id, request_id, model, cost_usd,
                record_type, note, created_at
            ) VALUES (
                :id, :user_id, :token_id, :request_id, :model, :cost_usd,
                :record_type, :note, :created_at
            )
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
            # SQLAlchemy's UUID bind processor uses the hexadecimal form on SQLite.
            "token_id": token_id.hex,
            "request_id": f"request-{uuid.uuid4()}",
            "model": "openai.gpt-5.4",
            # aiosqlite does not bind Decimal directly; NUMERIC converts this value.
            "cost_usd": str(cost),
            "record_type": record_type,
            "note": note,
            "created_at": created_at,
        },
    )


async def _snapshot(token, db_session):
    with patch(
        "app.services.team.get_team_membership",
        AsyncMock(return_value=None),
    ):
        return await get_quota_snapshot(token, db_session, now=NOW)


async def _enforce(token, db_session):
    with (
        patch("app.services.quota.datetime", FrozenDateTime),
        patch(
            "app.services.team.get_team_membership",
            AsyncMock(return_value=None),
        ),
    ):
        await enforce_quota(token, db_session)


@pytest.mark.asyncio
async def test_snapshot_executes_real_sql_for_windows_adjustments_and_token_scope(
    db_session,
):
    token = _token(
        quota_usd=Decimal("200.00"),
        monthly_quota_usd=Decimal("100.00"),
    )
    records = [
        ("40.00", datetime(2026, 7, 31, 23, 0), "usage", None),
        ("70.00", datetime(2026, 8, 10, 8, 0), "usage", None),
        ("-5.00", datetime(2026, 8, 20, 8, 0), "adjustment", "credit"),
        ("3.00", datetime(2026, 8, 24, 8, 0), "usage", None),
        ("0.00", datetime(2026, 8, 24, 9, 0), "usage", "pricing_missing"),
        ("1.00", datetime(2026, 8, 24, 10, 0), "adjustment", "debit"),
    ]
    for cost, created_at, record_type, note in records:
        await _insert_record(
            db_session,
            token.id,
            cost,
            created_at,
            record_type=record_type,
            note=note,
        )
    await _insert_record(
        db_session,
        uuid.uuid4(),
        "999.00",
        datetime(2026, 8, 24, 11, 0),
    )
    await db_session.commit()

    snapshot = await _snapshot(token, db_session)

    assert snapshot.monthly_usage_cost_usd == Decimal("73.0000")
    assert snapshot.monthly_adjustment_usd == Decimal("-4.0000")
    assert snapshot.monthly_quota_impact_usd == Decimal("69.0000")
    assert snapshot.monthly_remaining_usd == Decimal("31.0000")
    assert snapshot.daily_usage_cost_usd == Decimal("3.0000")
    assert snapshot.daily_adjustment_usd == Decimal("1.0000")
    assert snapshot.daily_quota_impact_usd == Decimal("4.0000")
    assert snapshot.lifetime_usage_cost_usd == Decimal("113.0000")
    assert snapshot.lifetime_adjustment_usd == Decimal("-4.0000")
    assert snapshot.lifetime_quota_impact_usd == Decimal("109.0000")
    assert snapshot.lifetime_remaining_usd == Decimal("91.0000")
    assert snapshot.unpriced_request_count == 1
    assert snapshot.is_monthly_exceeded is False
    assert snapshot.is_daily_exceeded is True
    assert snapshot.is_lifetime_exceeded is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("token", "records", "expected_message"),
    [
        (
            _token(quota_usd=Decimal("50.00")),
            [("50.00", datetime(2026, 7, 1), "usage")],
            "Lifetime quota exceeded",
        ),
        (
            _token(monthly_quota_usd=Decimal("100.00")),
            [("100.00", datetime(2026, 8, 10), "usage")],
            "Monthly quota exceeded",
        ),
        (
            _token(monthly_quota_usd=Decimal("310.00")),
            [("10.00", datetime(2026, 8, 24, 8, 0), "usage")],
            "Daily limit exceeded",
        ),
        (
            _token(
                monthly_quota_usd=Decimal("100.00"),
                reset_policy="rollover",
                quota_start=datetime(2026, 6, 15),
            ),
            [
                ("100.00", datetime(2026, 6, 16), "usage"),
                ("100.00", datetime(2026, 7, 1), "usage"),
                ("100.00", datetime(2026, 8, 1), "usage"),
            ],
            "Monthly quota exceeded (rollover)",
        ),
    ],
    ids=["lifetime", "monthly", "daily", "rollover"],
)
async def test_enforcement_executes_real_sql_for_each_limit(
    db_session,
    token,
    records,
    expected_message,
):
    for cost, created_at, record_type in records:
        await _insert_record(
            db_session,
            token.id,
            cost,
            created_at,
            record_type=record_type,
        )
    await db_session.commit()

    with pytest.raises(HTTPException) as raised:
        await _enforce(token, db_session)

    assert raised.value.status_code == 429
    assert expected_message in raised.value.detail


@pytest.mark.asyncio
async def test_credit_adjustment_reduces_the_sql_enforcement_impact(db_session):
    token = _token(monthly_quota_usd=Decimal("100.00"))
    await _insert_record(
        db_session,
        token.id,
        "105.00",
        datetime(2026, 8, 10),
    )
    await _insert_record(
        db_session,
        token.id,
        "-10.00",
        datetime(2026, 8, 11),
        record_type="adjustment",
        note="credit",
    )
    await db_session.commit()

    await _enforce(token, db_session)
    snapshot = await _snapshot(token, db_session)

    assert snapshot.monthly_usage_cost_usd == Decimal("105.0000")
    assert snapshot.monthly_adjustment_usd == Decimal("-10.0000")
    assert snapshot.monthly_quota_impact_usd == Decimal("95.0000")
    assert snapshot.monthly_remaining_usd == Decimal("5.0000")
    assert snapshot.is_monthly_exceeded is False

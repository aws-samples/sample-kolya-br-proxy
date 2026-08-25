"""Centralized quota calculation and enforcement for API tokens."""

import calendar
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token import APIToken
from app.models.usage import UsageRecord


ZERO = Decimal("0.00")


@dataclass(frozen=True)
class EffectiveQuota:
    """Resolved personal or team quota policy for one API token."""

    scope: str
    monthly_base_limit_usd: Decimal | None
    reset_policy: str
    quota_start: datetime | None
    daily_limit_enabled: bool
    has_monthly_limit: bool


@dataclass(frozen=True)
class QuotaSnapshot:
    """Authoritative, read-only view of quota state at a point in time."""

    scope: str
    reset_policy: str
    usage_window_start: datetime
    next_allowance_at: datetime
    rollover_months: int
    monthly_base_limit_usd: Decimal | None
    monthly_effective_allowance_usd: Decimal | None
    monthly_usage_cost_usd: Decimal
    monthly_adjustment_usd: Decimal
    monthly_quota_impact_usd: Decimal
    monthly_remaining_usd: Decimal | None
    daily_limit_enabled: bool
    daily_limit_usd: Decimal | None
    daily_usage_cost_usd: Decimal
    daily_adjustment_usd: Decimal
    daily_quota_impact_usd: Decimal
    lifetime_limit_usd: Decimal | None
    lifetime_usage_cost_usd: Decimal | None
    lifetime_adjustment_usd: Decimal | None
    lifetime_quota_impact_usd: Decimal | None
    lifetime_remaining_usd: Decimal | None
    is_monthly_exceeded: bool
    is_daily_exceeded: bool
    is_lifetime_exceeded: bool
    unpriced_request_count: int
    as_of: datetime


def _months_elapsed(start: datetime, now: datetime) -> int:
    """Count calendar months from start to now (inclusive of current month)."""
    return (now.year - start.year) * 12 + (now.month - start.month) + 1


def _next_month_start(now: datetime) -> datetime:
    if now.month == 12:
        return datetime(now.year + 1, 1, 1)
    return datetime(now.year, now.month + 1, 1)


async def _resolve_effective_quota(token: APIToken, db: AsyncSession) -> EffectiveQuota:
    """Resolve team allocation first, otherwise use the token's own policy."""
    from app.services.team import get_team_membership

    membership = await get_team_membership(token.id, db)
    if membership:
        limit = membership.allocated_usd
        return EffectiveQuota(
            scope="team",
            monthly_base_limit_usd=limit,
            reset_policy=membership.team.monthly_reset_policy or "reset",
            quota_start=membership.team.monthly_budget_start,
            daily_limit_enabled=membership.team.daily_limit_enabled,
            # A team allocation of zero means no available budget.
            has_monthly_limit=limit is not None,
        )

    limit = token.monthly_quota_usd
    return EffectiveQuota(
        scope="personal",
        monthly_base_limit_usd=limit,
        reset_policy=token.monthly_reset_policy or "reset",
        quota_start=token.monthly_quota_start,
        daily_limit_enabled=True,
        # Personal None/zero means unlimited, preserving existing behavior.
        has_monthly_limit=limit is not None and limit > 0,
    )


def _cost_sum(condition):
    return func.coalesce(
        func.sum(case((condition, UsageRecord.cost_usd), else_=ZERO)), ZERO
    )


async def _build_quota_snapshot(
    token: APIToken,
    db: AsyncSession,
    effective: EffectiveQuota,
    now: datetime,
) -> QuotaSnapshot:
    month_start = datetime(now.year, now.month, 1)
    day_start = datetime(now.year, now.month, now.day)
    is_rollover = effective.has_monthly_limit and effective.reset_policy == "rollover"
    usage_window_start = (
        (effective.quota_start or month_start) if is_rollover else month_start
    )

    rollover_months = 0
    effective_allowance = None
    if effective.has_monthly_limit:
        rollover_months = (
            max(1, _months_elapsed(usage_window_start, now)) if is_rollover else 1
        )
        effective_allowance = effective.monthly_base_limit_usd
        if is_rollover:
            effective_allowance *= Decimal(str(rollover_months))

    usage_record = UsageRecord.record_type == "usage"
    adjustment_record = UsageRecord.record_type == "adjustment"
    in_monthly_window = UsageRecord.created_at >= usage_window_start
    in_daily_window = UsageRecord.created_at >= day_start
    unpriced_usage = and_(
        usage_record,
        in_monthly_window,
        UsageRecord.note == "pricing_missing",
    )

    query = select(
        _cost_sum(usage_record).label("lifetime_usage_cost"),
        _cost_sum(adjustment_record).label("lifetime_adjustment"),
        func.coalesce(func.sum(UsageRecord.cost_usd), ZERO).label(
            "lifetime_quota_impact"
        ),
        _cost_sum(and_(usage_record, in_monthly_window)).label("monthly_usage_cost"),
        _cost_sum(and_(adjustment_record, in_monthly_window)).label(
            "monthly_adjustment"
        ),
        _cost_sum(in_monthly_window).label("monthly_quota_impact"),
        _cost_sum(and_(usage_record, in_daily_window)).label("daily_usage_cost"),
        _cost_sum(and_(adjustment_record, in_daily_window)).label("daily_adjustment"),
        _cost_sum(in_daily_window).label("daily_quota_impact"),
        func.count(case((unpriced_usage, 1))).label("unpriced_request_count"),
    ).where(UsageRecord.token_id == token.id)

    # Avoid scanning lifetime history unless a lifetime quota requires it.
    if token.quota_usd is None:
        query = query.where(UsageRecord.created_at >= usage_window_start)

    result = await db.execute(query)
    row = result.one()

    monthly_impact = Decimal(row.monthly_quota_impact or ZERO)
    daily_impact = Decimal(row.daily_quota_impact or ZERO)
    lifetime_impact = (
        Decimal(row.lifetime_quota_impact or ZERO)
        if token.quota_usd is not None
        else None
    )

    monthly_remaining = (
        max(ZERO, effective_allowance - monthly_impact)
        if effective_allowance is not None
        else None
    )
    lifetime_remaining = (
        max(ZERO, token.quota_usd - lifetime_impact)
        if token.quota_usd is not None
        else None
    )

    daily_limit = None
    if effective.has_monthly_limit and effective.daily_limit_enabled:
        days_in_month = calendar.monthrange(now.year, now.month)[1]
        daily_limit = effective.monthly_base_limit_usd / Decimal(str(days_in_month))

    return QuotaSnapshot(
        scope=effective.scope,
        reset_policy=effective.reset_policy,
        usage_window_start=usage_window_start,
        next_allowance_at=_next_month_start(now),
        rollover_months=rollover_months,
        monthly_base_limit_usd=effective.monthly_base_limit_usd,
        monthly_effective_allowance_usd=effective_allowance,
        monthly_usage_cost_usd=Decimal(row.monthly_usage_cost or ZERO),
        monthly_adjustment_usd=Decimal(row.monthly_adjustment or ZERO),
        monthly_quota_impact_usd=monthly_impact,
        monthly_remaining_usd=monthly_remaining,
        daily_limit_enabled=effective.daily_limit_enabled,
        daily_limit_usd=daily_limit,
        daily_usage_cost_usd=Decimal(row.daily_usage_cost or ZERO),
        daily_adjustment_usd=Decimal(row.daily_adjustment or ZERO),
        daily_quota_impact_usd=daily_impact,
        lifetime_limit_usd=token.quota_usd,
        lifetime_usage_cost_usd=(
            Decimal(row.lifetime_usage_cost or ZERO)
            if token.quota_usd is not None
            else None
        ),
        lifetime_adjustment_usd=(
            Decimal(row.lifetime_adjustment or ZERO)
            if token.quota_usd is not None
            else None
        ),
        lifetime_quota_impact_usd=lifetime_impact,
        lifetime_remaining_usd=lifetime_remaining,
        is_monthly_exceeded=(
            effective_allowance is not None and monthly_impact >= effective_allowance
        ),
        is_daily_exceeded=daily_limit is not None and daily_impact >= daily_limit,
        is_lifetime_exceeded=(
            token.quota_usd is not None and lifetime_impact >= token.quota_usd
        ),
        unpriced_request_count=int(row.unpriced_request_count or 0),
        as_of=now,
    )


async def get_quota_snapshot(
    token: APIToken, db: AsyncSession, now: datetime | None = None
) -> QuotaSnapshot:
    """Return quota state for the authenticated token without enforcing it."""
    current_time = now or datetime.utcnow()
    effective = await _resolve_effective_quota(token, db)
    return await _build_quota_snapshot(token, db, effective, current_time)


async def enforce_quota(token: APIToken, db: AsyncSession) -> None:
    """Check lifetime, monthly, and daily quota tiers; raise HTTP 429."""
    effective = await _resolve_effective_quota(token, db)
    if token.quota_usd is None and not effective.has_monthly_limit:
        return

    snapshot = await _build_quota_snapshot(token, db, effective, datetime.utcnow())

    calculate_used = getattr(token, "calculate_used_usd", None)
    if token.quota_usd is not None and callable(calculate_used):
        calculate_used(snapshot.lifetime_quota_impact_usd)

    if snapshot.is_lifetime_exceeded:
        raise HTTPException(
            status_code=429,
            detail=(
                "Lifetime quota exceeded. "
                f"Used: ${snapshot.lifetime_quota_impact_usd:.2f}, "
                f"Limit: ${snapshot.lifetime_limit_usd:.2f}"
            ),
        )

    if snapshot.is_monthly_exceeded:
        if snapshot.reset_policy == "rollover":
            raise HTTPException(
                status_code=429,
                detail=(
                    "Monthly quota exceeded (rollover). "
                    f"Used: ${snapshot.monthly_quota_impact_usd:.2f}, "
                    f"Allowance: ${snapshot.monthly_effective_allowance_usd:.2f} "
                    f"({snapshot.rollover_months} months × "
                    f"${snapshot.monthly_base_limit_usd:.2f})"
                ),
            )
        raise HTTPException(
            status_code=429,
            detail=(
                "Monthly quota exceeded. "
                f"Used: ${snapshot.monthly_quota_impact_usd:.2f}, "
                f"Limit: ${snapshot.monthly_effective_allowance_usd:.2f}"
            ),
        )

    if snapshot.is_daily_exceeded:
        raise HTTPException(
            status_code=429,
            detail=(
                "Daily limit exceeded. "
                f"Used today: ${snapshot.daily_quota_impact_usd:.2f}, "
                f"Limit: ${snapshot.daily_limit_usd:.2f}"
            ),
        )

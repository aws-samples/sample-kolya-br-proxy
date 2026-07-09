"""Centralized quota enforcement for API tokens."""

import calendar
from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token import APIToken
from app.models.usage import UsageRecord


def _months_elapsed(start: datetime, now: datetime) -> int:
    """Count calendar months from start to now (inclusive of current month)."""
    return (now.year - start.year) * 12 + (now.month - start.month) + 1


async def enforce_quota(token: APIToken, db: AsyncSession) -> None:
    """Check all quota tiers for a token. Raises HTTP 429 if any exceeded.

    Checks in order:
    1. Lifetime quota (quota_usd) - sum of ALL usage
    2. Monthly quota - either from team allocation or token's own monthly_quota_usd
    3. Daily limit - auto-calculated from effective monthly quota
    """
    from app.services.team import get_team_membership

    has_lifetime = token.quota_usd is not None

    team_membership = await get_team_membership(token.id, db)

    # Early exit: no quota of any kind
    has_own_monthly = (
        token.monthly_quota_usd is not None and token.monthly_quota_usd > 0
    )
    if not has_lifetime and not has_own_monthly and not team_membership:
        return

    daily_limit_enabled = True
    if team_membership:
        effective_monthly = team_membership.allocated_usd
        effective_policy = team_membership.team.monthly_reset_policy
        effective_start = team_membership.team.monthly_budget_start
        daily_limit_enabled = team_membership.team.daily_limit_enabled
        # Team members are ALWAYS subject to their allocation, even when it is
        # $0 — an allocation of 0 means "no budget", so every request must be
        # blocked. Never treat a team allocation as "unlimited".
        has_monthly = effective_monthly is not None
    else:
        effective_monthly = token.monthly_quota_usd
        effective_policy = token.monthly_reset_policy
        effective_start = token.monthly_quota_start
        # For personal tokens, monthly_quota_usd is optional: None/0 means the
        # token simply has no monthly limit.
        has_monthly = effective_monthly is not None and effective_monthly > 0

    if not has_lifetime and not has_monthly:
        return

    now = datetime.utcnow()
    today = now.date()
    month_start = datetime(today.year, today.month, 1)
    day_start = datetime(today.year, today.month, today.day)

    is_rollover = (effective_policy or "reset") == "rollover"
    rollover_start = effective_start or month_start

    # Determine the start boundary for the monthly sum
    monthly_boundary = rollover_start if is_rollover else month_start

    if has_lifetime:
        # Need full history for lifetime check
        query = select(
            func.coalesce(func.sum(UsageRecord.cost_usd), Decimal("0.00")).label(
                "total"
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            UsageRecord.created_at >= monthly_boundary,
                            UsageRecord.cost_usd,
                        ),
                        else_=Decimal("0.00"),
                    )
                ),
                Decimal("0.00"),
            ).label("monthly"),
            func.coalesce(
                func.sum(
                    case(
                        (UsageRecord.created_at >= day_start, UsageRecord.cost_usd),
                        else_=Decimal("0.00"),
                    )
                ),
                Decimal("0.00"),
            ).label("daily"),
        ).where(UsageRecord.token_id == token.id)
    else:
        # Only monthly/daily needed — scope to monthly_boundary for efficiency
        query = select(
            func.coalesce(func.sum(UsageRecord.cost_usd), Decimal("0.00")).label(
                "monthly"
            ),
            func.coalesce(
                func.sum(
                    case(
                        (UsageRecord.created_at >= day_start, UsageRecord.cost_usd),
                        else_=Decimal("0.00"),
                    )
                ),
                Decimal("0.00"),
            ).label("daily"),
        ).where(
            UsageRecord.token_id == token.id,
            UsageRecord.created_at >= monthly_boundary,
        )

    result = await db.execute(query)
    row = result.one()

    if has_lifetime:
        total_used, monthly_used, daily_used = row.total, row.monthly, row.daily
    else:
        total_used = Decimal("0.00")
        monthly_used, daily_used = row.monthly, row.daily

    if has_lifetime:
        token.calculate_used_usd(total_used)

    # 1. Lifetime quota
    if has_lifetime and total_used >= token.quota_usd:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Lifetime quota exceeded. "
                f"Used: ${total_used:.2f}, Limit: ${token.quota_usd:.2f}"
            ),
        )

    # 2. Monthly quota
    if has_monthly:
        if is_rollover:
            months = _months_elapsed(rollover_start, now)
            cumulative_allowance = effective_monthly * Decimal(str(months))
            if monthly_used >= cumulative_allowance:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Monthly quota exceeded (rollover). "
                        f"Used: ${monthly_used:.2f}, "
                        f"Allowance: ${cumulative_allowance:.2f} "
                        f"({months} months × ${effective_monthly:.2f})"
                    ),
                )
        else:
            if monthly_used >= effective_monthly:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Monthly quota exceeded. "
                        f"Used: ${monthly_used:.2f}, "
                        f"Limit: ${effective_monthly:.2f}"
                    ),
                )

    # 3. Daily limit (auto-calculated from effective monthly quota)
    if has_monthly and daily_limit_enabled:
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        effective_daily = effective_monthly / Decimal(str(days_in_month))

        if daily_used >= effective_daily:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Daily limit exceeded. "
                    f"Used today: ${daily_used:.2f}, Limit: ${effective_daily:.2f}"
                ),
            )

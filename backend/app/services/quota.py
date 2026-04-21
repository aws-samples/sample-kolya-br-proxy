"""Shared quota and spend-limit validation for proxy endpoints."""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token import APIToken
from app.models.usage import UsageRecord


async def _sum_cost(
    db: AsyncSession,
    token_id: UUID,
    since: Optional[datetime] = None,
) -> Decimal:
    stmt = select(func.coalesce(func.sum(UsageRecord.cost_usd), Decimal("0.00"))).where(
        UsageRecord.token_id == token_id
    )
    if since is not None:
        stmt = stmt.where(UsageRecord.created_at >= since)
    result = await db.execute(stmt)
    return result.scalar()


async def validate_quota_and_limits(token: APIToken, db: AsyncSession) -> None:
    """Check total quota, daily limit, and hourly limit.

    Raises HTTPException(429) with a ``type`` field when a limit is hit.
    """
    # Lazy monthly reset
    if token.check_monthly_reset():
        await db.commit()

    # Total quota
    total_used = await _sum_cost(db, token.id)
    token.calculate_used_usd(total_used)

    if token.is_quota_exceeded:
        raise HTTPException(
            status_code=429,
            detail={
                "type": "quota_exceeded",
                "message": (
                    f"Token quota exceeded. "
                    f"Used: ${total_used:.2f}, Quota: ${token.quota_usd:.2f}"
                ),
            },
        )

    if not token.rate_limit_enabled:
        return

    now = datetime.utcnow()

    # Daily spend limit
    if token.daily_spend_limit_usd is not None:
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        daily_used = await _sum_cost(db, token.id, since=today_start)
        if daily_used >= token.daily_spend_limit_usd:
            raise HTTPException(
                status_code=429,
                detail={
                    "type": "daily_spend_limit_exceeded",
                    "message": (
                        f"Daily spend limit reached. "
                        f"Used today: ${daily_used:.2f}, "
                        f"Limit: ${token.daily_spend_limit_usd:.2f}"
                    ),
                },
            )

    # Hourly spend limit
    if token.hourly_spend_limit_usd is not None:
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        hourly_used = await _sum_cost(db, token.id, since=hour_start)
        if hourly_used >= token.hourly_spend_limit_usd:
            raise HTTPException(
                status_code=429,
                detail={
                    "type": "hourly_spend_limit_exceeded",
                    "message": (
                        f"Hourly spend limit reached. "
                        f"Used this hour: ${hourly_used:.2f}, "
                        f"Limit: ${token.hourly_spend_limit_usd:.2f}"
                    ),
                },
            )

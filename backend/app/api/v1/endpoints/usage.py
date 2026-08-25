"""API-key-authenticated, self-scoped quota and usage endpoints."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_token_flexible
from app.core.database import get_db
from app.models.token import APIToken
from app.schemas.usage import QuotaSnapshotResponse, SelfUsageTimeseriesResponse
from app.services.quota import get_quota_snapshot
from app.services.usage_stats import UsageStatsService


router = APIRouter(prefix="/usage")
MAX_QUERY_DAYS = 90


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc)


@router.get("/quota", response_model=QuotaSnapshotResponse)
async def get_self_quota(
    token: APIToken = Depends(get_current_token_flexible),
    db: AsyncSession = Depends(get_db),
) -> QuotaSnapshotResponse:
    """Return quota state for the API key that authenticated this request."""
    snapshot = await get_quota_snapshot(token, db)
    return QuotaSnapshotResponse.from_snapshot(snapshot)


@router.get("/timeseries", response_model=SelfUsageTimeseriesResponse)
async def get_self_usage_timeseries(
    start_date: datetime,
    end_date: datetime,
    token: APIToken = Depends(get_current_token_flexible),
    db: AsyncSession = Depends(get_db),
) -> SelfUsageTimeseriesResponse:
    """Return a half-open UTC daily series scoped to the authenticating key."""
    start = _naive_utc(start_date)
    end = _naive_utc(end_date)
    if start >= end:
        raise HTTPException(
            status_code=400, detail="start_date must be before end_date"
        )
    if end - start > timedelta(days=MAX_QUERY_DAYS):
        raise HTTPException(
            status_code=400,
            detail=f"date range cannot exceed {MAX_QUERY_DAYS} days",
        )

    data = await UsageStatsService(db).get_quota_timeseries(
        token_id=token.id,
        start_date=start,
        end_date=end,
    )
    return SelfUsageTimeseriesResponse(
        start_date=_aware_utc(start),
        end_date=_aware_utc(end),
        data=data,
    )

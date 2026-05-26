"""Usage statistics endpoints."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_allowed_resource_ids, require_permission
from app.core.database import get_db
from app.models.token import APIToken
from app.models.usage import UsageRecord
from app.models.user import User, UserRole
from app.services.usage_stats import UsageStatsService

router = APIRouter()

MAX_QUERY_DAYS = 90


async def _get_accessible_token_ids(
    user: User, db: AsyncSession
) -> Optional[List[UUID]]:
    """Return token IDs the user can view usage for.

    - super_admin: None (no filter, sees all)
    - admin with manage_api_keys=list: only those token IDs
    - admin with manage_api_keys="all"/True: None (sees all)
    """
    if user.role == UserRole.SUPER_ADMIN:
        return None
    allowed_ids = get_allowed_resource_ids(user, "manage_api_keys")
    if allowed_ids is None:
        return None
    return [UUID(tid) for tid in allowed_ids]


def _clamp_date_range(
    start_date: datetime | None,
    end_date: datetime | None,
) -> tuple[datetime, datetime]:
    """Clamp and validate date range to at most MAX_QUERY_DAYS.

    Returns (start_date, end_date) as naive-UTC datetimes.
    Raises HTTPException if the requested range exceeds the limit.
    """
    now = datetime.utcnow()
    earliest_allowed = now - timedelta(days=MAX_QUERY_DAYS + 1)

    if end_date is None:
        end_date = now
    if end_date.tzinfo is not None:
        end_date = end_date.replace(tzinfo=None)

    if start_date is None:
        start_date = earliest_allowed
    if start_date.tzinfo is not None:
        start_date = start_date.replace(tzinfo=None)

    if start_date < earliest_allowed:
        raise HTTPException(
            status_code=400,
            detail=f"start_date cannot be more than {MAX_QUERY_DAYS} days ago",
        )

    if (end_date - start_date).days > MAX_QUERY_DAYS + 1:
        raise HTTPException(
            status_code=400,
            detail=f"Date range cannot exceed {MAX_QUERY_DAYS} days",
        )

    return start_date, end_date


class UsageStatsResponse(BaseModel):
    """Usage statistics response."""

    current_month_cost: str
    current_month_requests: int
    current_month_tokens: int
    last_30_days_cost: str
    last_30_days_requests: int
    total_cost: str
    total_requests: int


class UsageByTokenResponse(BaseModel):
    """Usage statistics grouped by token."""

    token_id: str
    token_name: str
    is_deleted: bool
    is_expired: bool
    total_cost: str
    total_requests: int
    total_tokens: int


class UsageByModelResponse(BaseModel):
    """Usage statistics grouped by model."""

    model: str
    total_cost: str
    total_requests: int
    total_tokens: int


@router.get("/stats", response_model=UsageStatsResponse)
async def get_usage_stats(
    current_user: User = Depends(require_permission("view_usage")),
    db: AsyncSession = Depends(get_db),
    start_date: datetime | None = None,
    end_date: datetime | None = None,
):
    """
    Get usage statistics for the current user.

    Args:
        start_date: Optional start date for custom range
        end_date: Optional end date for custom range

    Returns statistics for:
    - Current month (from 1st of current month) or custom range if provided
    - Last 30 days
    - All time
    """
    now = datetime.utcnow()
    current_month_start = start_date if start_date else datetime(now.year, now.month, 1)
    current_month_end = end_date if end_date else now
    last_30_days_start = now - timedelta(days=30)

    accessible = await _get_accessible_token_ids(current_user, db)

    base_conditions = [UsageRecord.record_type == "usage"]
    if accessible is not None:
        base_conditions.append(UsageRecord.token_id.in_(accessible))

    # Current month stats (or custom range)
    current_month_query = select(
        func.coalesce(func.sum(UsageRecord.cost_usd), Decimal("0.00")).label("cost"),
        func.count(UsageRecord.id).label("requests"),
        func.coalesce(func.sum(UsageRecord.total_tokens), 0).label("tokens"),
    ).where(
        *base_conditions,
        UsageRecord.created_at >= current_month_start,
        UsageRecord.created_at <= current_month_end,
    )
    current_month_result = await db.execute(current_month_query)
    current_month = current_month_result.first()

    # Last 30 days stats
    last_30_days_query = select(
        func.coalesce(func.sum(UsageRecord.cost_usd), Decimal("0.00")).label("cost"),
        func.count(UsageRecord.id).label("requests"),
    ).where(
        *base_conditions,
        UsageRecord.created_at >= last_30_days_start,
    )
    last_30_days_result = await db.execute(last_30_days_query)
    last_30_days = last_30_days_result.first()

    # All time stats
    all_time_query = select(
        func.coalesce(func.sum(UsageRecord.cost_usd), Decimal("0.00")).label("cost"),
        func.count(UsageRecord.id).label("requests"),
    ).where(
        *base_conditions,
    )
    all_time_result = await db.execute(all_time_query)
    all_time = all_time_result.first()

    return UsageStatsResponse(
        current_month_cost=str(current_month[0] if current_month else Decimal("0.00")),
        current_month_requests=current_month[1] if current_month else 0,
        current_month_tokens=current_month[2] if current_month else 0,
        last_30_days_cost=str(last_30_days[0] if last_30_days else Decimal("0.00")),
        last_30_days_requests=last_30_days[1] if last_30_days else 0,
        total_cost=str(all_time[0] if all_time else Decimal("0.00")),
        total_requests=all_time[1] if all_time else 0,
    )


@router.get("/by-token", response_model=list[UsageByTokenResponse])
async def get_usage_by_token(
    current_user: User = Depends(require_permission("view_usage")),
    db: AsyncSession = Depends(get_db),
    token_id: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
):
    """
    Get usage statistics grouped by API token (includes deleted tokens for historical data).

    Args:
        token_id: Optional filter by specific token_id
        start_date: Optional start date for date range
        end_date: Optional end date for date range
    """
    start_date, end_date = _clamp_date_range(start_date, end_date)
    accessible = await _get_accessible_token_ids(current_user, db)

    conditions = [
        UsageRecord.created_at >= start_date,
        UsageRecord.created_at <= end_date,
        UsageRecord.record_type == "usage",
    ]
    if accessible is not None:
        conditions.append(UsageRecord.token_id.in_(accessible))

    query = (
        select(
            UsageRecord.token_id,
            APIToken.name.label("token_name"),
            APIToken.is_deleted,
            APIToken.expires_at,
            func.coalesce(func.sum(UsageRecord.cost_usd), Decimal("0.00")).label(
                "total_cost"
            ),
            func.count(UsageRecord.id).label("total_requests"),
            func.coalesce(func.sum(UsageRecord.total_tokens), 0).label("total_tokens"),
        )
        .join(APIToken, UsageRecord.token_id == APIToken.id)
        .where(*conditions)
        .group_by(
            UsageRecord.token_id,
            APIToken.name,
            APIToken.is_deleted,
            APIToken.expires_at,
        )
        .order_by(func.sum(UsageRecord.cost_usd).desc())
    )

    if token_id:
        try:
            token_uuid = UUID(token_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid token_id format")
        query = query.where(UsageRecord.token_id == token_uuid)

    result = await db.execute(query)
    rows = result.all()

    return [
        UsageByTokenResponse(
            token_id=str(row.token_id),
            token_name=row.token_name,
            is_deleted=row.is_deleted,
            is_expired=row.expires_at is not None
            and row.expires_at < datetime.utcnow(),
            total_cost=str(row.total_cost),
            total_requests=row.total_requests,
            total_tokens=row.total_tokens,
        )
        for row in rows
    ]


@router.get("/by-model", response_model=list[UsageByModelResponse])
async def get_usage_by_model(
    current_user: User = Depends(require_permission("view_usage")),
    db: AsyncSession = Depends(get_db),
    model: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
):
    """
    Get usage statistics grouped by model (includes deleted models for historical data).

    Args:
        model: Optional filter by specific model
        start_date: Optional start date for date range
        end_date: Optional end date for date range
    """
    start_date, end_date = _clamp_date_range(start_date, end_date)
    accessible = await _get_accessible_token_ids(current_user, db)

    conditions = [
        UsageRecord.created_at >= start_date,
        UsageRecord.created_at <= end_date,
        UsageRecord.record_type == "usage",
    ]
    if accessible is not None:
        conditions.append(UsageRecord.token_id.in_(accessible))

    query = (
        select(
            UsageRecord.model,
            func.coalesce(func.sum(UsageRecord.cost_usd), Decimal("0.00")).label(
                "total_cost"
            ),
            func.count(UsageRecord.id).label("total_requests"),
            func.coalesce(func.sum(UsageRecord.total_tokens), 0).label("total_tokens"),
        )
        .where(*conditions)
        .group_by(UsageRecord.model)
        .order_by(func.sum(UsageRecord.cost_usd).desc())
    )

    if model:
        query = query.where(UsageRecord.model == model)

    result = await db.execute(query)
    rows = result.all()

    return [
        UsageByModelResponse(
            model=row.model,
            total_cost=str(row.total_cost),
            total_requests=row.total_requests,
            total_tokens=row.total_tokens,
        )
        for row in rows
    ]


# --- Admin time-series usage statistics endpoints ---


class TimeBucketData(BaseModel):
    """A single time-bucket in a time-series response."""

    time_bucket: str
    call_count: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_cost: str


class AggregatedStatsResponse(BaseModel):
    """Aggregated time-series usage statistics."""

    granularity: str
    start_date: str
    end_date: str
    data: List[TimeBucketData]


class TokenUsageSummary(BaseModel):
    """Per-token usage summary."""

    token_id: str
    token_name: str
    call_count: int
    total_tokens: int
    total_cost: str


class TimeseriesDataPoint(BaseModel):
    """A single data point in a token time-series."""

    time_bucket: str
    value: str | int


class TokenTimeseriesEntry(BaseModel):
    """Time-series data for a single token."""

    token_id: str
    token_name: str
    data: List[TimeseriesDataPoint]


class TokensTimeseriesResponse(BaseModel):
    """Multi-token time-series response."""

    granularity: str
    metric: str
    series: List[TokenTimeseriesEntry]


class UsageBreakdownItem(BaseModel):
    """Single row in the token×model breakdown report."""

    time_bucket: str
    token_id: str
    token_name: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    total_cost: str
    request_count: int


class UsageBreakdownResponse(BaseModel):
    """Token × model breakdown report."""

    granularity: str
    start_date: str
    end_date: str
    data: List[UsageBreakdownItem]


@router.get("/breakdown", response_model=UsageBreakdownResponse)
async def get_usage_breakdown(
    start_date: datetime,
    end_date: datetime,
    granularity: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    token_id: Optional[str] = None,
    model: Optional[str] = None,
    tz: str = Query(
        "UTC", description="IANA timezone for date grouping, e.g. Asia/Shanghai"
    ),
    current_user: User = Depends(require_permission("view_usage")),
    db: AsyncSession = Depends(get_db),
):
    """
    Get usage breakdown by token × model × time bucket.

    Shows how many tokens and how much cost each key spent on each model,
    grouped by daily/weekly/monthly granularity.

    - **start_date / end_date**: Time range (max 90 days)
    - **granularity**: daily, weekly, monthly
    - **token_id**: Optional filter by single token
    - **model**: Optional filter by model name
    - **tz**: Timezone for date grouping
    """
    start_date, end_date = _clamp_date_range(start_date, end_date)

    accessible = await _get_accessible_token_ids(current_user, db)

    service = UsageStatsService(db)
    data = await service.get_usage_breakdown(
        user_id=None,
        accessible_token_ids=accessible,
        start_date=start_date,
        end_date=end_date,
        granularity=granularity,
        token_id=UUID(token_id) if token_id else None,
        model=model,
        tz=tz,
    )

    return UsageBreakdownResponse(
        granularity=granularity,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        data=[UsageBreakdownItem(**d) for d in data],
    )


@router.get("/aggregated-stats", response_model=AggregatedStatsResponse)
async def get_aggregated_stats(
    start_date: datetime,
    end_date: datetime,
    granularity: str = Query("daily", pattern="^(hourly|daily|weekly|monthly)$"),
    token_id: Optional[str] = None,
    token_ids: Optional[str] = Query(None, description="Comma-separated token UUIDs"),
    tz: str = Query(
        "UTC", description="IANA timezone for date grouping, e.g. Asia/Shanghai"
    ),
    current_user: User = Depends(require_permission("view_usage")),
    db: AsyncSession = Depends(get_db),
):
    """
    Get aggregated usage statistics as time-series data.

    - **start_date**: Start of time range (required)
    - **end_date**: End of time range (required)
    - **granularity**: Time bucket size: hourly, daily, weekly, monthly
    - **token_id**: Optional filter by single token UUID
    - **token_ids**: Optional comma-separated token UUIDs (overrides token_id)
    - **tz**: IANA timezone name for grouping (default: UTC)
    """
    start_date, end_date = _clamp_date_range(start_date, end_date)

    parsed_token_id = UUID(token_id) if token_id else None
    parsed_token_ids = (
        [UUID(tid.strip()) for tid in token_ids.split(",") if tid.strip()]
        if token_ids
        else None
    )

    # Scope by accessible tokens instead of user_id
    accessible = await _get_accessible_token_ids(current_user, db)
    # Merge explicit token_ids with access control
    if accessible is not None:
        if parsed_token_ids:
            parsed_token_ids = [t for t in parsed_token_ids if t in accessible]
        else:
            parsed_token_ids = accessible

    service = UsageStatsService(db)
    data = await service.get_aggregated_stats(
        user_id=None,
        start_date=start_date,
        end_date=end_date,
        granularity=granularity,
        token_id=parsed_token_id,
        token_ids=parsed_token_ids,
        tz=tz,
    )

    return AggregatedStatsResponse(
        granularity=granularity,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        data=[TimeBucketData(**d) for d in data],
    )


@router.get("/token-summary", response_model=List[TokenUsageSummary])
async def get_token_summary(
    start_date: datetime,
    end_date: datetime,
    current_user: User = Depends(require_permission("view_usage")),
    db: AsyncSession = Depends(get_db),
):
    """
    Get per-token usage summary for a time period.

    - **start_date**: Start of time range (required)
    - **end_date**: End of time range (required)
    """
    start_date, end_date = _clamp_date_range(start_date, end_date)

    accessible = await _get_accessible_token_ids(current_user, db)

    service = UsageStatsService(db)
    data = await service.get_usage_by_token(
        user_id=None,
        start_date=start_date,
        end_date=end_date,
        token_ids=accessible,
    )

    return [TokenUsageSummary(**d) for d in data]


@router.get("/tokens-timeseries", response_model=TokensTimeseriesResponse)
async def get_tokens_timeseries(
    start_date: datetime,
    end_date: datetime,
    token_ids: str = Query(..., description="Comma-separated token UUIDs"),
    granularity: str = Query("daily", pattern="^(hourly|daily|weekly|monthly)$"),
    metric: str = Query("calls", pattern="^(calls|tokens|cost)$"),
    tz: str = Query(
        "UTC", description="IANA timezone for date grouping, e.g. Asia/Shanghai"
    ),
    current_user: User = Depends(require_permission("view_usage")),
    db: AsyncSession = Depends(get_db),
):
    """
    Get time-series data for multiple tokens (for chart overlay).

    - **start_date**: Start of time range (required)
    - **end_date**: End of time range (required)
    - **token_ids**: Comma-separated list of token UUIDs
    - **granularity**: Time bucket size: hourly, daily, weekly, monthly
    - **metric**: Metric to aggregate: calls, tokens, cost
    - **tz**: IANA timezone name for grouping (default: UTC)
    """
    start_date, end_date = _clamp_date_range(start_date, end_date)

    parsed_ids = [UUID(tid.strip()) for tid in token_ids.split(",") if tid.strip()]

    # Scope by accessible tokens
    accessible = await _get_accessible_token_ids(current_user, db)
    if accessible is not None:
        parsed_ids = [t for t in parsed_ids if t in accessible]

    service = UsageStatsService(db)
    series_dict = await service.get_tokens_timeseries(
        user_id=None,
        token_ids=parsed_ids,
        start_date=start_date,
        end_date=end_date,
        granularity=granularity,
        metric=metric,
        tz=tz,
    )

    series_list = [
        TokenTimeseriesEntry(
            token_id=entry["token_id"],
            token_name=entry["token_name"],
            data=[TimeseriesDataPoint(**dp) for dp in entry["data"]],
        )
        for entry in series_dict.values()
    ]

    return TokensTimeseriesResponse(
        granularity=granularity,
        metric=metric,
        series=series_list,
    )

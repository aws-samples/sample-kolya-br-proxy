"""Usage statistics aggregation service."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token import APIToken
from app.models.usage import UsageRecord


class UsageStatsService:
    """Service for aggregating usage statistics with time-series support."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_aggregated_stats(
        self,
        user_id: UUID,
        start_date: datetime,
        end_date: datetime,
        granularity: str = "daily",
        token_id: Optional[UUID] = None,
        token_ids: Optional[List[UUID]] = None,
        tz: str = "UTC",
    ) -> List[dict]:
        """
        Get aggregated usage statistics as time-series data.

        Args:
            user_id: Owner user ID
            start_date: Start of time range
            end_date: End of time range
            granularity: One of 'hourly', 'daily', 'weekly', 'monthly'
            token_id: Optional filter by single token (deprecated, use token_ids)
            token_ids: Optional filter by multiple tokens
            tz: IANA timezone name for date grouping (e.g., 'Asia/Shanghai')

        Returns:
            List of time-bucket dicts with aggregated metrics.
        """
        trunc_field = self._granularity_to_trunc(granularity)

        time_expr = self._localized_time(UsageRecord.created_at, tz)
        time_bucket = func.date_trunc(trunc_field, time_expr).label("time_bucket")

        query = (
            select(
                time_bucket,
                func.count(UsageRecord.id).label("call_count"),
                func.coalesce(func.sum(UsageRecord.prompt_tokens), 0).label(
                    "total_prompt_tokens"
                ),
                func.coalesce(func.sum(UsageRecord.completion_tokens), 0).label(
                    "total_completion_tokens"
                ),
                func.coalesce(func.sum(UsageRecord.total_tokens), 0).label(
                    "total_tokens"
                ),
                func.coalesce(func.sum(UsageRecord.cost_usd), Decimal("0.0000")).label(
                    "total_cost"
                ),
            )
            .where(
                UsageRecord.user_id == user_id,
                UsageRecord.created_at >= start_date,
                UsageRecord.created_at <= end_date,
            )
            .group_by(time_bucket)
            .order_by(time_bucket)
        )

        if token_ids:
            query = query.where(UsageRecord.token_id.in_(token_ids))
        elif token_id is not None:
            query = query.where(UsageRecord.token_id == token_id)

        result = await self.db.execute(query)
        rows = result.all()

        return [
            {
                "time_bucket": row.time_bucket.isoformat(),
                "call_count": row.call_count,
                "total_prompt_tokens": row.total_prompt_tokens,
                "total_completion_tokens": row.total_completion_tokens,
                "total_tokens": row.total_tokens,
                "total_cost": str(row.total_cost),
            }
            for row in rows
        ]

    async def get_usage_by_token(
        self,
        user_id: UUID,
        start_date: datetime,
        end_date: datetime,
    ) -> List[dict]:
        """
        Get per-token usage summary for a time period.

        Args:
            user_id: Owner user ID
            start_date: Start of time range
            end_date: End of time range

        Returns:
            List of per-token summary dicts.
        """
        query = (
            select(
                UsageRecord.token_id,
                APIToken.name.label("token_name"),
                func.count(UsageRecord.id).label("call_count"),
                func.coalesce(func.sum(UsageRecord.total_tokens), 0).label(
                    "total_tokens"
                ),
                func.coalesce(func.sum(UsageRecord.cost_usd), Decimal("0.0000")).label(
                    "total_cost"
                ),
            )
            .join(APIToken, UsageRecord.token_id == APIToken.id)
            .where(
                UsageRecord.user_id == user_id,
                UsageRecord.created_at >= start_date,
                UsageRecord.created_at <= end_date,
            )
            .group_by(UsageRecord.token_id, APIToken.name)
            .order_by(func.sum(UsageRecord.cost_usd).desc())
        )

        result = await self.db.execute(query)
        rows = result.all()

        return [
            {
                "token_id": str(row.token_id),
                "token_name": row.token_name,
                "call_count": row.call_count,
                "total_tokens": row.total_tokens,
                "total_cost": str(row.total_cost),
            }
            for row in rows
        ]

    async def get_tokens_timeseries(
        self,
        user_id: UUID,
        token_ids: List[UUID],
        start_date: datetime,
        end_date: datetime,
        granularity: str = "daily",
        metric: str = "calls",
        tz: str = "UTC",
    ) -> dict:
        """
        Get time-series data for multiple tokens (for chart overlay).

        Args:
            user_id: Owner user ID
            token_ids: List of token UUIDs to include
            start_date: Start of time range
            end_date: End of time range
            granularity: One of 'hourly', 'daily', 'weekly', 'monthly'
            metric: One of 'calls', 'tokens', 'cost'
            tz: IANA timezone name for date grouping (e.g., 'Asia/Shanghai')

        Returns:
            Dict mapping token_id -> list of time-series data points.
        """
        trunc_field = self._granularity_to_trunc(granularity)

        time_expr = self._localized_time(UsageRecord.created_at, tz)
        time_bucket = func.date_trunc(trunc_field, time_expr).label("time_bucket")

        metric_col = self._metric_to_column(metric)

        query = (
            select(
                UsageRecord.token_id,
                APIToken.name.label("token_name"),
                time_bucket,
                metric_col,
            )
            .join(APIToken, UsageRecord.token_id == APIToken.id)
            .where(
                UsageRecord.user_id == user_id,
                UsageRecord.token_id.in_(token_ids),
                UsageRecord.created_at >= start_date,
                UsageRecord.created_at <= end_date,
            )
            .group_by(UsageRecord.token_id, APIToken.name, time_bucket)
            .order_by(time_bucket)
        )

        result = await self.db.execute(query)
        rows = result.all()

        # Group by token_id
        series: dict = {}
        for row in rows:
            tid = str(row.token_id)
            if tid not in series:
                series[tid] = {
                    "token_id": tid,
                    "token_name": row.token_name,
                    "data": [],
                }
            series[tid]["data"].append(
                {
                    "time_bucket": row.time_bucket.isoformat(),
                    "value": str(row.value) if metric == "cost" else row.value,
                }
            )

        return series

    @staticmethod
    def _localized_time(column, tz: str):
        """Convert a naive-UTC column to a local-time expression for grouping.

        PostgreSQL: column AT TIME ZONE 'UTC' AT TIME ZONE tz
        - First cast: naive → timestamptz (interpreted as UTC)
        - Second cast: timestamptz → naive (converted to target tz)
        """
        if tz and tz != "UTC":
            return func.timezone(tz, func.timezone("UTC", column))
        return column

    @staticmethod
    def _granularity_to_trunc(granularity: str) -> str:
        """Convert granularity parameter to PostgreSQL date_trunc field."""
        mapping = {
            "hourly": "hour",
            "daily": "day",
            "weekly": "week",
            "monthly": "month",
        }
        return mapping.get(granularity, "day")

    @staticmethod
    def _metric_to_column(metric: str):
        """Convert metric parameter to the appropriate SQLAlchemy aggregation."""
        if metric == "tokens":
            return func.coalesce(func.sum(UsageRecord.total_tokens), 0).label("value")
        elif metric == "cost":
            return func.coalesce(
                func.sum(UsageRecord.cost_usd), Decimal("0.0000")
            ).label("value")
        else:  # "calls"
            return func.count(UsageRecord.id).label("value")

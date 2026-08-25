"""Schemas for API-key self-service quota and usage endpoints."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from app.services.quota import QuotaSnapshot


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _decimal_string(value) -> str | None:
    return str(value) if value is not None else None


class QuotaSnapshotResponse(BaseModel):
    """Quota state for the API key that authenticated the request."""

    scope: str
    reset_policy: str
    timezone: Literal["UTC"] = "UTC"
    usage_window_start: datetime
    next_allowance_at: datetime
    rollover_months: int
    monthly_base_limit_usd: str | None
    monthly_effective_allowance_usd: str | None
    monthly_usage_cost_usd: str
    monthly_adjustment_usd: str
    monthly_quota_impact_usd: str
    monthly_remaining_usd: str | None
    daily_limit_enabled: bool
    daily_limit_usd: str | None
    daily_usage_cost_usd: str
    daily_adjustment_usd: str
    daily_quota_impact_usd: str
    lifetime_limit_usd: str | None
    lifetime_usage_cost_usd: str | None
    lifetime_adjustment_usd: str | None
    lifetime_quota_impact_usd: str | None
    lifetime_remaining_usd: str | None
    is_monthly_exceeded: bool
    is_daily_exceeded: bool
    is_lifetime_exceeded: bool
    unpriced_request_count: int
    as_of: datetime

    @classmethod
    def from_snapshot(cls, snapshot: QuotaSnapshot) -> "QuotaSnapshotResponse":
        return cls(
            scope=snapshot.scope,
            reset_policy=snapshot.reset_policy,
            usage_window_start=_utc(snapshot.usage_window_start),
            next_allowance_at=_utc(snapshot.next_allowance_at),
            rollover_months=snapshot.rollover_months,
            monthly_base_limit_usd=_decimal_string(snapshot.monthly_base_limit_usd),
            monthly_effective_allowance_usd=_decimal_string(
                snapshot.monthly_effective_allowance_usd
            ),
            monthly_usage_cost_usd=str(snapshot.monthly_usage_cost_usd),
            monthly_adjustment_usd=str(snapshot.monthly_adjustment_usd),
            monthly_quota_impact_usd=str(snapshot.monthly_quota_impact_usd),
            monthly_remaining_usd=_decimal_string(snapshot.monthly_remaining_usd),
            daily_limit_enabled=snapshot.daily_limit_enabled,
            daily_limit_usd=_decimal_string(snapshot.daily_limit_usd),
            daily_usage_cost_usd=str(snapshot.daily_usage_cost_usd),
            daily_adjustment_usd=str(snapshot.daily_adjustment_usd),
            daily_quota_impact_usd=str(snapshot.daily_quota_impact_usd),
            lifetime_limit_usd=_decimal_string(snapshot.lifetime_limit_usd),
            lifetime_usage_cost_usd=_decimal_string(snapshot.lifetime_usage_cost_usd),
            lifetime_adjustment_usd=_decimal_string(snapshot.lifetime_adjustment_usd),
            lifetime_quota_impact_usd=_decimal_string(
                snapshot.lifetime_quota_impact_usd
            ),
            lifetime_remaining_usd=_decimal_string(snapshot.lifetime_remaining_usd),
            is_monthly_exceeded=snapshot.is_monthly_exceeded,
            is_daily_exceeded=snapshot.is_daily_exceeded,
            is_lifetime_exceeded=snapshot.is_lifetime_exceeded,
            unpriced_request_count=snapshot.unpriced_request_count,
            as_of=_utc(snapshot.as_of),
        )


class SelfUsageBucket(BaseModel):
    """One UTC day of usage for the authenticated API key."""

    time_bucket: datetime
    call_count: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    usage_cost_usd: str
    adjustment_usd: str
    quota_impact_usd: str
    unpriced_request_count: int


class SelfUsageTimeseriesResponse(BaseModel):
    """UTC daily usage series for the authenticated API key."""

    start_date: datetime
    end_date: datetime
    timezone: Literal["UTC"] = "UTC"
    data: list[SelfUsageBucket]

"""Alert rule management and usage-based alert checking."""

import asyncio
import calendar
import logging
import uuid as uuid_mod
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import AlertNotification, AlertRule
from app.models.team import Team, TeamMember
from app.models.token import APIToken
from app.models.usage import UsageRecord

logger = logging.getLogger(__name__)

SOFT_RULES = {
    "monthly_cost",
    "daily_cost",
    "lifetime_cost",
    "hourly_cost",
}
HARD_RULES = {
    "monthly_quota_pct",
    "lifetime_quota_pct",
    "daily_limit_pct",
    "team_budget_pct",
}

RULE_LABELS = {
    "monthly_cost": "Monthly cost reached",
    "daily_cost": "Daily cost reached",
    "lifetime_cost": "Total cost reached",
    "hourly_cost": "Hourly cost reached",
    "monthly_quota_pct": "Monthly quota usage reached",
    "lifetime_quota_pct": "Total quota usage reached",
    "daily_limit_pct": "Daily limit usage reached",
    "team_budget_pct": "Team budget usage reached",
}


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def create_rule(
    db: AsyncSession,
    user_id: UUID,
    alert_type: str,
    rule_key: str,
    threshold_value: Decimal,
    token_id: Optional[UUID] = None,
    team_id: Optional[UUID] = None,
    cooldown_hours: int = 24,
    notify_email: Optional[str] = None,
    notify_in_app: bool = True,
) -> AlertRule:
    if alert_type not in ("soft", "hard"):
        raise ValueError("alert_type must be 'soft' or 'hard'")
    valid_keys = SOFT_RULES if alert_type == "soft" else HARD_RULES
    if rule_key not in valid_keys:
        raise ValueError(f"Invalid rule_key '{rule_key}' for alert_type '{alert_type}'")
    if token_id and team_id:
        raise ValueError("token_id and team_id are mutually exclusive")
    if not token_id and not team_id:
        raise ValueError("Either token_id or team_id must be provided")
    if rule_key == "team_budget_pct" and not team_id:
        raise ValueError("team_budget_pct requires team scope")
    if team_id and rule_key != "team_budget_pct":
        raise ValueError("Team alerts only support team_budget_pct")

    if rule_key in ("monthly_quota_pct", "daily_limit_pct") and token_id:
        tm_result = await db.execute(
            select(TeamMember, Team.daily_limit_enabled)
            .join(Team, TeamMember.team_id == Team.id)
            .where(TeamMember.token_id == token_id)
        )
        row = tm_result.first()
        if rule_key == "monthly_quota_pct":
            if not row or not row[0].allocated_usd:
                raise ValueError(
                    "monthly_quota_pct requires a team token with monthly quota"
                )
        if rule_key == "daily_limit_pct":
            if not row or not row[0].allocated_usd or not row[1]:
                raise ValueError(
                    "daily_limit_pct requires a team token with daily limit enabled"
                )

    rule = AlertRule(
        id=uuid_mod.uuid4(),
        user_id=user_id,
        token_id=token_id,
        team_id=team_id,
        alert_type=alert_type,
        rule_key=rule_key,
        threshold_value=threshold_value,
        cooldown_hours=cooldown_hours,
        notify_email=notify_email,
        notify_in_app=notify_in_app,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


async def update_rule(
    db: AsyncSession,
    rule_id: UUID,
    user_id: UUID,
    **kwargs,
) -> Optional[AlertRule]:
    result = await db.execute(
        select(AlertRule).where(AlertRule.id == rule_id, AlertRule.user_id == user_id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        return None
    for key, value in kwargs.items():
        if value is not None and hasattr(rule, key):
            setattr(rule, key, value)
    rule.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(rule)
    return rule


async def delete_rule(db: AsyncSession, rule_id: UUID, user_id: UUID) -> bool:
    result = await db.execute(
        delete(AlertRule).where(AlertRule.id == rule_id, AlertRule.user_id == user_id)
    )
    await db.commit()
    return result.rowcount > 0


async def list_rules(
    db: AsyncSession,
    user_id: UUID,
    token_id: Optional[UUID] = None,
    team_id: Optional[UUID] = None,
) -> list[AlertRule]:
    query = select(AlertRule).where(AlertRule.user_id == user_id)
    if token_id:
        query = query.where(AlertRule.token_id == token_id)
    if team_id:
        query = query.where(AlertRule.team_id == team_id)
    query = query.order_by(AlertRule.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


async def list_notifications(
    db: AsyncSession,
    user_id: UUID,
    unread_only: bool = False,
    limit: int = 50,
) -> list[AlertNotification]:
    query = select(AlertNotification).where(AlertNotification.user_id == user_id)
    if unread_only:
        query = query.where(AlertNotification.is_read.is_(False))
    query = query.order_by(AlertNotification.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_unread_count(db: AsyncSession, user_id: UUID) -> int:
    result = await db.execute(
        select(func.count(AlertNotification.id)).where(
            AlertNotification.user_id == user_id,
            AlertNotification.is_read.is_(False),
        )
    )
    return result.scalar() or 0


async def mark_read(db: AsyncSession, notification_id: UUID, user_id: UUID) -> bool:
    result = await db.execute(
        update(AlertNotification)
        .where(
            AlertNotification.id == notification_id,
            AlertNotification.user_id == user_id,
        )
        .values(is_read=True)
    )
    await db.commit()
    return result.rowcount > 0


async def mark_all_read(db: AsyncSession, user_id: UUID) -> int:
    result = await db.execute(
        update(AlertNotification)
        .where(
            AlertNotification.user_id == user_id,
            AlertNotification.is_read.is_(False),
        )
        .values(is_read=True)
    )
    await db.commit()
    return result.rowcount


# ---------------------------------------------------------------------------
# Alert check
# ---------------------------------------------------------------------------


def _build_message(
    rule: AlertRule,
    current_value: Decimal,
    scope_name: str,
) -> str:
    label = RULE_LABELS.get(rule.rule_key, rule.rule_key)
    if rule.alert_type == "hard":
        return (
            f"[{scope_name}] {label} {current_value:.1f}%, "
            f"exceeded threshold {rule.threshold_value:.1f}%"
        )
    return (
        f"[{scope_name}] {label} ${current_value:.2f}, "
        f"exceeded threshold ${rule.threshold_value:.2f}"
    )


async def check_alerts_for_usage(
    token_id: UUID,
    user_id: UUID,
    db: AsyncSession,
) -> None:
    """Check all active alert rules after a usage record is committed."""

    # 1. Token-scoped rules
    result = await db.execute(
        select(AlertRule).where(
            AlertRule.user_id == user_id,
            AlertRule.is_active.is_(True),
            AlertRule.token_id == token_id,
        )
    )
    rules = list(result.scalars().all())

    # 2. Team-scoped rules (only if token belongs to a team)
    team_row = (
        await db.execute(
            select(TeamMember.team_id).where(TeamMember.token_id == token_id)
        )
    ).first()
    team_id = team_row[0] if team_row else None

    if team_id:
        team_result = await db.execute(
            select(AlertRule).where(
                AlertRule.user_id == user_id,
                AlertRule.is_active.is_(True),
                AlertRule.team_id == team_id,
            )
        )
        rules.extend(team_result.scalars().all())

    if not rules:
        return

    # 2. Batch cooldown check — single query for all rule IDs
    rule_ids = [r.id for r in rules]
    cutoff = datetime.utcnow() - timedelta(hours=max(r.cooldown_hours for r in rules))
    cooldown_q = (
        select(AlertNotification.alert_rule_id, func.max(AlertNotification.created_at))
        .where(
            AlertNotification.alert_rule_id.in_(rule_ids),
            AlertNotification.created_at >= cutoff,
        )
        .group_by(AlertNotification.alert_rule_id)
    )
    cooldown_result = await db.execute(cooldown_q)
    last_notified: dict[UUID, datetime] = {
        row[0]: row[1] for row in cooldown_result.all()
    }

    # 3. Fetch aggregated usage metrics in a single query
    now = datetime.utcnow()
    today = now.date()
    month_start = datetime(today.year, today.month, 1)
    day_start = datetime(today.year, today.month, today.day)
    hour_start = now - timedelta(hours=1)

    usage_q = select(
        func.coalesce(func.sum(UsageRecord.cost_usd), Decimal("0.00")).label("total"),
        func.coalesce(
            func.sum(
                case(
                    (UsageRecord.created_at >= month_start, UsageRecord.cost_usd),
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
        func.coalesce(
            func.sum(
                case(
                    (UsageRecord.created_at >= hour_start, UsageRecord.cost_usd),
                    else_=Decimal("0.00"),
                )
            ),
            Decimal("0.00"),
        ).label("hourly"),
    ).where(UsageRecord.token_id == token_id)
    usage_result = await db.execute(usage_q)
    usage = usage_result.one()

    # 4. If token is in a team, also get team-level data
    team_monthly_used = Decimal("0.00")
    team_budget = Decimal("0.00")
    team_obj = None
    if team_id:
        team_obj_q = select(Team).where(Team.id == team_id)
        team_obj_result = await db.execute(team_obj_q)
        team_obj = team_obj_result.scalar_one_or_none()
        if team_obj:
            team_budget = team_obj.monthly_budget_usd or Decimal("0.00")
            team_members_q = select(TeamMember.token_id).where(
                TeamMember.team_id == team_id
            )
            tm_result = await db.execute(team_members_q)
            team_token_ids = [r[0] for r in tm_result.all()]
            if team_token_ids:
                team_usage_q = select(
                    func.coalesce(func.sum(UsageRecord.cost_usd), Decimal("0.00"))
                ).where(
                    UsageRecord.token_id.in_(team_token_ids),
                    UsageRecord.created_at >= month_start,
                )
                team_usage_result = await db.execute(team_usage_q)
                team_monthly_used = team_usage_result.scalar() or Decimal("0.00")

    # 5. Get token info for quota values and name
    token_q = select(APIToken).where(APIToken.id == token_id)
    token_result = await db.execute(token_q)
    token_obj = token_result.scalar_one_or_none()
    if not token_obj:
        return

    allocated_usd = Decimal("0.00")
    if team_id:
        alloc_q = select(TeamMember.allocated_usd).where(
            TeamMember.token_id == token_id, TeamMember.team_id == team_id
        )
        alloc_result = await db.execute(alloc_q)
        alloc_row = alloc_result.first()
        if alloc_row:
            allocated_usd = alloc_row[0] or Decimal("0.00")

    effective_monthly = (
        allocated_usd
        if allocated_usd > 0
        else (token_obj.monthly_quota_usd or Decimal("0.00"))
    )

    def get_metric(rule: AlertRule) -> Optional[Decimal]:
        key = rule.rule_key
        if key == "monthly_cost":
            return usage.monthly
        if key == "daily_cost":
            return usage.daily
        if key == "lifetime_cost":
            return usage.total
        if key == "hourly_cost":
            return usage.hourly
        if key == "monthly_quota_pct":
            if effective_monthly <= 0:
                return None
            return (usage.monthly / effective_monthly) * 100
        if key == "lifetime_quota_pct":
            quota = token_obj.quota_usd
            if not quota or quota <= 0:
                return None
            return (usage.total / quota) * 100
        if key == "daily_limit_pct":
            if effective_monthly <= 0:
                return None
            days_in_month = calendar.monthrange(today.year, today.month)[1]
            daily_limit = effective_monthly / Decimal(str(days_in_month))
            if daily_limit <= 0:
                return None
            return (usage.daily / daily_limit) * 100
        if key == "team_budget_pct":
            if team_budget <= 0:
                return None
            return (team_monthly_used / team_budget) * 100
        return None

    # 6. Evaluate rules, collect notifications, commit once
    from app.services.notification import dispatch_alert

    pending_notifications: list[AlertNotification] = []
    pending_emails: list[tuple[str, str]] = []

    for rule in rules:
        try:
            current_value = get_metric(rule)
            if current_value is None:
                continue
            if current_value < rule.threshold_value:
                continue

            # Check cooldown from batched results
            last_time = last_notified.get(rule.id)
            if last_time:
                cooldown_cutoff = now - timedelta(hours=rule.cooldown_hours)
                if last_time >= cooldown_cutoff:
                    continue

            scope_name = token_obj.name
            scope_type = "token"
            scope_id = token_id
            if rule.team_id:
                scope_type = "team"
                scope_id = rule.team_id
                scope_name = team_obj.name if team_obj else "Unknown Team"

            message = _build_message(rule, current_value, scope_name)

            channels: list[str] = []
            if rule.notify_in_app:
                channels.append("in_app")
            if rule.notify_email:
                channels.append("email")
                pending_emails.append((rule.notify_email, message))

            notification = AlertNotification(
                id=uuid_mod.uuid4(),
                user_id=user_id,
                alert_rule_id=rule.id,
                rule_key=rule.rule_key,
                alert_type=rule.alert_type,
                scope_type=scope_type,
                scope_id=scope_id,
                scope_name=scope_name,
                current_value=current_value,
                threshold_value=rule.threshold_value,
                message=message,
                channels_used=",".join(channels),
            )
            pending_notifications.append(notification)

        except Exception:
            logger.warning("Failed to process alert rule %s", rule.id, exc_info=True)

    if pending_notifications:
        db.add_all(pending_notifications)
        try:
            await db.commit()
        except Exception:
            logger.warning("Failed to commit alert notifications", exc_info=True)
            await db.rollback()
            return

    # Send emails in background thread to avoid blocking the event loop
    if pending_emails:
        for email_addrs, message in pending_emails:
            try:
                await asyncio.to_thread(dispatch_alert, message, email_addrs)
            except Exception:
                logger.warning("Failed to send alert email", exc_info=True)

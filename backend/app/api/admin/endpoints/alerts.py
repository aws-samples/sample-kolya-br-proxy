"""Alert rule and notification management endpoints."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_audit_log_service, require_permission
from app.core.database import get_db
from app.models.audit_log import AuditAction
from app.models.user import User
from app.services import alert as alert_service
from app.services.audit_log import AuditLogService

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateAlertRuleRequest(BaseModel):
    alert_type: str
    rule_key: str
    threshold_value: Decimal
    token_id: Optional[str] = None
    team_id: Optional[str] = None
    cooldown_hours: int = 24
    notify_email: Optional[str] = None
    notify_in_app: bool = True


class UpdateAlertRuleRequest(BaseModel):
    threshold_value: Optional[Decimal] = None
    cooldown_hours: Optional[int] = None
    is_active: Optional[bool] = None
    notify_email: Optional[str] = None
    notify_in_app: Optional[bool] = None


class AlertRuleResponse(BaseModel):
    id: str
    user_id: str
    token_id: Optional[str] = None
    team_id: Optional[str] = None
    alert_type: str
    rule_key: str
    threshold_value: str
    cooldown_hours: int
    notify_email: Optional[str] = None
    notify_in_app: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AlertNotificationResponse(BaseModel):
    id: str
    user_id: str
    alert_rule_id: Optional[str] = None
    rule_key: str
    alert_type: str
    scope_type: str
    scope_id: Optional[str] = None
    scope_name: Optional[str] = None
    current_value: str
    threshold_value: str
    message: str
    channels_used: Optional[str] = None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UnreadCountResponse(BaseModel):
    count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rule_to_response(rule) -> AlertRuleResponse:
    return AlertRuleResponse(
        id=str(rule.id),
        user_id=str(rule.user_id),
        token_id=str(rule.token_id) if rule.token_id else None,
        team_id=str(rule.team_id) if rule.team_id else None,
        alert_type=rule.alert_type,
        rule_key=rule.rule_key,
        threshold_value=str(rule.threshold_value),
        cooldown_hours=rule.cooldown_hours,
        notify_email=rule.notify_email,
        notify_in_app=rule.notify_in_app,
        is_active=rule.is_active,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _notification_to_response(n) -> AlertNotificationResponse:
    return AlertNotificationResponse(
        id=str(n.id),
        user_id=str(n.user_id),
        alert_rule_id=str(n.alert_rule_id) if n.alert_rule_id else None,
        rule_key=n.rule_key,
        alert_type=n.alert_type,
        scope_type=n.scope_type,
        scope_id=str(n.scope_id) if n.scope_id else None,
        scope_name=n.scope_name,
        current_value=str(n.current_value),
        threshold_value=str(n.threshold_value),
        message=n.message,
        channels_used=n.channels_used,
        is_read=n.is_read,
        created_at=n.created_at,
    )


# ---------------------------------------------------------------------------
# Rule endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/rules", response_model=AlertRuleResponse, status_code=status.HTTP_201_CREATED
)
async def create_alert_rule(
    request: CreateAlertRuleRequest,
    current_user: User = Depends(require_permission("manage_api_keys")),
    db: AsyncSession = Depends(get_db),
    audit_service: AuditLogService = Depends(get_audit_log_service),
):
    try:
        rule = await alert_service.create_rule(
            db=db,
            user_id=current_user.id,
            alert_type=request.alert_type,
            rule_key=request.rule_key,
            threshold_value=request.threshold_value,
            token_id=UUID(request.token_id) if request.token_id else None,
            team_id=UUID(request.team_id) if request.team_id else None,
            cooldown_hours=request.cooldown_hours,
            notify_email=request.notify_email,
            notify_in_app=request.notify_in_app,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    await audit_service.log(
        action=AuditAction.ALERT_RULE_CREATED,
        user=current_user,
        resource_type="alert_rule",
        resource_id=str(rule.id),
        details={
            "rule_key": rule.rule_key,
            "threshold": str(rule.threshold_value),
            "scope": "team" if rule.team_id else "token",
        },
    )
    return _rule_to_response(rule)


@router.get("/rules", response_model=List[AlertRuleResponse])
async def list_alert_rules(
    token_id: Optional[str] = None,
    team_id: Optional[str] = None,
    current_user: User = Depends(require_permission("manage_api_keys")),
    db: AsyncSession = Depends(get_db),
):
    rules = await alert_service.list_rules(
        db=db,
        user_id=current_user.id,
        token_id=UUID(token_id) if token_id else None,
        team_id=UUID(team_id) if team_id else None,
    )
    return [_rule_to_response(r) for r in rules]


@router.put("/rules/{rule_id}", response_model=AlertRuleResponse)
async def update_alert_rule(
    rule_id: str,
    request: UpdateAlertRuleRequest,
    current_user: User = Depends(require_permission("manage_api_keys")),
    db: AsyncSession = Depends(get_db),
    audit_service: AuditLogService = Depends(get_audit_log_service),
):
    try:
        rule_uuid = UUID(rule_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid rule ID"
        )

    kwargs = request.model_dump(exclude_none=True)
    rule = await alert_service.update_rule(
        db=db, rule_id=rule_uuid, user_id=current_user.id, **kwargs
    )
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alert rule not found"
        )
    await audit_service.log(
        action=AuditAction.ALERT_RULE_UPDATED,
        user=current_user,
        resource_type="alert_rule",
        resource_id=str(rule.id),
        details=kwargs,
    )
    return _rule_to_response(rule)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(
    rule_id: str,
    current_user: User = Depends(require_permission("manage_api_keys")),
    db: AsyncSession = Depends(get_db),
    audit_service: AuditLogService = Depends(get_audit_log_service),
):
    try:
        rule_uuid = UUID(rule_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid rule ID"
        )

    deleted = await alert_service.delete_rule(
        db=db, rule_id=rule_uuid, user_id=current_user.id
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alert rule not found"
        )
    await audit_service.log(
        action=AuditAction.ALERT_RULE_DELETED,
        user=current_user,
        resource_type="alert_rule",
        resource_id=rule_id,
    )
    return None


# ---------------------------------------------------------------------------
# Notification endpoints
# ---------------------------------------------------------------------------


@router.get("/notifications", response_model=List[AlertNotificationResponse])
async def list_notifications(
    unread_only: bool = False,
    limit: int = 50,
    current_user: User = Depends(require_permission("manage_api_keys")),
    db: AsyncSession = Depends(get_db),
):
    notifications = await alert_service.list_notifications(
        db=db, user_id=current_user.id, unread_only=unread_only, limit=min(limit, 200)
    )
    return [_notification_to_response(n) for n in notifications]


@router.get("/notifications/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    current_user: User = Depends(require_permission("manage_api_keys")),
    db: AsyncSession = Depends(get_db),
):
    count = await alert_service.get_unread_count(db=db, user_id=current_user.id)
    return UnreadCountResponse(count=count)


@router.post(
    "/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT
)
async def mark_notification_read(
    notification_id: str,
    current_user: User = Depends(require_permission("manage_api_keys")),
    db: AsyncSession = Depends(get_db),
):
    try:
        n_uuid = UUID(notification_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid notification ID"
        )

    marked = await alert_service.mark_read(
        db=db, notification_id=n_uuid, user_id=current_user.id
    )
    if not marked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
        )
    return None


@router.post("/notifications/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(
    current_user: User = Depends(require_permission("manage_api_keys")),
    db: AsyncSession = Depends(get_db),
):
    await alert_service.mark_all_read(db=db, user_id=current_user.id)
    return None

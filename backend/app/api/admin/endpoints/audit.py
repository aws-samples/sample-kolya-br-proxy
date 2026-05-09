"""Audit log viewing endpoints."""

from datetime import datetime, timedelta
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_audit_log_service,
    get_current_superadmin,
    get_current_user_from_jwt,
)
from app.core.database import get_db
from app.models.audit_log import AuditAction, AuditLog
from app.models.user import User
from app.services.audit_log import AuditLogService

ACTIVITY_ACTIONS = [
    AuditAction.ADMIN_CREATED,
    AuditAction.ADMIN_UPDATED,
    AuditAction.ADMIN_DELETED,
    AuditAction.TOKEN_CREATED,
    AuditAction.TOKEN_UPDATED,
    AuditAction.TOKEN_DELETED,
    AuditAction.TEAM_CREATED,
    AuditAction.TEAM_UPDATED,
    AuditAction.TEAM_DELETED,
    AuditAction.MODEL_UPDATED,
]

router = APIRouter()


class AuditLogResponse(BaseModel):
    """Single audit log entry response."""

    id: str
    user_id: str | None
    action: str
    success: bool
    details: str | None
    error_message: str | None
    ip_address: str | None
    user_agent: str | None
    resource_type: str | None
    resource_id: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class PaginatedAuditLogsResponse(BaseModel):
    """Paginated audit logs response."""

    items: List[AuditLogResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class AuditSummaryResponse(BaseModel):
    """Audit activity summary response."""

    total: int
    success_count: int
    failure_count: int
    action_counts: dict[str, int]


@router.get("", response_model=PaginatedAuditLogsResponse)
async def list_audit_logs(
    current_user: User = Depends(get_current_superadmin),
    audit_service: AuditLogService = Depends(get_audit_log_service),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user_id: UUID | None = None,
    action: AuditAction | None = None,
    success: bool | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
):
    """
    List audit logs with pagination and optional filters.

    - **page**: Page number (1-based)
    - **page_size**: Items per page (max 200)
    - **user_id**: Filter by user ID
    - **action**: Filter by action type
    - **success**: Filter by success/failure
    - **start_date**: Filter from date
    - **end_date**: Filter to date
    """
    logs, total = await audit_service.get_audit_logs(
        page=page,
        page_size=page_size,
        user_id=user_id,
        action=action,
        success=success,
        start_date=start_date,
        end_date=end_date,
    )

    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    items = [
        AuditLogResponse(
            id=str(log.id),
            user_id=str(log.user_id) if log.user_id else None,
            action=log.action.value,
            success=log.success,
            details=log.details,
            error_message=log.error_message,
            ip_address=log.ip_address,
            user_agent=log.user_agent,
            resource_type=log.resource_type,
            resource_id=log.resource_id,
            created_at=log.created_at,
        )
        for log in logs
    ]

    return PaginatedAuditLogsResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/summary", response_model=AuditSummaryResponse)
async def get_audit_summary(
    current_user: User = Depends(get_current_superadmin),
    audit_service: AuditLogService = Depends(get_audit_log_service),
    start_date: datetime | None = None,
    end_date: datetime | None = None,
):
    """
    Get audit activity summary with counts by action type and success/failure breakdown.

    - **start_date**: Filter from date
    - **end_date**: Filter to date
    """
    summary = await audit_service.get_audit_summary(
        start_date=start_date,
        end_date=end_date,
    )

    return AuditSummaryResponse(**summary)


class ActivityItem(BaseModel):
    """Simplified activity entry visible to all admins."""

    id: str
    user_id: str | None
    user_email: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    details: str | None
    created_at: datetime


class PaginatedActivityResponse(BaseModel):
    """Paginated activity feed response."""

    items: List[ActivityItem]
    total: int
    page: int
    page_size: int
    total_pages: int


@router.get("/activity", response_model=PaginatedActivityResponse)
async def list_activity(
    current_user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    days: int = Query(7, ge=1, le=30),
):
    """
    Activity feed visible to all admins.
    Shows only management operations (token/team/model/admin CRUD).
    """
    start_date = datetime.utcnow() - timedelta(days=days)

    base_filter = (
        AuditLog.action.in_(ACTIVITY_ACTIONS),
        AuditLog.created_at >= start_date,
    )

    total_result = await db.execute(select(func.count(AuditLog.id)).where(*base_filter))
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    result = await db.execute(
        select(AuditLog)
        .where(*base_filter)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    logs = list(result.scalars().all())

    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    # Batch load user emails
    user_ids = {log.user_id for log in logs if log.user_id}
    email_map: dict[str, str] = {}
    if user_ids:
        result = await db.execute(
            select(User.id, User.email).where(User.id.in_(user_ids))
        )
        email_map = {str(row.id): row.email for row in result}

    items = [
        ActivityItem(
            id=str(log.id),
            user_id=str(log.user_id) if log.user_id else None,
            user_email=email_map.get(str(log.user_id)) if log.user_id else None,
            action=log.action.value,
            resource_type=log.resource_type,
            resource_id=log.resource_id,
            details=log.details,
            created_at=log.created_at,
        )
        for log in logs
    ]

    return PaginatedActivityResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )

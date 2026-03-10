"""Audit log viewing endpoints."""

from datetime import datetime
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.deps import get_audit_log_service, get_current_user_from_jwt
from app.models.audit_log import AuditAction
from app.models.user import User
from app.services.audit_log import AuditLogService

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
    current_user: User = Depends(get_current_user_from_jwt),
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
    current_user: User = Depends(get_current_user_from_jwt),
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

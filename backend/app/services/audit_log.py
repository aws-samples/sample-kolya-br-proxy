"""
Audit log service for tracking security-sensitive operations.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAction, AuditLog
from app.models.user import User

logger = logging.getLogger(__name__)


class AuditLogService:
    """Service for creating and managing audit logs."""

    def __init__(self, db: AsyncSession):
        """
        Initialize audit log service.

        Args:
            db: Database session
        """
        self.db = db

    async def log(
        self,
        action: AuditAction,
        success: bool = True,
        user: Optional[User] = None,
        user_id: Optional[UUID] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
    ) -> AuditLog:
        """
        Create an audit log entry.

        Args:
            action: Audit action type
            success: Whether the action was successful
            user: Optional User object
            user_id: Optional user ID (if user object not available)
            ip_address: Optional client IP address
            user_agent: Optional client user agent
            details: Optional additional details (will be JSON encoded)
            error_message: Optional error message for failed actions
            resource_type: Optional resource type (e.g., "api_token", "user")
            resource_id: Optional resource ID

        Returns:
            Created AuditLog object
        """
        # Get user_id from user object if provided
        if user and not user_id:
            user_id = user.id

        # Convert details dict to JSON string
        details_json = None
        if details:
            try:
                details_json = json.dumps(details)
            except Exception as e:
                logger.warning(f"Failed to serialize audit log details: {e}")
                details_json = json.dumps({"error": "Failed to serialize details"})

        # Create audit log entry
        audit_log = AuditLog(
            user_id=user_id,
            action=action,
            success=success,
            details=details_json,
            error_message=error_message,
            ip_address=ip_address,
            user_agent=user_agent,
            resource_type=resource_type,
            resource_id=resource_id,
            created_at=datetime.utcnow(),
        )

        self.db.add(audit_log)
        await self.db.commit()
        await self.db.refresh(audit_log)

        # Log to application logger for monitoring
        log_level = logging.INFO if success else logging.WARNING
        logger.log(
            log_level,
            f"Audit: {action.value} - User: {user_id} - IP: {ip_address} - Success: {success}",
        )

        return audit_log

    async def log_login_success(
        self,
        user: User,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        auth_method: Optional[str] = None,
    ) -> AuditLog:
        """Log successful login attempt."""
        return await self.log(
            action=AuditAction.LOGIN_SUCCESS,
            success=True,
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"auth_method": auth_method} if auth_method else None,
        )

    async def log_login_failed(
        self,
        email: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> AuditLog:
        """Log failed login attempt."""
        return await self.log(
            action=AuditAction.LOGIN_FAILED,
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
            error_message=error_message,
            details={"email": email} if email else None,
        )

    async def log_oauth_login_success(
        self,
        user: User,
        provider: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        is_new_user: bool = False,
    ) -> AuditLog:
        """Log successful OAuth login."""
        return await self.log(
            action=AuditAction.OAUTH_LOGIN_SUCCESS,
            success=True,
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"provider": provider, "is_new_user": is_new_user},
        )

    async def log_oauth_login_failed(
        self,
        provider: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> AuditLog:
        """Log failed OAuth login attempt."""
        return await self.log(
            action=AuditAction.OAUTH_LOGIN_FAILED,
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
            error_message=error_message,
            details={"provider": provider},
        )

    async def log_oauth_account_linked(
        self,
        user: User,
        provider: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AuditLog:
        """Log OAuth account linking to existing user."""
        return await self.log(
            action=AuditAction.OAUTH_ACCOUNT_LINKED,
            success=True,
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"provider": provider},
        )

    async def log_token_refresh_success(
        self,
        user: User,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AuditLog:
        """Log successful token refresh."""
        return await self.log(
            action=AuditAction.TOKEN_REFRESH_SUCCESS,
            success=True,
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def log_token_refresh_failed(
        self,
        user_id: Optional[UUID] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> AuditLog:
        """Log failed token refresh attempt."""
        return await self.log(
            action=AuditAction.TOKEN_REFRESH_FAILED,
            success=False,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            error_message=error_message,
        )

    async def log_token_revoked(
        self,
        user: User,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AuditLog:
        """Log token revocation."""
        return await self.log(
            action=AuditAction.TOKEN_REVOKED,
            success=True,
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def log_token_family_revoked(
        self,
        user: User,
        family_id: UUID,
        reason: str,
        ip_address: Optional[str] = None,
    ) -> AuditLog:
        """Log token family revocation (theft detection)."""
        return await self.log(
            action=AuditAction.TOKEN_FAMILY_REVOKED,
            success=True,
            user=user,
            ip_address=ip_address,
            details={"family_id": str(family_id), "reason": reason},
        )

    async def log_token_theft_detected(
        self,
        user: User,
        family_id: UUID,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AuditLog:
        """Log token theft detection (reuse attempt)."""
        return await self.log(
            action=AuditAction.TOKEN_THEFT_DETECTED,
            success=False,
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"family_id": str(family_id)},
        )

    async def log_logout_all_devices(
        self,
        user: User,
        token_count: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AuditLog:
        """Log logout from all devices."""
        return await self.log(
            action=AuditAction.LOGOUT_ALL_DEVICES,
            success=True,
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"tokens_revoked": token_count},
        )

    async def get_audit_logs(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        user_id: Optional[UUID] = None,
        action: Optional[AuditAction] = None,
        success: Optional[bool] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Tuple[List[AuditLog], int]:
        """
        Get paginated audit logs with optional filters.

        Returns:
            Tuple of (audit_log_list, total_count)
        """
        # Base query
        query = select(AuditLog)
        count_query = select(func.count(AuditLog.id))

        # Apply filters
        if user_id is not None:
            query = query.where(AuditLog.user_id == user_id)
            count_query = count_query.where(AuditLog.user_id == user_id)
        if action is not None:
            query = query.where(AuditLog.action == action)
            count_query = count_query.where(AuditLog.action == action)
        if success is not None:
            query = query.where(AuditLog.success == success)
            count_query = count_query.where(AuditLog.success == success)
        if start_date is not None:
            if start_date.tzinfo is not None:
                start_date = start_date.replace(tzinfo=None)
            query = query.where(AuditLog.created_at >= start_date)
            count_query = count_query.where(AuditLog.created_at >= start_date)
        if end_date is not None:
            if end_date.tzinfo is not None:
                end_date = end_date.replace(tzinfo=None)
            query = query.where(AuditLog.created_at <= end_date)
            count_query = count_query.where(AuditLog.created_at <= end_date)

        # Get total count
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Apply pagination and ordering
        offset = (page - 1) * page_size
        query = (
            query.order_by(AuditLog.created_at.desc()).offset(offset).limit(page_size)
        )

        result = await self.db.execute(query)
        logs = list(result.scalars().all())

        return logs, total

    async def get_audit_summary(
        self,
        *,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Get audit activity summary with counts by action and success/failure breakdown.

        Returns:
            Dict with action_counts and success/failure breakdown.
        """
        # Strip timezone info for naive UTC comparison
        if start_date and start_date.tzinfo is not None:
            start_date = start_date.replace(tzinfo=None)
        if end_date and end_date.tzinfo is not None:
            end_date = end_date.replace(tzinfo=None)

        # Counts by action
        action_query = (
            select(
                AuditLog.action,
                func.count(AuditLog.id).label("count"),
            )
            .group_by(AuditLog.action)
            .order_by(func.count(AuditLog.id).desc())
        )

        if start_date:
            action_query = action_query.where(AuditLog.created_at >= start_date)
        if end_date:
            action_query = action_query.where(AuditLog.created_at <= end_date)

        action_result = await self.db.execute(action_query)
        action_counts = {row.action.value: row.count for row in action_result.all()}

        # Success/failure breakdown
        success_query = select(
            AuditLog.success,
            func.count(AuditLog.id).label("count"),
        ).group_by(AuditLog.success)

        if start_date:
            success_query = success_query.where(AuditLog.created_at >= start_date)
        if end_date:
            success_query = success_query.where(AuditLog.created_at <= end_date)

        success_result = await self.db.execute(success_query)
        success_breakdown = {}
        for row in success_result.all():
            key = "success" if row.success else "failure"
            success_breakdown[key] = row.count

        total = sum(success_breakdown.values())

        return {
            "total": total,
            "success_count": success_breakdown.get("success", 0),
            "failure_count": success_breakdown.get("failure", 0),
            "action_counts": action_counts,
        }

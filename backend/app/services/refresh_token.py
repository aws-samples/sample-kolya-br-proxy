"""
Refresh token service for secure token rotation.
Implements token family tracking to detect token theft.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    create_refresh_token,
    generate_token_family_id,
    hash_refresh_token,
)
from app.models.audit_log import AuditAction, AuditLog
from app.models.refresh_token import RefreshToken
from app.models.user import User

logger = logging.getLogger(__name__)
settings = get_settings()


class RefreshTokenService:
    """Service for managing refresh token rotation and revocation."""

    def __init__(self, db: AsyncSession):
        """
        Initialize refresh token service.

        Args:
            db: Database session
        """
        self.db = db

    async def create_refresh_token(
        self,
        user: User,
        parent_token: Optional[RefreshToken] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> tuple[str, RefreshToken]:
        """
        Create a new refresh token with rotation.

        Args:
            user: User object
            parent_token: Optional parent token for rotation chain
            ip_address: Optional client IP address
            user_agent: Optional client user agent

        Returns:
            Tuple of (JWT token string, RefreshToken model)
        """
        # Generate JWT refresh token
        jwt_token = create_refresh_token(data={"sub": str(user.id)})

        # Determine family_id (inherit from parent or create new)
        family_id = (
            parent_token.family_id if parent_token else generate_token_family_id()
        )

        # Hash token for storage
        token_hash = hash_refresh_token(jwt_token)

        # Calculate expiration
        expires_at = datetime.utcnow() + timedelta(
            days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
        )

        # Create database record
        refresh_token = RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            family_id=family_id,
            parent_token_id=parent_token.id if parent_token else None,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        self.db.add(refresh_token)
        await self.db.commit()
        await self.db.refresh(refresh_token)

        return jwt_token, refresh_token

    async def validate_and_rotate_token(
        self,
        jwt_token: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[User], Optional[str]]:
        """
        Validate refresh token and rotate it (issue new one).

        Implements token theft detection:
        - If token is already used (has children), revoke entire family
        - If token is revoked, deny access
        - If token is valid, rotate it

        Args:
            jwt_token: JWT refresh token string
            ip_address: Optional client IP address
            user_agent: Optional client user agent

        Returns:
            Tuple of (new_jwt_token, user, error_message)
            If successful: (token, user, None)
            If failed: (None, None, error_message)
        """
        token_hash = hash_refresh_token(jwt_token)

        # Find token in database
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        token = result.scalar_one_or_none()

        if not token:
            return None, None, "Invalid refresh token"

        # Check if token is expired
        if token.expires_at < datetime.utcnow():
            return None, None, "Refresh token expired"

        # Check if token is revoked
        if token.is_revoked:
            return None, None, "Refresh token has been revoked"

        # TOKEN THEFT DETECTION:
        # If this token already has children, it means it was already used
        # This indicates potential token theft - revoke entire family
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.parent_token_id == token.id)
        )
        children = result.scalars().all()

        if children:
            logger.warning(
                f"Token reuse detected for user {token.user_id}. "
                f"Revoking entire token family {token.family_id}"
            )

            # Log token theft detection
            await self._log_audit(
                action=AuditAction.TOKEN_THEFT_DETECTED,
                user_id=token.user_id,
                success=False,
                ip_address=ip_address,
                user_agent=user_agent,
                details={"family_id": str(token.family_id)},
            )

            await self.revoke_token_family(
                token.family_id, reason="Token reuse detected (potential theft)"
            )
            return None, None, "Token reuse detected - all tokens revoked"

        # Get user
        result = await self.db.execute(select(User).where(User.id == token.user_id))
        user = result.scalar_one_or_none()

        if not user or not user.is_active:
            return None, None, "User not found or inactive"

        # Create new token (rotation)
        new_jwt_token, new_token = await self.create_refresh_token(
            user=user,
            parent_token=token,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        logger.info(f"Refresh token rotated for user {user.id}")

        return new_jwt_token, user, None

    async def revoke_token(self, token_hash: str, reason: Optional[str] = None) -> bool:
        """
        Revoke a specific refresh token.

        Args:
            token_hash: Hash of token to revoke
            reason: Optional reason for revocation

        Returns:
            True if token was revoked, False if not found
        """
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        token = result.scalar_one_or_none()

        if not token:
            return False

        token.is_revoked = True
        token.revoked_at = datetime.utcnow()
        token.revoked_reason = reason

        await self.db.commit()
        logger.info(f"Refresh token {token.id} revoked: {reason}")
        return True

    async def revoke_token_family(
        self, family_id: UUID, reason: Optional[str] = None
    ) -> int:
        """
        Revoke all tokens in a token family.

        Used when token theft is detected.

        Args:
            family_id: Token family UUID
            reason: Optional reason for revocation

        Returns:
            Number of tokens revoked
        """
        result = await self.db.execute(
            select(RefreshToken).where(
                RefreshToken.family_id == family_id, RefreshToken.is_revoked.is_(False)
            )
        )
        tokens = result.scalars().all()

        count = 0
        user_id = None
        for token in tokens:
            if not user_id:
                user_id = token.user_id
            token.is_revoked = True
            token.revoked_at = datetime.utcnow()
            token.revoked_reason = reason
            count += 1

        await self.db.commit()
        logger.warning(f"Revoked {count} tokens in family {family_id}: {reason}")

        # Log family revocation
        if user_id:
            await self._log_audit(
                action=AuditAction.TOKEN_FAMILY_REVOKED,
                user_id=user_id,
                success=True,
                details={"family_id": str(family_id), "count": count, "reason": reason},
            )

        return count

    async def revoke_all_user_tokens(
        self, user_id: UUID, reason: Optional[str] = None
    ) -> int:
        """
        Revoke all refresh tokens for a user.

        Useful for logout all devices or security incidents.

        Args:
            user_id: User UUID
            reason: Optional reason for revocation

        Returns:
            Number of tokens revoked
        """
        result = await self.db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id, RefreshToken.is_revoked.is_(False)
            )
        )
        tokens = result.scalars().all()

        count = 0
        for token in tokens:
            token.is_revoked = True
            token.revoked_at = datetime.utcnow()
            token.revoked_reason = reason
            count += 1

        await self.db.commit()
        logger.info(f"Revoked {count} tokens for user {user_id}: {reason}")
        return count

    async def cleanup_expired_tokens(self) -> int:
        """
        Clean up expired refresh tokens from database.

        Should be run periodically (e.g., daily cron job).

        Returns:
            Number of tokens deleted
        """
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.expires_at < datetime.utcnow())
        )
        tokens = result.scalars().all()

        count = len(tokens)
        for token in tokens:
            await self.db.delete(token)

        await self.db.commit()
        logger.info(f"Cleaned up {count} expired refresh tokens")
        return count

    async def _log_audit(
        self,
        action: AuditAction,
        user_id: Optional[UUID] = None,
        success: bool = True,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        details: Optional[dict] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Internal method to log audit events.

        Args:
            action: Audit action type
            user_id: Optional user ID
            success: Whether the action was successful
            ip_address: Optional client IP address
            user_agent: Optional client user agent
            details: Optional additional details
            error_message: Optional error message
        """
        import json

        details_json = None
        if details:
            try:
                details_json = json.dumps(details)
            except Exception:
                details_json = None

        audit_log = AuditLog(
            user_id=user_id,
            action=action,
            success=success,
            details=details_json,
            error_message=error_message,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=datetime.utcnow(),
        )

        self.db.add(audit_log)
        await self.db.commit()

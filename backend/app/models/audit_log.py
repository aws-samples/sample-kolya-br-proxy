"""Audit log model for tracking security-sensitive operations."""

import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class AuditAction(enum.Enum):
    """Audit log action types."""

    # Authentication
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    LOGOUT_ALL_DEVICES = "logout_all_devices"

    # OAuth
    OAUTH_LOGIN_SUCCESS = "oauth_login_success"
    OAUTH_LOGIN_FAILED = "oauth_login_failed"
    OAUTH_ACCOUNT_LINKED = "oauth_account_linked"

    # Token Operations
    TOKEN_REFRESH_SUCCESS = "token_refresh_success"
    TOKEN_REFRESH_FAILED = "token_refresh_failed"
    TOKEN_REVOKED = "token_revoked"
    TOKEN_FAMILY_REVOKED = "token_family_revoked"
    TOKEN_THEFT_DETECTED = "token_theft_detected"

    # API Token Management
    API_TOKEN_CREATED = "api_token_created"
    API_TOKEN_REVOKED = "api_token_revoked"

    # User Management
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DELETED = "user_deleted"
    PASSWORD_CHANGED = "password_changed"  # pragma: allowlist secret
    EMAIL_VERIFIED = "email_verified"

    # Authorization
    UNAUTHORIZED_ACCESS_ATTEMPT = "unauthorized_access_attempt"
    PERMISSION_DENIED = "permission_denied"


class AuditLog(Base):
    """
    Audit log model for tracking security events.

    Records authentication, authorization, and other security-sensitive operations.
    """

    __tablename__ = "audit_logs"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)

    # User (nullable for anonymous/failed login attempts)
    user_id = Column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Action
    action = Column(Enum(AuditAction), nullable=False, index=True)

    # Result
    success = Column(Boolean, nullable=False, default=True, index=True)

    # Details
    details = Column(Text, nullable=True)  # JSON string with additional details
    error_message = Column(String(500), nullable=True)

    # Request metadata
    ip_address = Column(String(45), nullable=True, index=True)
    user_agent = Column(String(500), nullable=True)

    # Resource identifiers (optional)
    resource_type = Column(String(50), nullable=True)  # e.g., "api_token", "user"
    resource_id = Column(String(255), nullable=True)

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, action={self.action}, user_id={self.user_id})>"

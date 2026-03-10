"""User model for authentication and user management."""

import enum
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Enum, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class AuthMethod(enum.Enum):
    """Authentication method enum."""

    LOCAL = "local"  # Local password authentication
    MICROSOFT = "microsoft"  # Microsoft OAuth
    COGNITO = "cognito"  # AWS Cognito


class User(Base):
    """User model for system authentication and management."""

    __tablename__ = "users"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)  # Nullable for OAuth users
    auth_method = Column(
        Enum(AuthMethod), default=AuthMethod.LOCAL, nullable=False, index=True
    )
    is_active = Column(Boolean, default=True, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    email_verified = Column(Boolean, default=False, nullable=False)

    # Balance and credits
    current_balance = Column(Numeric(10, 2), default=Decimal("0.00"), nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    last_login_at = Column(DateTime, nullable=True)

    # OAuth fields
    microsoft_id = Column(String(255), nullable=True, unique=True)

    # Profile information
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)

    # Relationships
    tokens = relationship(
        "APIToken", back_populates="user", cascade="all, delete-orphan"
    )
    usage_records = relationship(
        "UsageRecord", back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email})>"

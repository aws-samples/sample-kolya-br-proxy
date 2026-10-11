"""API Token model for token management and access control."""

from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, JSON
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class APIToken(Base):
    """API Token model for managing user access tokens."""

    __tablename__ = "api_tokens"

    # Typed with Mapped[] so instances expose Python values (not Column[...])
    # to type checkers. Nullability is spelled out explicitly to keep the
    # schema identical to the previous Column() definitions.
    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # Token information
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    token_hash: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    encrypted_token: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )  # Encrypted token for retrieval

    # Expiration and quotas
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    quota_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    monthly_quota_usd: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    monthly_reset_policy: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    monthly_quota_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    # Access control
    allowed_ips: Mapped[Optional[List[str]]] = mapped_column(
        ARRAY(String), nullable=True
    )

    # Email addresses to notify with this key's value (one key, many users)
    notify_emails: Mapped[Optional[List[str]]] = mapped_column(
        ARRAY(String), nullable=True
    )

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Metadata for additional configuration (renamed from 'metadata' to avoid SQLAlchemy reserved word)
    token_metadata: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)

    # Relationships
    user = relationship("User", back_populates="tokens")
    usage_records = relationship(
        "UsageRecord", back_populates="token", cascade="all, delete-orphan"
    )
    models = relationship("Model", back_populates="token", cascade="all, delete-orphan")
    team_membership = relationship(
        "TeamMember",
        back_populates="token",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<APIToken(id={self.id}, name={self.name}, user_id={self.user_id})>"

    @property
    def is_expired(self) -> bool:
        """Check if token is expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at

    def calculate_used_usd(self, used_amount: Decimal) -> None:
        """
        Helper to calculate quota status with provided used amount.
        Used amount should be calculated separately via query.
        """
        self._cached_used_usd = used_amount

    @property
    def is_quota_exceeded(self) -> bool:
        """Check if token quota is exceeded."""
        if self.quota_usd is None:
            return False
        used = getattr(self, "_cached_used_usd", Decimal("0.00"))
        return used >= self.quota_usd

    @property
    def remaining_quota(self) -> Optional[Decimal]:
        """Get remaining quota in USD."""
        if self.quota_usd is None:
            return None
        used = getattr(self, "_cached_used_usd", Decimal("0.00"))
        return max(Decimal("0.00"), self.quota_usd - used)

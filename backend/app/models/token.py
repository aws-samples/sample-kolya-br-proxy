"""API Token model for token management and access control."""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Numeric, String, JSON
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID, ARRAY
from sqlalchemy.orm import relationship

from app.core.database import Base


class APIToken(Base):
    """API Token model for managing user access tokens."""

    __tablename__ = "api_tokens"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PostgresUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # Token information
    name = Column(String(255), nullable=False)
    token_hash = Column(String(255), unique=True, nullable=False, index=True)
    encrypted_token = Column(
        String(512), nullable=True
    )  # Encrypted token for retrieval

    # Expiration and quotas
    expires_at = Column(DateTime, nullable=True)
    quota_usd = Column(Numeric(10, 2), nullable=True)

    # Monthly auto-recharge
    monthly_quota_usd = Column(Numeric(10, 2), nullable=True)
    monthly_quota_enabled = Column(Boolean, default=False, nullable=False)
    last_quota_reset_at = Column(DateTime, nullable=True)

    # Spend rate limits
    daily_spend_limit_usd = Column(Numeric(10, 2), nullable=True)
    hourly_spend_limit_usd = Column(Numeric(10, 2), nullable=True)
    rate_limit_enabled = Column(Boolean, default=False, nullable=False)

    # Access control
    allowed_ips = Column(ARRAY(String), nullable=True)

    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    last_used_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)

    # Metadata for additional configuration (renamed from 'metadata' to avoid SQLAlchemy reserved word)
    token_metadata = Column(JSON, nullable=True)

    # Relationships
    user = relationship("User", back_populates="tokens")
    usage_records = relationship(
        "UsageRecord", back_populates="token", cascade="all, delete-orphan"
    )
    models = relationship("Model", back_populates="token", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<APIToken(id={self.id}, name={self.name}, user_id={self.user_id})>"

    def check_monthly_reset(self) -> bool:
        """Lazy monthly quota reset. Returns True if reset happened."""
        if not self.monthly_quota_enabled or not self.monthly_quota_usd:
            return False
        now = datetime.utcnow()
        if self.last_quota_reset_at is None or (
            now.year != self.last_quota_reset_at.year
            or now.month != self.last_quota_reset_at.month
        ):
            self.quota_usd = self.monthly_quota_usd
            self.last_quota_reset_at = now
            return True
        return False

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

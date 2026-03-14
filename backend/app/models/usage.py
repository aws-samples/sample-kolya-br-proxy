"""Usage tracking model for API usage and billing."""

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, JSON
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class UsageRecord(Base):
    """Usage record model for tracking API usage and costs."""

    __tablename__ = "usage_records"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PostgresUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    token_id = Column(
        PostgresUUID(as_uuid=True), ForeignKey("api_tokens.id"), nullable=False
    )

    # Request information
    request_id = Column(String(255), nullable=False, index=True)
    model = Column(String(100), nullable=False)

    # Token usage
    prompt_tokens = Column(Integer, default=0, nullable=False)
    completion_tokens = Column(Integer, default=0, nullable=False)
    total_tokens = Column(Integer, default=0, nullable=False)
    cache_creation_input_tokens = Column(Integer, default=0, nullable=False)
    cache_read_input_tokens = Column(Integer, default=0, nullable=False)

    # Cost information
    cost_usd = Column(Numeric(10, 4), default=Decimal("0.0000"), nullable=False)

    # Request metadata (renamed from 'metadata' to avoid SQLAlchemy reserved word)
    request_metadata = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    user = relationship("User", back_populates="usage_records")
    token = relationship("APIToken", back_populates="usage_records")

    def __repr__(self) -> str:
        return (
            f"<UsageRecord(id={self.id}, model={self.model}, cost_usd={self.cost_usd})>"
        )

    @property
    def cost_per_token(self) -> Decimal:
        """Calculate cost per token."""
        if self.total_tokens == 0:
            return Decimal("0.0000")
        return self.cost_usd / Decimal(str(self.total_tokens))

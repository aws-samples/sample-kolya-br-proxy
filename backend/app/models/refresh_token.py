"""Refresh token model for JWT token rotation."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class RefreshToken(Base):
    """
    Refresh token model for secure token rotation.

    Implements token family tracking to detect token theft.
    Each refresh creates a new token and revokes the old one.
    """

    __tablename__ = "refresh_tokens"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)

    # User relationship
    user_id = Column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Token data
    token_hash = Column(String(64), unique=True, nullable=False, index=True)

    # Token family tracking (for detecting token theft)
    family_id = Column(PostgresUUID(as_uuid=True), nullable=False, index=True)
    parent_token_id = Column(
        PostgresUUID(as_uuid=True),
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)

    # Revocation
    is_revoked = Column(Boolean, default=False, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    revoked_reason = Column(String(255), nullable=True)

    # Metadata
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)

    # Relationships
    user = relationship("User", back_populates="refresh_tokens")
    children = relationship(
        "RefreshToken",
        back_populates="parent",
        foreign_keys=[parent_token_id],
    )
    parent = relationship(
        "RefreshToken",
        back_populates="children",
        remote_side=[id],
        foreign_keys=[parent_token_id],
    )

    def __repr__(self) -> str:
        return f"<RefreshToken(id={self.id}, user_id={self.user_id}, revoked={self.is_revoked})>"

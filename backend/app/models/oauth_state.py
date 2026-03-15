"""
OAuth state model for CSRF protection.
Stores temporary OAuth state parameters.
"""

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.core.database import Base


class OAuthState(Base):
    """
    OAuth state for CSRF protection.

    Stores temporary state parameters used in OAuth flows.
    States expire after 10 minutes for security.
    """

    __tablename__ = "oauth_states"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    state = Column(String, unique=True, nullable=False, index=True)
    provider = Column(String, nullable=False)  # e.g., "microsoft"
    code_verifier = Column(String(128), nullable=True)  # PKCE code_verifier
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(
        DateTime,
        default=lambda: datetime.utcnow() + timedelta(minutes=10),
        nullable=False,
    )

    def is_expired(self) -> bool:
        """Check if state has expired."""
        return datetime.utcnow() > self.expires_at

    def __repr__(self):
        return f"<OAuthState {self.state[:8]}... ({self.provider})>"

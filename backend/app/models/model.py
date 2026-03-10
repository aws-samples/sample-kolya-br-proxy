"""
Model configuration database model.
Stores models associated with API tokens.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class Model(Base):
    """
    Model configuration.

    Stores which models are enabled for specific API tokens.
    Each model belongs to one API token.
    """

    __tablename__ = "models"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    token_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey("api_tokens.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_name = Column(String, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    # Relationship
    token = relationship("APIToken", back_populates="models")

    def __repr__(self):
        return f"<Model {self.model_name} (token_id={self.token_id})>"

"""System configuration model for application settings."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID

from app.core.database import Base


class SystemConfig(Base):
    """System configuration model for storing application settings."""

    __tablename__ = "system_configs"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)

    # Configuration key-value
    key = Column(String(255), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=True)
    description = Column(Text, nullable=True)

    # Visibility
    is_public = Column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<SystemConfig(key={self.key}, value={self.value[:50]}...)>"

"""Entra ID group mapping model."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, Enum, Integer, JSON, String
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID

from app.core.database import Base
from app.models.user import UserRole


class EntraGroupMapping(Base):
    __tablename__ = "entra_group_mappings"

    id = Column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid4)
    entra_group_id = Column(String(255), unique=True, nullable=False, index=True)
    group_name = Column(String(255), nullable=False)
    role = Column(
        Enum(UserRole, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=UserRole.ADMIN,
    )
    permissions = Column(JSON, nullable=True)
    priority = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

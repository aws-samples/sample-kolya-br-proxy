"""Alert rule and notification models for usage alerting."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    token_id = Column(
        UUID(as_uuid=True),
        ForeignKey("api_tokens.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    team_id = Column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    alert_type = Column(String(20), nullable=False)
    rule_key = Column(String(50), nullable=False)
    threshold_value = Column(Numeric(12, 4), nullable=False)

    cooldown_hours = Column(Integer, nullable=False, default=24)

    notify_email = Column(Text, nullable=True)
    notify_phone = Column(Text, nullable=True)
    notify_in_app = Column(Boolean, nullable=False, default=True)

    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "NOT (token_id IS NOT NULL AND team_id IS NOT NULL)",
            name="ck_alert_rules_scope_exclusive",
        ),
    )

    user = relationship("User", foreign_keys=[user_id])
    token = relationship("APIToken", foreign_keys=[token_id])
    team = relationship("Team", foreign_keys=[team_id])
    notifications = relationship(
        "AlertNotification", back_populates="alert_rule", passive_deletes=True
    )


class AlertNotification(Base):
    __tablename__ = "alert_notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    alert_rule_id = Column(
        UUID(as_uuid=True),
        ForeignKey("alert_rules.id", ondelete="SET NULL"),
        nullable=True,
    )

    rule_key = Column(String(50), nullable=False)
    alert_type = Column(String(20), nullable=False)
    scope_type = Column(String(20), nullable=False)
    scope_id = Column(UUID(as_uuid=True), nullable=True)
    scope_name = Column(String(255), nullable=True)

    current_value = Column(Numeric(12, 4), nullable=False)
    threshold_value = Column(Numeric(12, 4), nullable=False)
    message = Column(Text, nullable=False)
    channels_used = Column(String(100), nullable=True)

    is_read = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_alert_notifications_user_created", "user_id", "created_at"),
        Index("ix_alert_notifications_user_read", "user_id", "is_read"),
    )

    user = relationship("User", foreign_keys=[user_id])
    alert_rule = relationship(
        "AlertRule", back_populates="notifications", foreign_keys=[alert_rule_id]
    )

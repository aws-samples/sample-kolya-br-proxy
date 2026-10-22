"""Latest result of comparing hardcoded model-card prices with the live card."""

from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, String

from app.core.database import Base


class ModelCardPriceCheck(Base):
    __tablename__ = "model_card_price_checks"

    model_id = Column(String(255), primary_key=True)
    source_url = Column(String(500), nullable=False)
    # "ok" | "mismatch" | "parse_error"
    status = Column(String(20), nullable=False)
    issues = Column(JSON, nullable=False, default=list)
    checked_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # When status/issues last changed; notifications fire only on change.
    changed_at = Column(DateTime, nullable=False, default=datetime.utcnow)

"""
Model pricing database model.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Numeric, DateTime, UniqueConstraint
from app.core.database import Base


class ModelPricing(Base):
    """Model pricing information."""

    __tablename__ = "model_pricing"

    id = Column(Integer, primary_key=True, index=True)
    model_id = Column(String(255), nullable=False, index=True)
    region = Column(String(50), nullable=False, index=True)
    input_price_per_token = Column(Numeric(precision=20, scale=10), nullable=False)
    output_price_per_token = Column(Numeric(precision=20, scale=10), nullable=False)
    # Cached input price (used by Gemini implicit cache; None = fallback to input * 0.25)
    cached_input_price_per_token = Column(Numeric(precision=20, scale=10), nullable=True)
    currency = Column(String(10), nullable=False, default="USD")
    source = Column(String(50), nullable=False)  # 'api' or 'scraper'
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("model_id", "region", name="uq_model_region"),)

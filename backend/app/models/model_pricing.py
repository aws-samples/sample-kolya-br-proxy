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
    # Published cache-read rate; None = provider default ratio of the input price.
    cached_input_price_per_token = Column(
        Numeric(precision=20, scale=10), nullable=True
    )
    # Published cache-write rate (e.g. $0 for Nova); None = TTL multiplier.
    cache_write_price_per_token = Column(Numeric(precision=20, scale=10), nullable=True)
    # Long-context band: when total input tokens exceed the threshold, the whole
    # request bills at these rates. All None = the model has a single band.
    long_context_threshold = Column(Integer, nullable=True)
    long_input_price_per_token = Column(Numeric(precision=20, scale=10), nullable=True)
    long_output_price_per_token = Column(Numeric(precision=20, scale=10), nullable=True)
    long_cached_input_price_per_token = Column(
        Numeric(precision=20, scale=10), nullable=True
    )
    currency = Column(String(10), nullable=False, default="USD")
    source = Column(String(50), nullable=False)  # 'api' or 'scraper'
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("model_id", "region", name="uq_model_region"),)

    # Owned by each source row: a refresh that omits them clears them.
    SOURCE_OWNED_FIELDS = (
        "cache_write_price_per_token",
        "long_context_threshold",
        "long_input_price_per_token",
        "long_output_price_per_token",
        "long_cached_input_price_per_token",
    )

    def apply_source_rates(self, data: dict) -> None:
        """Replace cache-write and long-context rates with *data*'s."""
        for field in self.SOURCE_OWNED_FIELDS:
            setattr(self, field, data.get(field))

"""Per-modality unit prices for Bedrock embedding models.

Embedding models are not priced like chat models: AWS bills text tokens or
text requests, images, and seconds of audio/video separately. Each row stores
one ``(model, region, unit)`` price; units are defined in
``app.services.embedding_pricing.EMBEDDING_UNITS``.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, Numeric, String, UniqueConstraint

from app.core.database import Base


class EmbeddingPricing(Base):
    __tablename__ = "embedding_pricing"
    __table_args__ = (
        UniqueConstraint(
            "model_id", "region", "unit", name="uq_embedding_pricing_model_region_unit"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    model_id = Column(String(255), nullable=False, index=True)
    region = Column(String(50), nullable=False)
    unit = Column(String(32), nullable=False)
    price_per_unit = Column(Numeric(precision=24, scale=14), nullable=False)
    currency = Column(String(10), nullable=False, default="USD")
    source = Column(String(50), nullable=False)
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

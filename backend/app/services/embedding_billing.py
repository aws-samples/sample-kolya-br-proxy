# pyright: reportMissingImports=false
"""Per-modality metering and cost for text and image embeddings.

AWS bills the two supported models in different units:

* Nova Multimodal Embeddings: text tokens and (standard) images.
* Marengo Embed 3.0: text requests and images.

A quantity that cannot be measured (Nova text without a token count) is
listed in ``unknown_units`` instead of being guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.schemas.embeddings import CanonicalEmbeddingRequest, CanonicalEmbeddingResult
from app.services.embedding_models import NOVA_MODEL_ID
from app.services.embedding_pricing import (
    IMAGE,
    STANDARD_IMAGE,
    TEXT_REQUEST,
    TEXT_TOKEN,
)


@dataclass
class EmbeddingMetering:
    units: dict[str, Decimal] = field(default_factory=dict)
    unknown_units: list[str] = field(default_factory=list)

    def add(self, unit: str, quantity: Decimal | int) -> None:
        self.units[unit] = self.units.get(unit, Decimal(0)) + Decimal(quantity)


@dataclass
class EmbeddingCost:
    total_usd: Decimal
    missing_price_units: list[str]


def meter_embedding(
    request: CanonicalEmbeddingRequest, result: CanonicalEmbeddingResult
) -> EmbeddingMetering:
    """Count billable units for one completed embedding request."""
    metering = EmbeddingMetering()
    is_nova = request.model == NOVA_MODEL_ID
    texts = sum(1 for item in request.inputs if item.type == "text")
    images = len(request.inputs) - texts

    if images:
        metering.add(STANDARD_IMAGE if is_nova else IMAGE, images)
    if texts:
        if not is_nova:
            metering.add(TEXT_REQUEST, texts)
        elif result.input_tokens > 0:
            metering.add(TEXT_TOKEN, result.input_tokens)
        else:
            metering.unknown_units.append(TEXT_TOKEN)
    return metering


def price_embedding(
    metering: EmbeddingMetering, prices: dict[str, Decimal]
) -> EmbeddingCost:
    """Multiply metered quantities by unit prices without intermediate rounding."""
    total = Decimal(0)
    missing: list[str] = []
    for unit, quantity in metering.units.items():
        price = prices.get(unit)
        if price is None:
            missing.append(unit)
            continue
        total += quantity * price
    return EmbeddingCost(total_usd=total, missing_price_units=missing)

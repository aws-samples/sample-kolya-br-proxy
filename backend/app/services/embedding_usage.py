# pyright: reportMissingImports=false, reportArgumentType=false
"""Usage persistence for ``/v1/embeddings`` requests."""

import logging
from decimal import Decimal
from typing import cast

from app.core.config import get_settings
from app.core.database import get_db
from app.models.token import APIToken
from app.models.usage import UsageRecord
from app.schemas.embeddings import CanonicalEmbeddingRequest, CanonicalEmbeddingResult
from app.services.embedding_billing import meter_embedding, price_embedding
from app.services.embedding_pricing import get_embedding_prices

logger = logging.getLogger(__name__)

# Matches usage_records.cost_usd Numeric(20, 10).
_COST_SCALE = Decimal("0.0000000001")


async def record_embedding_usage(
    *,
    token: APIToken,
    model: str,
    request_id: str,
    request: CanonicalEmbeddingRequest,
    result: CanonicalEmbeddingResult,
) -> None:
    """Persist auditable embedding usage without storing vectors or images.

    Cost is metered per modality (text tokens or requests, images) against
    ``embedding_pricing`` and stored in ``usage_records.cost_usd`` at the
    column's ten decimal places.
    """
    async for db in get_db():
        try:
            metering = meter_embedding(request, result)
            # Price where the request actually ran (see EmbeddingService).
            region = get_settings().EMBEDDING_REGION
            prices, pricing_region = await get_embedding_prices(db, model, region)
            cost = price_embedding(metering, prices)

            notes: list[str] = []
            if cost.missing_price_units:
                notes.append("embedding_pricing_missing")
                logger.error(
                    "Embedding prices missing for %s; those units are recorded at zero cost",
                    cost.missing_price_units,
                    extra={"request_id": request_id, "model": model},
                )
            if metering.unknown_units:
                notes.append("embedding_billable_units_unavailable")
            note = ",".join(notes) or None
            cost_usd = cost.total_usd.quantize(_COST_SCALE)

            usage = UsageRecord(
                user_id=cast(object, token.user_id),
                token_id=cast(object, token.id),
                model=model,
                request_id=request_id,
                prompt_tokens=result.input_tokens,
                completion_tokens=0,
                total_tokens=result.input_tokens,
                cost_usd=cost_usd,
                note=note,
                request_metadata={
                    "operation": "embedding",
                    "input_count": len(request.inputs),
                    "input_types": [item.type for item in request.inputs],
                    "vector_count": len(result.vectors),
                    "dimensions": request.dimensions,
                    "billable_units": {
                        unit: str(quantity) for unit, quantity in metering.units.items()
                    },
                    "unknown_units": metering.unknown_units,
                    "missing_price_units": cost.missing_price_units,
                    "pricing_region": pricing_region,
                },
            )
            db.add(usage)
            await db.commit()
            try:
                from app.services.alert import check_alerts_for_usage

                await check_alerts_for_usage(
                    token_id=cast(object, token.id),
                    user_id=cast(object, token.user_id),
                    db=db,
                )
            except Exception:
                logger.warning("Embedding usage alert check failed", exc_info=True)
        except Exception:
            await db.rollback()
            logger.error("Failed to record embedding usage", exc_info=True)
        finally:
            await db.close()
        break

"""
Admin endpoints for pricing management.
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.core.database import get_db
from app.services.pricing import (
    ModelPricing as PricingService,
    db_has_long_band,
    db_rates_for_band,
    effective_db_rates,
    get_official_profile_pricing,
)
from app.services.pricing_updater import PricingUpdater
from app.api.deps import get_current_superadmin
from app.models.user import User
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/update")
async def update_pricing(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
):
    """
    Manually trigger pricing update from AWS sources.

    This endpoint fetches the latest pricing from:
    1. AWS Price List API (primary)
    2. AWS Bedrock pricing page (fallback)

    Returns:
        Update statistics
    """
    try:
        updater = PricingUpdater(db)
        stats = await updater.update_all_pricing()

        return {
            "success": True,
            "message": f"Updated {stats['updated']} models from {stats['source']}",
            "stats": stats,
        }
    except Exception as e:
        logger.error(f"Failed to update pricing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _m(value):
    return None if value is None else str(value * 1_000_000)


def _tiers(rate_list):
    return [
        {
            "input_price_per_1m": _m(rates.input),
            "cache_write_price_per_1m": _m(rates.cache_write),
            "cache_read_price_per_1m": _m(rates.cache_read),
            "output_price_per_1m": _m(rates.output),
        }
        for rates in rate_list
    ]


@router.get("/models/{model_id}")
async def get_model_pricing(
    model_id: str,
    region: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
):
    """
    Get pricing information for a specific model.

    Args:
        model_id: Model identifier
        region: AWS region (default: "default")

    Returns:
        Pricing information
    """
    effective_region = region or get_settings().AWS_REGION

    # Catalogued profiles are billed from model-card rates regardless of any
    # DB row, so report exactly those rates (both context bands).
    official = get_official_profile_pricing(model_id)
    if official is not None:
        tiers = [official.short] + ([official.long] if official.long else [])
        ultrafast = get_official_profile_pricing(model_id, "ultrafast")
        ultrafast_tiers = (
            [ultrafast.short] + ([ultrafast.long] if ultrafast.long else [])
            if ultrafast is not None and ultrafast is not official
            else []
        )

        return {
            "model_id": model_id,
            "region": effective_region,
            "input_price_per_token": str(official.short.input),
            "output_price_per_token": str(official.short.output),
            "input_price_per_1m": _m(official.short.input),
            "output_price_per_1m": _m(official.short.output),
            "long_context_threshold": official.long_context_threshold,
            "context_tiers": _tiers(tiers),
            "ultrafast_context_tiers": _tiers(ultrafast_tiers) or None,
            "source": "aws-model-card",
            "source_url": official.source_url,
            "currency": "USD",
        }

    record = await PricingUpdater(db).get_pricing_record(model_id, effective_region)

    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Pricing not found for model: {model_id}, region: {effective_region}"
            ),
        )

    input_price = Decimal(str(record.input_price_per_token))
    output_price = Decimal(str(record.output_price_per_token))
    # Same rates billing applies (published or fallback cache rates, 5m write).
    write_5m = PricingService.CACHE_WRITE_MULTIPLIER["5m"]
    bands = [False] + ([True] if db_has_long_band(record) else [])
    db_tiers = [
        effective_db_rates(model_id, db_rates_for_band(record, long_band), write_5m)
        for long_band in bands
    ]

    return {
        "model_id": model_id,
        "region": effective_region,
        "input_price_per_token": str(input_price),
        "output_price_per_token": str(output_price),
        "input_price_per_1m": str(input_price * 1_000_000),
        "output_price_per_1m": str(output_price * 1_000_000),
        "long_context_threshold": record.long_context_threshold
        if len(bands) > 1
        else None,
        "context_tiers": _tiers(db_tiers),
        "source": record.source,
        "currency": "USD",
    }

"""
Admin endpoints for pricing management.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
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
        # Refresh the mantle (OpenAI) model registry first so pricing rows for
        # newly launched models can be matched in this same update.
        from app.services.mantle_models import refresh_mantle_registry

        try:
            await refresh_mantle_registry()
        except Exception as e:
            logger.warning(f"Mantle model discovery failed (non-fatal): {e}")

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


@router.get("/models/{model_id}")
async def get_model_pricing(
    model_id: str,
    region: str = None,
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
    updater = PricingUpdater(db)
    pricing = await updater.get_pricing(model_id, region)

    if not pricing:
        raise HTTPException(
            status_code=404,
            detail=f"Pricing not found for model: {model_id}, region: {region}",
        )

    input_price, output_price = pricing

    return {
        "model_id": model_id,
        "region": region,
        "input_price_per_token": str(input_price),
        "output_price_per_token": str(output_price),
        "input_price_per_1m": str(input_price * 1_000_000),
        "output_price_per_1m": str(output_price * 1_000_000),
        "currency": "USD",
    }

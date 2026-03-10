"""
Admin endpoints for monitoring - pricing table display with caching.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.api.deps import get_current_user_from_jwt
from app.models.user import User
from app.models.model_pricing import ModelPricing as ModelPricingModel
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Cache for pricing table data
_pricing_cache: Optional[Dict[str, Any]] = None
_cache_timestamp: Optional[datetime] = None
CACHE_DURATION = timedelta(hours=6)


def _is_cache_valid() -> bool:
    """Check if cache is still valid."""
    if _pricing_cache is None or _cache_timestamp is None:
        return False
    return datetime.utcnow() - _cache_timestamp < CACHE_DURATION


async def _fetch_pricing_table(db: AsyncSession) -> List[Dict[str, Any]]:
    """Fetch all pricing data from database."""
    result = await db.execute(
        select(ModelPricingModel).order_by(
            ModelPricingModel.model_id, ModelPricingModel.region
        )
    )
    pricing_records = result.scalars().all()

    pricing_list = []
    for record in pricing_records:
        pricing_list.append(
            {
                "model_id": record.model_id,
                "region": record.region,
                "input_price_per_token": str(record.input_price_per_token),
                "output_price_per_token": str(record.output_price_per_token),
                "input_price_per_1k": str(record.input_price_per_token * 1_000),
                "output_price_per_1k": str(record.output_price_per_token * 1_000),
                "input_price_per_1m": str(record.input_price_per_token * 1_000_000),
                "output_price_per_1m": str(record.output_price_per_token * 1_000_000),
                "source": record.source,
                "last_updated": record.last_updated.isoformat()
                if record.last_updated
                else None,
            }
        )

    return pricing_list


@router.get("/pricing-table")
async def get_pricing_table(
    force_refresh: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_from_jwt),
):
    """
    Get complete pricing table for all models and regions.

    This endpoint returns cached data (6 hours) unless force_refresh=true.

    Args:
        force_refresh: Force refresh cache from database

    Returns:
        Pricing table with cache metadata
    """
    global _pricing_cache, _cache_timestamp

    try:
        # Check if we need to refresh cache
        if force_refresh or not _is_cache_valid():
            logger.info("Fetching pricing table from database...")
            pricing_list = await _fetch_pricing_table(db)

            # Update cache
            _pricing_cache = {
                "total_records": len(pricing_list),
                "pricing_data": pricing_list,
                "cache_info": {
                    "cached_at": datetime.utcnow().isoformat(),
                    "cache_duration_hours": 6,
                    "expires_at": (datetime.utcnow() + CACHE_DURATION).isoformat(),
                },
            }
            _cache_timestamp = datetime.utcnow()
            logger.info(f"Pricing table cached: {len(pricing_list)} records")
        else:
            logger.info("Returning cached pricing table")

        # Add cache status to response
        response = _pricing_cache.copy()
        response["cache_info"]["is_cached"] = not force_refresh
        response["cache_info"]["cache_age_seconds"] = int(
            (datetime.utcnow() - _cache_timestamp).total_seconds()
        )

        return response

    except Exception as e:
        logger.error(f"Failed to get pricing table: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pricing-summary")
async def get_pricing_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_from_jwt),
):
    """
    Get pricing summary statistics.

    Returns:
        Summary of pricing data including model count, region count, etc.
    """
    try:
        # Use cache if available
        global _pricing_cache
        if _is_cache_valid() and _pricing_cache:
            pricing_data = _pricing_cache["pricing_data"]
        else:
            pricing_data = await _fetch_pricing_table(db)

        # Calculate summary statistics
        models = set()
        regions = set()
        sources = set()

        for record in pricing_data:
            models.add(record["model_id"])
            regions.add(record["region"])
            sources.add(record["source"])

        return {
            "total_records": len(pricing_data),
            "unique_models": len(models),
            "unique_regions": len(regions),
            "data_sources": list(sources),
            "models_list": sorted(list(models)),
            "regions_list": sorted(list(regions)),
        }

    except Exception as e:
        logger.error(f"Failed to get pricing summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clear-cache")
async def clear_pricing_cache(
    current_user: User = Depends(get_current_user_from_jwt),
):
    """
    Clear the pricing table cache.

    Use this after manual pricing updates to force cache refresh.

    Returns:
        Success message
    """
    global _pricing_cache, _cache_timestamp

    _pricing_cache = None
    _cache_timestamp = None

    logger.info("Pricing cache cleared")

    return {
        "success": True,
        "message": "Pricing cache cleared successfully",
    }

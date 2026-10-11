"""
Admin endpoints for monitoring - pricing table display with caching.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.api.deps import require_permission
from app.models.user import User
from app.models.model_pricing import ModelPricing as ModelPricingModel
from typing import List, Dict, Any, Optional, cast
from datetime import datetime, timedelta
from decimal import Decimal

from app.core.config import get_settings
from app.services.mantle_models import resolve_mantle_region
from app.services.openai_gpt_catalog import GptRoute, list_gpt_routes
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


def _per_1m(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else str((value * 1_000_000).normalize())


def _flat_price_fields(input_price: Decimal, output_price: Decimal) -> Dict[str, Any]:
    """Legacy flat fields (short-context band) kept for API compatibility."""
    return {
        "input_price_per_token": str(input_price),
        "output_price_per_token": str(output_price),
        "input_price_per_1k": str(input_price * 1_000),
        "output_price_per_1k": str(output_price * 1_000),
        "input_price_per_1m": str(input_price * 1_000_000),
        "output_price_per_1m": str(output_price * 1_000_000),
    }


def _tier(label: str, max_input_tokens: Optional[int], rates) -> Dict[str, Any]:
    return {
        "label": label,
        "max_input_tokens": max_input_tokens,
        "input_price_per_1m": _per_1m(rates.input),
        "cache_write_price_per_1m": _per_1m(rates.cache_write),
        "cache_read_price_per_1m": _per_1m(rates.cache_read),
        "output_price_per_1m": _per_1m(rates.output),
    }


def _context_tiers(pricing, prefix: str = "") -> List[Dict[str, Any]]:
    threshold = pricing.long_context_threshold
    tiers = [
        _tier(
            f"{prefix}≤{threshold // 1000}K" if threshold else f"{prefix}All",
            threshold,
            pricing.short,
        )
    ]
    if pricing.long is not None and threshold:
        tiers.append(_tier(f"{prefix}>{threshold // 1000}K", None, pricing.long))
    return tiers


def _gpt_route_row(route: GptRoute) -> Dict[str, Any]:
    """Render one catalogued GPT route exactly as it is routed and billed."""
    pricing = route.pricing
    tiers = _context_tiers(pricing)
    if route.ultrafast_pricing is not None:
        tiers += _context_tiers(route.ultrafast_pricing, prefix="Ultrafast ")
    if route.endpoint_family == "runtime":
        region = get_settings().AWS_REGION
    else:
        try:
            region = resolve_mantle_region(route.model_id)
        except KeyError:  # catalogued but absent from the Mantle registry
            region = "unavailable"
    cache = route.prompt_cache
    return {
        "model_id": route.model_id,
        "region": region,
        **_flat_price_fields(pricing.short.input, pricing.short.output),
        "cache_write_price_per_1m": _per_1m(pricing.short.cache_write),
        "cache_read_price_per_1m": _per_1m(pricing.short.cache_read),
        "context_tiers": tiers,
        "endpoint_family": route.endpoint_family,
        "api": route.api,
        "service_tiers": ["standard"]
        + (["ultrafast"] if route.ultrafast_pricing is not None else []),
        "scope": route.scope,
        "prompt_cache": {
            "implicit": cache.implicit,
            "explicit": cache.explicit,
            "explicit_content_types": sorted(cache.explicit_content_types),
            "max_breakpoints": cache.max_breakpoints if cache.explicit else None,
            "min_prefix_tokens": cache.min_prefix_tokens if cache.explicit else None,
            "ttl": cache.ttl if cache.explicit else None,
        },
        "source": "aws-model-card",
        "source_url": pricing.source_url,
        "last_updated": None,
    }


async def _fetch_pricing_table(db: AsyncSession) -> List[Dict[str, Any]]:
    """Build the pricing table shown in the admin UI.

    Catalogued GPT routes are rendered from the same catalog used for routing
    and billing (both context bands, cache write/read, cache capability);
    stale DB rows for those IDs are skipped so the UI cannot show a price the
    billing path does not use. Other models come from the database.
    """
    result = await db.execute(
        select(ModelPricingModel).order_by(
            ModelPricingModel.model_id, ModelPricingModel.region
        )
    )
    pricing_records = result.scalars().all()

    gpt_routes = list_gpt_routes()
    gpt_ids = {route.model_id for route in gpt_routes}

    pricing_list = [_gpt_route_row(route) for route in gpt_routes]
    for record in pricing_records:
        if record.model_id in gpt_ids:
            continue
        last_updated = cast(Optional[datetime], record.last_updated)
        cached_input = getattr(record, "cached_input_price_per_token", None)
        pricing_list.append(
            {
                "model_id": record.model_id,
                "region": record.region,
                **_flat_price_fields(
                    cast(Decimal, record.input_price_per_token),
                    cast(Decimal, record.output_price_per_token),
                ),
                "cache_write_price_per_1m": None,
                "cache_read_price_per_1m": _per_1m(cached_input),
                "context_tiers": None,
                "endpoint_family": None,
                "api": None,
                "service_tiers": None,
                "scope": None,
                "prompt_cache": None,
                "source": record.source,
                "source_url": None,
                "last_updated": last_updated.isoformat() if last_updated else None,
            }
        )

    pricing_list.sort(key=lambda row: (row["model_id"], row["region"]))
    return pricing_list


@router.get("/pricing-table")
async def get_pricing_table(
    force_refresh: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("view_monitor")),
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

        cache, cached_at = _pricing_cache, _cache_timestamp
        if cache is None or cached_at is None:  # populated above
            raise RuntimeError("pricing cache was not populated")

        # Build per-request cache status without mutating the shared cache
        # (a shallow copy would write these fields back into it).
        return {
            **cache,
            "cache_info": {
                **cache["cache_info"],
                "is_cached": not force_refresh,
                "cache_age_seconds": int(
                    (datetime.utcnow() - cached_at).total_seconds()
                ),
            },
        }

    except Exception as e:
        logger.error(f"Failed to get pricing table: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pricing-summary")
async def get_pricing_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("view_monitor")),
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
    current_user: User = Depends(require_permission("view_monitor")),
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

"""
Pricing service for calculating model usage costs.
"""

from typing import Optional
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
import logging

logger = logging.getLogger(__name__)

# Gemini implicit cache: if no explicit cached price in DB, use 25% of input price
GEMINI_CACHE_READ_FALLBACK_RATIO = Decimal("0.25")


class ModelPricing:
    """Model pricing configuration and cost calculation."""

    def __init__(self, db: Optional[AsyncSession] = None):
        """
        Initialize pricing service.

        Args:
            db: Database session for fetching pricing from database
        """
        self.db = db

    # Cache write multipliers by TTL (relative to input price) — Bedrock/Anthropic only
    CACHE_WRITE_MULTIPLIER = {
        "5m": Decimal("1.25"),
        "1h": Decimal("2.0"),
    }
    CACHE_READ_MULTIPLIER = Decimal("0.1")

    async def calculate_cost(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        region: str = None,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        cache_ttl: str = None,
    ) -> Decimal:
        """
        Calculate the cost for a model usage.

        For Gemini models:
          - region is always "global"
          - cache_read_input_tokens = Gemini implicit cached_tokens
          - cached price = DB cached_input_price_per_token (fallback: input × 0.25)
          - no cache_creation cost (Gemini auto-cache has no write fee)

        For Bedrock models:
          - region = configured AWS_REGION
          - cache_creation_input_tokens uses TTL-based write multiplier

        Args:
            model: Model name
            prompt_tokens: Number of non-cached input tokens
            completion_tokens: Number of output tokens
            region: Override region (auto-detected from model if None)
            cache_creation_input_tokens: Tokens written to Bedrock cache
            cache_read_input_tokens: Tokens read from cache (Bedrock or Gemini)
            cache_ttl: Bedrock cache TTL ("5m" or "1h")

        Returns:
            Cost in USD as Decimal

        Raises:
            ValueError: If model pricing cannot be determined
        """
        from app.services.gemini_client import is_gemini_model

        # Determine region
        if region is None:
            if is_gemini_model(model):
                region = "global"
            else:
                from app.core.config import get_settings

                region = get_settings().AWS_REGION

        # Determine cache write multiplier (Bedrock only)
        write_multiplier = self.CACHE_WRITE_MULTIPLIER.get(
            cache_ttl or "5m", Decimal("1.25")
        )

        # Try to get pricing from database
        if self.db:
            from app.services.pricing_updater import PricingUpdater

            updater = PricingUpdater(self.db)
            pricing = await updater.get_pricing(model, region)

            if pricing:
                input_price_per_token, output_price_per_token = pricing
                input_cost = Decimal(prompt_tokens) * input_price_per_token
                output_cost = Decimal(completion_tokens) * output_price_per_token

                if is_gemini_model(model):
                    # Gemini: no write cost; read cost uses dedicated cached price
                    cached_price = await self._get_gemini_cached_price(
                        model, input_price_per_token
                    )
                    cache_read_cost = Decimal(cache_read_input_tokens) * cached_price
                    return input_cost + output_cost + cache_read_cost
                else:
                    # Bedrock: TTL-based write cost + 0.1x read cost
                    cache_write_cost = (
                        Decimal(cache_creation_input_tokens)
                        * input_price_per_token
                        * write_multiplier
                    )
                    cache_read_cost = (
                        Decimal(cache_read_input_tokens)
                        * input_price_per_token
                        * self.CACHE_READ_MULTIPLIER
                    )
                    return input_cost + output_cost + cache_write_cost + cache_read_cost

        # If no database or pricing not found, raise error
        logger.error(f"No pricing found for model: {model}, region: {region}")
        raise ValueError(
            f"Pricing not available for model: {model}. "
            "Please run pricing update task or contact administrator."
        )

    async def _get_gemini_cached_price(
        self, model: str, input_price_per_token: Decimal
    ) -> Decimal:
        """
        Get the cached input price for a Gemini model.

        Tries to read cached_input_price_per_token from DB.
        Falls back to input_price × 0.25 if not set.
        """
        if self.db:
            try:
                from app.models.model_pricing import ModelPricing as ModelPricingRecord
                from sqlalchemy import select

                stmt = select(ModelPricingRecord).where(
                    ModelPricingRecord.model_id == model,
                    ModelPricingRecord.region == "global",
                )
                result = await self.db.execute(stmt)
                record = result.scalar_one_or_none()
                if record and hasattr(record, "cached_input_price_per_token"):
                    cached = record.cached_input_price_per_token
                    if cached is not None:
                        return Decimal(str(cached))
            except Exception as e:
                logger.debug(f"Could not fetch Gemini cached price from DB: {e}")

        # Fallback: 25% of normal input price (Google's standard cache discount)
        return input_price_per_token * GEMINI_CACHE_READ_FALLBACK_RATIO

    async def get_model_pricing_info(
        self, model: str, region: str = None
    ) -> Optional[dict]:
        """
        Get pricing information for a model.

        Args:
            model: Model name
            region: AWS region (defaults to configured AWS_REGION)

        Returns:
            Dictionary with pricing info or None if not found
        """
        if not self.db:
            return None

        if region is None:
            from app.core.config import get_settings

            region = get_settings().AWS_REGION

        from app.services.pricing_updater import PricingUpdater

        updater = PricingUpdater(self.db)
        pricing = await updater.get_pricing(model, region)

        if not pricing:
            return None

        input_price, output_price = pricing

        return {
            "model": model,
            "region": region,
            "input_price_per_1m": str(input_price * 1_000_000),
            "output_price_per_1m": str(output_price * 1_000_000),
            "input_price_per_1k": str(input_price * 1_000),
            "output_price_per_1k": str(output_price * 1_000),
        }

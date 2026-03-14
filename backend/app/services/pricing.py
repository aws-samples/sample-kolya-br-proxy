"""
Pricing service for calculating model usage costs.
"""

from typing import Optional
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
import logging

logger = logging.getLogger(__name__)


class ModelPricing:
    """Model pricing configuration and cost calculation."""

    def __init__(self, db: Optional[AsyncSession] = None):
        """
        Initialize pricing service.

        Args:
            db: Database session for fetching pricing from database
        """
        self.db = db

    async def calculate_cost(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        region: str = None,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ) -> Decimal:
        """
        Calculate the cost for a model usage.

        Args:
            model: Model name (e.g. "meta.llama3-3-70b-instruct-v1:0"
                   or "global.amazon.nova-pro-v1:0" for cross-region)
            prompt_tokens: Number of input tokens (excludes cache tokens)
            completion_tokens: Number of output tokens
            region: AWS region (defaults to configured AWS_REGION)
            cache_creation_input_tokens: Tokens written to cache (1.25x input price)
            cache_read_input_tokens: Tokens read from cache (0.1x input price)

        Returns:
            Cost in USD as Decimal

        Raises:
            ValueError: If model pricing cannot be determined
        """
        if region is None:
            from app.core.config import get_settings

            region = get_settings().AWS_REGION

        # Try to get pricing from database
        if self.db:
            from app.services.pricing_updater import PricingUpdater

            updater = PricingUpdater(self.db)
            pricing = await updater.get_pricing(model, region)

            if pricing:
                input_price_per_token, output_price_per_token = pricing
                input_cost = Decimal(prompt_tokens) * input_price_per_token
                output_cost = Decimal(completion_tokens) * output_price_per_token
                # Cache tokens use differentiated pricing
                cache_write_cost = (
                    Decimal(cache_creation_input_tokens)
                    * input_price_per_token
                    * Decimal("1.25")
                )
                cache_read_cost = (
                    Decimal(cache_read_input_tokens)
                    * input_price_per_token
                    * Decimal("0.1")
                )
                return input_cost + output_cost + cache_write_cost + cache_read_cost

        # If no database or pricing not found, raise error
        logger.error(f"No pricing found for model: {model}, region: {region}")
        raise ValueError(
            f"Pricing not available for model: {model}. "
            "Please run pricing update task or contact administrator."
        )

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

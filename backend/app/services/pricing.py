"""
Pricing service for calculating model usage costs.
"""

from dataclasses import dataclass
from typing import Optional
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
import logging

logger = logging.getLogger(__name__)

# Gemini implicit cache: if no explicit cached price in DB, use 25% of input price
GEMINI_CACHE_READ_FALLBACK_RATIO = Decimal("0.25")
_ONE_MILLION = Decimal("1000000")


def _per_token(price_per_million: str) -> Decimal:
    return Decimal(price_per_million) / _ONE_MILLION


@dataclass(frozen=True)
class TokenRates:
    """Per-token rates for one context-length band."""

    input: Decimal
    output: Decimal
    cache_read: Decimal | None = None
    cache_write: Decimal | None = None


@dataclass(frozen=True)
class OfficialProfilePricing:
    """AWS model-card rates for one exact inference profile."""

    model_id: str
    source_url: str
    short: TokenRates
    long_context_threshold: int | None = None
    long: TokenRates | None = None

    def rates_for_input_tokens(self, input_tokens: int) -> TokenRates:
        """Select the rate band AWS applies to the entire request."""
        if (
            self.long is not None
            and self.long_context_threshold is not None
            and input_tokens > self.long_context_threshold
        ):
            return self.long
        return self.short


# Source-backed fallbacks for profiles omitted from the public Price List file.
# Exact profile IDs are intentional: Global and Geo CRIS rates differ.
OFFICIAL_PROFILE_PRICING: dict[str, OfficialProfilePricing] = {
    "global.openai.gpt-6-sol": OfficialProfilePricing(
        model_id="global.openai.gpt-6-sol",
        source_url=(
            "https://docs.aws.amazon.com/bedrock/latest/userguide/"
            "model-card-openai-gpt-6-sol.html"
        ),
        short=TokenRates(
            input=_per_token("2.00"),
            cache_write=_per_token("2.50"),
            cache_read=_per_token("0.20"),
            output=_per_token("10.00"),
        ),
        long_context_threshold=272_000,
        long=TokenRates(
            input=_per_token("4.00"),
            cache_write=_per_token("5.00"),
            cache_read=_per_token("0.40"),
            output=_per_token("15.00"),
        ),
    ),
    "global.xai.grok-4.6": OfficialProfilePricing(
        model_id="global.xai.grok-4.6",
        source_url=(
            "https://docs.aws.amazon.com/bedrock/latest/userguide/"
            "model-card-xai-grok-4-6.html"
        ),
        short=TokenRates(
            input=_per_token("2.00"),
            cache_read=_per_token("0.50"),
            output=_per_token("6.00"),
        ),
    ),
    "us.openai.gpt-6-astra": OfficialProfilePricing(
        model_id="us.openai.gpt-6-astra",
        source_url=(
            "https://docs.aws.amazon.com/bedrock/latest/userguide/"
            "model-card-openai-gpt-6-astra.html"
        ),
        short=TokenRates(
            input=_per_token("11.00"),
            cache_write=_per_token("13.75"),
            cache_read=_per_token("1.10"),
            output=_per_token("55.00"),
        ),
        long_context_threshold=272_000,
        long=TokenRates(
            input=_per_token("22.00"),
            cache_write=_per_token("27.50"),
            cache_read=_per_token("2.20"),
            output=_per_token("82.50"),
        ),
    ),
}


def get_official_profile_pricing(
    model_id: str,
) -> OfficialProfilePricing | None:
    """Return model-card pricing only for an exact profile ID."""
    return OFFICIAL_PROFILE_PRICING.get(model_id)


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
        region: str | None = None,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        cache_ttl: str | None = None,
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
        from app.services.mantle_models import (
            is_openai_mantle_model,
            resolve_mantle_region,
        )

        # Determine region
        if region is None:
            if is_gemini_model(model):
                region = "global"
            elif is_openai_mantle_model(model):
                # mantle models are billed in the region they're routed to —
                # matches the routing in mantle_client.py.
                region = resolve_mantle_region(model)
            else:
                from app.services.bedrock import BedrockClient

                # Use resolve_model to determine the actual region where
                # the model runs — matches the routing in bedrock.py.
                _, region = BedrockClient.get_instance().resolve_model(model)

        # Determine cache write multiplier (Bedrock only).
        #
        # The extended 1h TTL (2.0x write price) is only actually applied at
        # Bedrock for models that support the ``ttl`` field in cache_control.
        # For legacy/unsupported models the proxy strips the ttl and Bedrock
        # writes a 5m cache billed at 1.25x — see
        # ``BedrockClient._model_supports_cache_ttl`` /
        # ``_inject_cache_control``. Gate the billing multiplier on the SAME
        # predicate so the cost we record always matches what AWS charges;
        # otherwise a 1h cache_ttl on an unsupported model over-bills the 0.75x
        # difference on every cache-write token.
        effective_write_ttl = cache_ttl or "5m"
        if effective_write_ttl != "5m":
            from app.services.bedrock import BedrockClient

            if not BedrockClient._model_supports_cache_ttl(model):
                effective_write_ttl = "5m"
        write_multiplier = self.CACHE_WRITE_MULTIPLIER.get(
            effective_write_ttl, self.CACHE_WRITE_MULTIPLIER["5m"]
        )

        # Try to get pricing from database
        if self.db:
            from app.services.pricing_updater import PricingUpdater

            updater = PricingUpdater(self.db)
            pricing = await updater.get_pricing(model, region)

            if pricing:
                input_price_per_token, output_price_per_token = pricing

                # Exact profile policies preserve AWS distinctions that the
                # legacy two-column DB row cannot represent: long-context
                # bands and model-specific cache dimensions. The DB row still
                # gates availability and powers the admin pricing API.
                official_pricing = get_official_profile_pricing(model)
                if official_pricing is not None:
                    total_input_tokens = (
                        prompt_tokens
                        + cache_creation_input_tokens
                        + cache_read_input_tokens
                    )
                    rates = official_pricing.rates_for_input_tokens(total_input_tokens)
                    if cache_creation_input_tokens and rates.cache_write is None:
                        raise ValueError(
                            f"AWS does not publish a cache-write price for {model}"
                        )
                    cache_write_price = (
                        rates.cache_write
                        if rates.cache_write is not None
                        else Decimal(0)
                    )
                    cache_read_price = (
                        rates.cache_read
                        if rates.cache_read is not None
                        else rates.input
                    )
                    return (
                        Decimal(prompt_tokens) * rates.input
                        + Decimal(completion_tokens) * rates.output
                        + Decimal(cache_creation_input_tokens) * cache_write_price
                        + Decimal(cache_read_input_tokens) * cache_read_price
                    )

                input_cost = Decimal(prompt_tokens) * input_price_per_token
                output_cost = Decimal(completion_tokens) * output_price_per_token

                cached_price = await self._get_cached_input_price(model, region)
                if is_gemini_model(model):
                    # Gemini: no write cost; use the dedicated DB rate when
                    # present, otherwise Google's standard 25% fallback.
                    cache_read_price = (
                        cached_price
                        if cached_price is not None
                        else input_price_per_token * GEMINI_CACHE_READ_FALLBACK_RATIO
                    )
                    cache_read_cost = (
                        Decimal(cache_read_input_tokens) * cache_read_price
                    )
                    return input_cost + output_cost + cache_read_cost
                else:
                    # Bedrock: TTL-based write cost. Cache-read discounts are
                    # model-specific when AWS publishes a dedicated dimension
                    # (for example Grok 4.6 is 25%, not the legacy 10%).
                    cache_write_cost = (
                        Decimal(cache_creation_input_tokens)
                        * input_price_per_token
                        * write_multiplier
                    )
                    cache_read_price = (
                        cached_price
                        if cached_price is not None
                        else input_price_per_token * self.CACHE_READ_MULTIPLIER
                    )
                    cache_read_cost = (
                        Decimal(cache_read_input_tokens) * cache_read_price
                    )
                    return input_cost + output_cost + cache_write_cost + cache_read_cost

        # If no database or pricing not found, raise error
        logger.error(f"No pricing found for model: {model}, region: {region}")
        raise ValueError(
            f"Pricing not available for model: {model}. "
            "Please run pricing update task or contact administrator."
        )

    async def _get_cached_input_price(self, model: str, region: str) -> Decimal | None:
        """Read an exact model/region cached-input rate when one is stored."""
        if not self.db:
            return None

        try:
            from app.models.model_pricing import ModelPricing as ModelPricingRecord
            from sqlalchemy import select

            result = await self.db.execute(
                select(ModelPricingRecord).where(
                    ModelPricingRecord.model_id == model,
                    ModelPricingRecord.region == region,
                )
            )
            record = result.scalar_one_or_none()
            if record and hasattr(record, "cached_input_price_per_token"):
                cached = record.cached_input_price_per_token
                if cached is not None:
                    return Decimal(str(cached))
        except Exception as e:
            logger.debug(f"Could not fetch cached-input price from DB: {e}")
        return None

    async def get_model_pricing_info(
        self, model: str, region: str | None = None
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

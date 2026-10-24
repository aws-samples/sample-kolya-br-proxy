"""
Pricing service for calculating model usage costs.
"""

from dataclasses import dataclass
from typing import Optional
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.services.openai_gpt_catalog import gpt_official_pricing, resolve_gpt_route
from app.services.pricing_types import OfficialProfilePricing, TokenRates
from app.services.pricing_types import per_token as _per_token

__all__ = [
    "OFFICIAL_PROFILE_PRICING",
    "ModelPricing",
    "OfficialProfilePricing",
    "TokenRates",
    "get_official_profile_pricing",
]

logger = logging.getLogger(__name__)

# Gemini implicit cache: if no explicit cached price in DB, use 25% of input price
GEMINI_CACHE_READ_FALLBACK_RATIO = Decimal("0.25")

# Source-backed pricing for exact model/profile IDs that the public Price List
# file omits or prices ambiguously. GPT entries come from the GPT catalog, which
# also drives routing and prompt-cache capability, so the three cannot drift.
# Exact IDs are intentional: Global and Geo CRIS rates differ.
OFFICIAL_PROFILE_PRICING: dict[str, OfficialProfilePricing] = {
    **gpt_official_pricing(),
    # ── Grok 4.6 ─────────────────────────────────────────────────────
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
}


def get_official_profile_pricing(
    model_id: str,
    service_tier: str | None = None,
) -> OfficialProfilePricing | None:
    """Return model-card pricing for an exact model or profile ID.

    *service_tier* is the tier that served the request; ``"ultrafast"``
    selects the Ultrafast rates on routes that offer them (6× Standard for
    GPT-6 Astra / GPT-6.1 Sol). Any other tier uses Standard rates.
    """
    pricing = OFFICIAL_PROFILE_PRICING.get(model_id)
    if pricing is None:
        return None
    route = resolve_gpt_route(model_id)
    return route.pricing_for_tier(service_tier) if route else pricing


def _calculate_official_cost(
    pricing: OfficialProfilePricing,
    prompt_tokens: int,
    completion_tokens: int,
    cache_creation_input_tokens: int,
    cache_read_input_tokens: int,
) -> Decimal:
    """Calculate authoritative model-card pricing without requiring a DB row."""
    total_input_tokens = (
        prompt_tokens + cache_creation_input_tokens + cache_read_input_tokens
    )
    rates = pricing.rates_for_input_tokens(total_input_tokens)
    if cache_creation_input_tokens and rates.cache_write is None:
        raise ValueError(
            f"AWS does not publish a cache-write price for {pricing.model_id}"
        )
    cache_write_price = rates.cache_write or Decimal(0)
    cache_read_price = rates.cache_read or rates.input
    return (
        Decimal(prompt_tokens) * rates.input
        + Decimal(completion_tokens) * rates.output
        + Decimal(cache_creation_input_tokens) * cache_write_price
        + Decimal(cache_read_input_tokens) * cache_read_price
    )


def _to_decimal(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


@dataclass(frozen=True)
class DbBandRates:
    """Rates from a DB pricing row for the band one request falls in."""

    input: Decimal
    output: Decimal
    cache_read: Decimal | None
    cache_write: Decimal | None
    is_long: bool


def db_rates_for_band(record, long_band: bool) -> DbBandRates:
    """Published rates of *record* for its short or long band."""
    if long_band:
        return DbBandRates(
            input=Decimal(str(record.long_input_price_per_token)),
            output=Decimal(str(record.long_output_price_per_token)),
            cache_read=_to_decimal(record.long_cached_input_price_per_token),
            cache_write=None,
            is_long=True,
        )
    return DbBandRates(
        input=Decimal(str(record.input_price_per_token)),
        output=Decimal(str(record.output_price_per_token)),
        cache_read=_to_decimal(record.cached_input_price_per_token),
        cache_write=_to_decimal(record.cache_write_price_per_token),
        is_long=False,
    )


def db_has_long_band(record) -> bool:
    return (
        record.long_context_threshold is not None
        and record.long_input_price_per_token is not None
        and record.long_output_price_per_token is not None
    )


@dataclass(frozen=True)
class EffectiveRates:
    """Per-token rates billing actually applies (fallback ratios resolved)."""

    input: Decimal
    output: Decimal
    cache_read: Decimal
    cache_write: Decimal | None  # None = no write fee (Gemini implicit cache)


# Bedrock cache-read rate as a fraction of input for models whose price feed
# omits it. The 5.5 Claude family bills reads at 5%, not the usual 10% —
# verified against Cost Explorer (Opus 5.5 $0.20/M on $4 input, Sonnet 5.5
# $0.10/M on $2 input).
_CACHE_READ_RATIO_BY_MODEL = {
    "claude-opus-5-5": Decimal("0.05"),
    "claude-sonnet-5-5": Decimal("0.05"),
}


def _bedrock_cache_read_ratio(model: str) -> Decimal:
    for family, ratio in _CACHE_READ_RATIO_BY_MODEL.items():
        if family in model:
            return ratio
    return ModelPricing.CACHE_READ_MULTIPLIER


def effective_db_rates(
    model: str, rates: DbBandRates, write_multiplier: Decimal
) -> EffectiveRates:
    """Resolve published-or-fallback cache rates for one DB band.

    Gemini: no write fee; cache read = published rate or 25% of input.
    Bedrock: cache write = published rate (e.g. Nova $0) or input × TTL
    multiplier; cache read = published rate or the per-model fallback ratio
    (5% for Claude 5.5, otherwise 10%).
    """
    from app.services.gemini_client import is_gemini_model

    if is_gemini_model(model):
        return EffectiveRates(
            input=rates.input,
            output=rates.output,
            cache_read=(
                rates.cache_read
                if rates.cache_read is not None
                else rates.input * GEMINI_CACHE_READ_FALLBACK_RATIO
            ),
            cache_write=None,
        )
    return EffectiveRates(
        input=rates.input,
        output=rates.output,
        cache_read=(
            rates.cache_read
            if rates.cache_read is not None
            else rates.input * _bedrock_cache_read_ratio(model)
        ),
        cache_write=(
            rates.cache_write
            if rates.cache_write is not None
            else rates.input * write_multiplier
        ),
    )


def _db_rates_for_request(record, total_input_tokens: int) -> DbBandRates:
    """Like the model-card path, a request whose total input (uncached + cache
    write + cache read) exceeds the threshold bills entirely at long rates."""
    return db_rates_for_band(
        record,
        db_has_long_band(record) and total_input_tokens > record.long_context_threshold,
    )


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
        service_tier: str | None = None,
        cache_write_1h_tokens: int | None = None,
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
            cache_write_1h_tokens: Portion of cache_creation_input_tokens that
                Bedrock reports was written with the 1h TTL. When given, it
                overrides cache_ttl for write pricing (the rest bills at 5m).

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

        # Model-card rates are authoritative and complete enough to calculate
        # cost even if the updater has not seeded (or temporarily lost) its DB
        # row. This prevents successful profile requests from being recorded at
        # zero cost after a profile-cache or pricing refresh failure.
        official_pricing = get_official_profile_pricing(model, service_tier)
        if official_pricing is not None:
            return _calculate_official_cost(
                official_pricing,
                prompt_tokens,
                completion_tokens,
                cache_creation_input_tokens,
                cache_read_input_tokens,
            )

        # Try to get pricing from database
        if self.db:
            from app.services.pricing_updater import PricingUpdater

            record = await PricingUpdater(self.db).get_pricing_record(model, region)
            if record is not None:
                total_input_tokens = (
                    prompt_tokens
                    + cache_creation_input_tokens
                    + cache_read_input_tokens
                )
                band = _db_rates_for_request(record, total_input_tokens)
                rates = effective_db_rates(model, band, write_multiplier)
                if cache_write_1h_tokens is not None and rates.cache_write is not None:
                    # Bedrock reported the TTL each write actually got: bill
                    # the 1h part at 2.0x and the rest at the 5m rate.
                    write_1h = min(cache_write_1h_tokens, cache_creation_input_tokens)
                    rate_5m = effective_db_rates(
                        model, band, self.CACHE_WRITE_MULTIPLIER["5m"]
                    ).cache_write
                    cache_write_cost = Decimal(
                        cache_creation_input_tokens - write_1h
                    ) * rate_5m + Decimal(write_1h) * (
                        band.input * self.CACHE_WRITE_MULTIPLIER["1h"]
                    )
                else:
                    cache_write_cost = Decimal(cache_creation_input_tokens) * (
                        rates.cache_write or 0
                    )
                return (
                    Decimal(prompt_tokens) * rates.input
                    + Decimal(completion_tokens) * rates.output
                    + cache_write_cost
                    + Decimal(cache_read_input_tokens) * rates.cache_read
                )

        # If no database or pricing not found, raise error
        logger.error(f"No pricing found for model: {model}, region: {region}")
        raise ValueError(
            f"Pricing not available for model: {model}. "
            "Please run pricing update task or contact administrator."
        )

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

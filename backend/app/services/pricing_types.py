"""Value types for source-backed (AWS model-card) pricing.

Kept separate from ``pricing.py`` so model catalogs can describe their prices
without importing the cost-calculation service (and creating an import cycle).
"""

from dataclasses import dataclass
from decimal import Decimal

_ONE_MILLION = Decimal("1000000")


def per_token(price_per_million: str) -> Decimal:
    """Convert a model-card ``$ / 1M tokens`` string to a per-token Decimal."""
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
    """AWS model-card rates for one exact model or inference-profile ID."""

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

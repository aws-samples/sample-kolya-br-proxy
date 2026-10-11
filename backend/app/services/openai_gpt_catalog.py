"""OpenAI GPT on Amazon Bedrock: exact routes, prompt-cache capability, pricing.

This module is the single source of truth for every closed-weight GPT model ID
the gateway serves. One lookup — :func:`resolve_gpt_route` — tells callers:

* which endpoint family serves the exact ID (``bedrock-mantle`` for canonical
  ``openai.*`` IDs, ``bedrock-runtime`` for ``us.`` / ``global.`` system
  inference profiles) — IDs are never rewritten, because the prefix carries
  residency, authorization and price semantics;
* which content types accept an explicit ``prompt_cache_breakpoint`` (empty =
  explicit caching unsupported);
* the model-card Standard-tier prices for both context bands.

Routing, explicit-cache validation, billing and the admin pricing table all
read the same entries, so they cannot drift apart. Cache prices are never used
to infer cache *support*: several model cards publish cache price dimensions
for models or endpoints that do not accept explicit breakpoints.

All GPT routes use the OpenAI Responses API. AWS documents prompt caching for
these models on Responses (some also on Chat Completions/Invoke, never on
Converse for explicit breakpoints), so a GPT request is never sent to Converse.

Sources: the per-model cards linked in ``source_url`` (fetched 2026-10-11).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.services.pricing_types import OfficialProfilePricing, TokenRates, per_token

EndpointFamily = Literal["mantle", "runtime"]
Scope = Literal["in-region", "us", "global"]

_CARD_URL = (
    "https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-{slug}.html"
)
_LONG_CONTEXT_THRESHOLD = 272_000

TEXT_IMAGE_FILE = frozenset({"input_text", "input_image", "input_file"})
TEXT_ONLY = frozenset({"input_text"})
# GPT-6.x: model cards document text breakpoints; live probes on 2026-10-11
# also wrote cache from image breakpoints on every 6.x route (Mantle and
# Runtime), so images are accepted. File breakpoints remain undocumented.
TEXT_IMAGE = frozenset({"input_text", "input_image"})
NO_EXPLICIT = frozenset()


@dataclass(frozen=True)
class PromptCacheCapability:
    """What prompt caching the exact route supports."""

    implicit: bool
    explicit_content_types: frozenset[str]
    max_breakpoints: int = 4
    min_prefix_tokens: int = 1024
    ttl: str = "30m"

    @property
    def explicit(self) -> bool:
        return bool(self.explicit_content_types)


@dataclass(frozen=True)
class GptRoute:
    """How one exact GPT model ID is served and billed."""

    model_id: str
    canonical_id: str
    display_name: str
    endpoint_family: EndpointFamily
    scope: Scope
    prompt_cache: PromptCacheCapability
    pricing: OfficialProfilePricing
    api: Literal["responses"] = "responses"
    # Premium speed tier (``service_tier: "ultrafast"``); None = unsupported.
    ultrafast_pricing: OfficialProfilePricing | None = None
    # Mantle regions that serve Ultrafast (Runtime profiles serve it anywhere).
    ultrafast_mantle_regions: tuple[str, ...] = ()

    def pricing_for_tier(self, service_tier: str | None) -> OfficialProfilePricing:
        """Model-card rates for the service tier that actually served a request."""
        if is_ultrafast(service_tier) and self.ultrafast_pricing is not None:
            return self.ultrafast_pricing
        return self.pricing


# (input, cache_write, cache_read, output) in USD per 1M tokens.
_Rates = tuple[str, str | None, str, str]


@dataclass(frozen=True)
class _Family:
    canonical_id: str
    display_name: str
    card_slug: str
    runtime_scopes: tuple[Literal["us", "global"], ...]
    regional_short: _Rates  # In-Region (Mantle) and US Geo CRIS share rates
    regional_long: _Rates
    global_short: _Rates | None
    global_long: _Rates | None
    mantle_explicit: frozenset[str]
    runtime_explicit: frozenset[str]
    ultrafast_multiplier: int | None = None
    ultrafast_mantle_regions: tuple[str, ...] = ()


def is_ultrafast(service_tier: str | None) -> bool:
    return isinstance(service_tier, str) and service_tier.lower() == "ultrafast"


def _family(
    canonical_id: str,
    display_name: str,
    card_slug: str,
    *,
    regional: tuple[_Rates, _Rates],
    global_: tuple[_Rates, _Rates] | None = None,
    runtime_scopes: tuple[Literal["us", "global"], ...] = ("us", "global"),
    mantle_explicit: frozenset[str] = NO_EXPLICIT,
    runtime_explicit: frozenset[str] = NO_EXPLICIT,
    ultrafast_multiplier: int | None = None,
    ultrafast_mantle_regions: tuple[str, ...] = (),
) -> _Family:
    return _Family(
        canonical_id=canonical_id,
        display_name=display_name,
        card_slug=card_slug,
        runtime_scopes=runtime_scopes,
        regional_short=regional[0],
        regional_long=regional[1],
        global_short=global_[0] if global_ else None,
        global_long=global_[1] if global_ else None,
        mantle_explicit=mantle_explicit,
        runtime_explicit=runtime_explicit,
        ultrafast_multiplier=ultrafast_multiplier,
        ultrafast_mantle_regions=ultrafast_mantle_regions,
    )


_FAMILIES: tuple[_Family, ...] = (
    _family(
        "openai.gpt-5.6-sol",
        "GPT-5.6 Sol",
        "openai-gpt-56-sol",
        regional=(
            ("4.40", "5.50", "0.44", "22.00"),
            ("8.80", "11.00", "0.88", "33.00"),
        ),
        global_=(("4.00", "5.00", "0.40", "20.00"), ("8.00", "10.00", "0.80", "30.00")),
        mantle_explicit=TEXT_IMAGE_FILE,
        runtime_explicit=TEXT_IMAGE_FILE,
    ),
    _family(
        "openai.gpt-5.6-terra",
        "GPT-5.6 Terra",
        "openai-gpt-56-terra",
        regional=(("2.20", "2.75", "0.22", "13.20"), ("4.40", "5.50", "0.44", "19.80")),
        global_=(("2.00", "2.50", "0.20", "12.00"), ("4.00", "5.00", "0.40", "18.00")),
        mantle_explicit=TEXT_IMAGE_FILE,
        runtime_explicit=TEXT_IMAGE_FILE,
    ),
    _family(
        "openai.gpt-5.6-luna",
        "GPT-5.6 Luna",
        "openai-gpt-56-luna",
        regional=(
            ("0.22", "0.275", "0.022", "1.32"),
            ("0.44", "0.55", "0.044", "1.98"),
        ),
        global_=(("0.20", "0.25", "0.02", "1.20"), ("0.40", "0.50", "0.04", "1.80")),
        mantle_explicit=TEXT_IMAGE_FILE,
        runtime_explicit=TEXT_IMAGE_FILE,
    ),
    _family(
        "openai.gpt-6-sol",
        "GPT-6 Sol",
        "openai-gpt-6-sol",
        regional=(("2.20", "2.75", "0.22", "11.00"), ("4.40", "5.50", "0.44", "16.50")),
        global_=(("2.00", "2.50", "0.20", "10.00"), ("4.00", "5.00", "0.40", "15.00")),
        mantle_explicit=TEXT_IMAGE,
        runtime_explicit=TEXT_IMAGE,
    ),
    _family(
        "openai.gpt-6-luna",
        "GPT-6 Luna",
        "openai-gpt-6-luna",
        regional=(
            ("0.11", "0.1375", "0.011", "0.55"),
            ("0.22", "0.275", "0.022", "0.825"),
        ),
        global_=(("0.10", "0.125", "0.01", "0.50"), ("0.20", "0.25", "0.02", "0.75")),
        mantle_explicit=TEXT_IMAGE,
        runtime_explicit=TEXT_IMAGE,
    ),
    _family(
        "openai.gpt-6-astra",
        "GPT-6 Astra",
        "openai-gpt-6-astra",
        regional=(
            ("11.00", "13.75", "1.10", "55.00"),
            ("22.00", "27.50", "2.20", "82.50"),
        ),
        global_=(
            ("10.00", "12.50", "1.00", "50.00"),
            ("20.00", "25.00", "2.00", "75.00"),
        ),
        # Mantle lists explicit caching (Responses). The Runtime feature table
        # omits prompt caching for Astra, but live probes on 2026-10-11 wrote
        # and read explicit text and image breakpoints on both endpoints.
        mantle_explicit=TEXT_IMAGE,
        runtime_explicit=TEXT_IMAGE,
        # "Ultrafast prices are six times the corresponding Standard prices";
        # Mantle Ultrafast only in us-east-1 (us-west-2 is Standard only).
        ultrafast_multiplier=6,
        ultrafast_mantle_regions=("us-east-1",),
    ),
    _family(
        "openai.gpt-6.1-sol",
        "GPT-6.1 Sol",
        "openai-gpt-6-1-sol",
        regional=(("2.20", "2.75", "0.11", "11.00"), ("4.40", "5.50", "0.22", "16.50")),
        global_=(("2.00", "2.50", "0.10", "10.00"), ("4.00", "5.00", "0.20", "15.00")),
        mantle_explicit=TEXT_IMAGE,
        runtime_explicit=TEXT_IMAGE,
        # "Ultrafast costs six times as much as Standard"; Mantle us-east-1.
        ultrafast_multiplier=6,
        ultrafast_mantle_regions=("us-east-1",),
    ),
    # GPT-5.5 and earlier: Mantle only, implicit caching with no write fee
    # (cache-write tokens bill at the normal input rate).
    _family(
        "openai.gpt-5.5",
        "GPT-5.5",
        "openai-gpt-55",
        regional=(
            ("5.50", "5.50", "0.55", "33.00"),
            ("11.00", "11.00", "1.10", "49.50"),
        ),
        runtime_scopes=(),
    ),
    _family(
        "openai.gpt-5.4",
        "GPT-5.4",
        "openai-gpt-54",
        regional=(
            ("2.75", "2.75", "0.275", "16.50"),
            ("5.50", "5.50", "0.55", "24.75"),
        ),
        runtime_scopes=(),
    ),
)


def _rates(values: _Rates) -> TokenRates:
    input_, cache_write, cache_read, output = values
    return TokenRates(
        input=per_token(input_),
        cache_write=per_token(cache_write) if cache_write is not None else None,
        cache_read=per_token(cache_read),
        output=per_token(output),
    )


def _pricing(
    model_id: str, slug: str, short: _Rates, long: _Rates
) -> OfficialProfilePricing:
    return OfficialProfilePricing(
        model_id=model_id,
        source_url=_CARD_URL.format(slug=slug),
        short=_rates(short),
        long_context_threshold=_LONG_CONTEXT_THRESHOLD,
        long=_rates(long),
    )


def _scaled(rates: TokenRates, factor: int) -> TokenRates:
    def scale(value):
        return None if value is None else value * factor

    return TokenRates(
        input=rates.input * factor,
        output=rates.output * factor,
        cache_read=scale(rates.cache_read),
        cache_write=scale(rates.cache_write),
    )


def _scaled_pricing(
    pricing: OfficialProfilePricing, factor: int
) -> OfficialProfilePricing:
    return OfficialProfilePricing(
        model_id=pricing.model_id,
        source_url=pricing.source_url,
        short=_scaled(pricing.short, factor),
        long_context_threshold=pricing.long_context_threshold,
        long=_scaled(pricing.long, factor) if pricing.long else None,
    )


def _build_routes() -> dict[str, GptRoute]:
    routes: dict[str, GptRoute] = {}
    for family in _FAMILIES:
        base = family.canonical_id.removeprefix("openai.")
        entries: list[tuple[str, EndpointFamily, Scope, frozenset[str], _Rates, _Rates]]
        entries = [
            (
                family.canonical_id,
                "mantle",
                "in-region",
                family.mantle_explicit,
                family.regional_short,
                family.regional_long,
            )
        ]
        for scope in family.runtime_scopes:
            if scope == "global":
                if family.global_short is None or family.global_long is None:
                    raise ValueError(f"{family.canonical_id}: missing Global rates")
                short, long = family.global_short, family.global_long
            else:
                short, long = family.regional_short, family.regional_long
            entries.append(
                (
                    f"{scope}.openai.{base}",
                    "runtime",
                    scope,
                    family.runtime_explicit,
                    short,
                    long,
                )
            )
        for model_id, endpoint, scope, explicit, short, long in entries:
            pricing = _pricing(model_id, family.card_slug, short, long)
            factor = family.ultrafast_multiplier
            routes[model_id] = GptRoute(
                model_id=model_id,
                canonical_id=family.canonical_id,
                display_name=family.display_name,
                endpoint_family=endpoint,
                scope=scope,
                prompt_cache=PromptCacheCapability(
                    implicit=True, explicit_content_types=explicit
                ),
                pricing=pricing,
                ultrafast_pricing=_scaled_pricing(pricing, factor) if factor else None,
                ultrafast_mantle_regions=(
                    family.ultrafast_mantle_regions if endpoint == "mantle" else ()
                ),
            )
    return routes


_ROUTES: dict[str, GptRoute] = _build_routes()


def resolve_gpt_route(model_id: str) -> GptRoute | None:
    """Return the route for an exact GPT model ID (or bare ``gpt-*`` name).

    Bare names (``gpt-6-sol``) resolve to the canonical Mantle ID, matching
    what OpenAI SDK clients commonly send. Profile IDs are matched exactly.
    """
    route = _ROUTES.get(model_id)
    if route is None and model_id.startswith("gpt-"):
        route = _ROUTES.get(f"openai.{model_id}")
    return route


def list_gpt_routes() -> list[GptRoute]:
    """All catalogued routes, canonical IDs first within each family."""
    return list(_ROUTES.values())


def runtime_responses_model_ids() -> frozenset[str]:
    """Exact ``us.`` / ``global.`` profile IDs served by Runtime Responses."""
    return frozenset(
        model_id
        for model_id, route in _ROUTES.items()
        if route.endpoint_family == "runtime"
    )


def gpt_official_pricing() -> dict[str, OfficialProfilePricing]:
    """Model-card pricing keyed by exact model ID."""
    return {model_id: route.pricing for model_id, route in _ROUTES.items()}

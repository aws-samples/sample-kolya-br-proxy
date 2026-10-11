"""The GPT catalog is the single source for route, cache capability and price.

Values are pinned to the AWS model cards (Standard tier) so a careless edit to
one dimension cannot silently change routing, explicit-cache validation, or
billing for another.
"""

from decimal import Decimal

import pytest

from app.services.openai_gpt_catalog import list_gpt_routes, resolve_gpt_route
from app.services.pricing import get_official_profile_pricing

MILLION = Decimal(1_000_000)

TEXT_IMAGE_FILE = {"input_text", "input_image", "input_file"}
TEXT_ONLY = {"input_text"}


@pytest.mark.parametrize(
    ("model_id", "endpoint_family", "scope"),
    [
        ("openai.gpt-5.6-sol", "mantle", "in-region"),
        ("us.openai.gpt-5.6-sol", "runtime", "us"),
        ("global.openai.gpt-5.6-sol", "runtime", "global"),
        ("openai.gpt-5.6-terra", "mantle", "in-region"),
        ("us.openai.gpt-5.6-terra", "runtime", "us"),
        ("global.openai.gpt-5.6-luna", "runtime", "global"),
        ("openai.gpt-6-sol", "mantle", "in-region"),
        ("us.openai.gpt-6-sol", "runtime", "us"),
        ("global.openai.gpt-6-sol", "runtime", "global"),
        ("global.openai.gpt-6-luna", "runtime", "global"),
        ("us.openai.gpt-6-astra", "runtime", "us"),
        ("openai.gpt-6.1-sol", "mantle", "in-region"),
        ("us.openai.gpt-6.1-sol", "runtime", "us"),
        ("global.openai.gpt-6.1-sol", "runtime", "global"),
        ("openai.gpt-5.5", "mantle", "in-region"),
        ("openai.gpt-5.4", "mantle", "in-region"),
    ],
)
def test_exact_model_id_selects_endpoint_family_without_rewriting(
    model_id, endpoint_family, scope
):
    route = resolve_gpt_route(model_id)

    assert route is not None
    assert route.model_id == model_id
    assert route.endpoint_family == endpoint_family
    assert route.api == "responses"
    assert route.scope == scope


def test_bare_names_resolve_to_canonical_mantle_route():
    route = resolve_gpt_route("gpt-6-sol")

    assert route is not None
    assert route.model_id == "openai.gpt-6-sol"
    assert route.endpoint_family == "mantle"


@pytest.mark.parametrize(
    "model_id",
    [
        "us.openai.gpt-5.5",  # GPT-5.5 is Mantle-only
        "global.openai.gpt-5.4",
        "eu.openai.gpt-6-sol",  # no EU profile on the model card
        "openai.gpt-oss-120b-1:0",  # open-weight models use Converse
        "anthropic.claude-sonnet-4-6",
    ],
)
def test_unpublished_ids_have_no_gpt_route(model_id):
    assert resolve_gpt_route(model_id) is None


@pytest.mark.parametrize(
    ("model_id", "explicit_types"),
    [
        ("openai.gpt-5.6-sol", TEXT_IMAGE_FILE),
        ("global.openai.gpt-5.6-sol", TEXT_IMAGE_FILE),
        ("us.openai.gpt-5.6-terra", TEXT_IMAGE_FILE),
        ("openai.gpt-5.6-luna", TEXT_IMAGE_FILE),
        ("openai.gpt-6-sol", TEXT_ONLY),
        ("global.openai.gpt-6-sol", TEXT_ONLY),
        ("us.openai.gpt-6-luna", TEXT_ONLY),
        ("openai.gpt-6.1-sol", TEXT_ONLY),
        ("global.openai.gpt-6.1-sol", TEXT_ONLY),
        ("openai.gpt-6-astra", TEXT_ONLY),
        # Astra Runtime: verified by live probe (card omits the feature row).
        ("us.openai.gpt-6-astra", TEXT_ONLY),
        ("global.openai.gpt-6-astra", TEXT_ONLY),
        ("openai.gpt-5.5", set()),
        ("openai.gpt-5.4", set()),
    ],
)
def test_explicit_cache_capability_is_exact_and_independent_of_prices(
    model_id, explicit_types
):
    route = resolve_gpt_route(model_id)

    assert route is not None
    assert set(route.prompt_cache.explicit_content_types) == explicit_types
    assert route.prompt_cache.explicit is bool(explicit_types)
    assert route.prompt_cache.max_breakpoints == 4
    # Prices with a cache-write dimension never imply explicit support.
    assert route.pricing is not None


def _per_million(rates):
    return tuple(
        None if value is None else (value * MILLION).normalize()
        for value in (rates.input, rates.cache_write, rates.cache_read, rates.output)
    )


def _d(*values):
    return tuple(Decimal(v).normalize() for v in values)


@pytest.mark.parametrize(
    ("model_id", "short", "long"),
    [
        (
            "openai.gpt-5.6-sol",
            _d("4.40", "5.50", "0.44", "22"),
            _d("8.80", "11", "0.88", "33"),
        ),
        (
            "us.openai.gpt-5.6-sol",
            _d("4.40", "5.50", "0.44", "22"),
            _d("8.80", "11", "0.88", "33"),
        ),
        (
            "global.openai.gpt-5.6-sol",
            _d("4", "5", "0.40", "20"),
            _d("8", "10", "0.80", "30"),
        ),
        (
            "openai.gpt-5.6-terra",
            _d("2.20", "2.75", "0.22", "13.20"),
            _d("4.40", "5.50", "0.44", "19.80"),
        ),
        (
            "global.openai.gpt-5.6-terra",
            _d("2", "2.50", "0.20", "12"),
            _d("4", "5", "0.40", "18"),
        ),
        (
            "us.openai.gpt-5.6-luna",
            _d("0.22", "0.275", "0.022", "1.32"),
            _d("0.44", "0.55", "0.044", "1.98"),
        ),
        (
            "global.openai.gpt-5.6-luna",
            _d("0.20", "0.25", "0.02", "1.20"),
            _d("0.40", "0.50", "0.04", "1.80"),
        ),
        (
            "us.openai.gpt-6-sol",
            _d("2.20", "2.75", "0.22", "11"),
            _d("4.40", "5.50", "0.44", "16.50"),
        ),
        (
            "global.openai.gpt-6-sol",
            _d("2", "2.50", "0.20", "10"),
            _d("4", "5", "0.40", "15"),
        ),
        (
            "openai.gpt-6-luna",
            _d("0.11", "0.1375", "0.011", "0.55"),
            _d("0.22", "0.275", "0.022", "0.825"),
        ),
        (
            "global.openai.gpt-6-luna",
            _d("0.10", "0.125", "0.01", "0.50"),
            _d("0.20", "0.25", "0.02", "0.75"),
        ),
        (
            "us.openai.gpt-6-astra",
            _d("11", "13.75", "1.10", "55"),
            _d("22", "27.50", "2.20", "82.50"),
        ),
        (
            "global.openai.gpt-6-astra",
            _d("10", "12.50", "1", "50"),
            _d("20", "25", "2", "75"),
        ),
        (
            "openai.gpt-6.1-sol",
            _d("2.20", "2.75", "0.11", "11"),
            _d("4.40", "5.50", "0.22", "16.50"),
        ),
        (
            "global.openai.gpt-6.1-sol",
            _d("2", "2.50", "0.10", "10"),
            _d("4", "5", "0.20", "15"),
        ),
    ],
)
def test_route_pricing_matches_model_card(model_id, short, long):
    pricing = get_official_profile_pricing(model_id)

    assert pricing is not None
    assert pricing.long_context_threshold == 272_000
    assert _per_million(pricing.short) == short
    assert _per_million(pricing.long) == long


def test_every_catalog_route_has_pricing_and_unique_model_id():
    routes = list_gpt_routes()
    model_ids = [route.model_id for route in routes]

    assert len(model_ids) == len(set(model_ids))
    for route in routes:
        assert get_official_profile_pricing(route.model_id) is route.pricing

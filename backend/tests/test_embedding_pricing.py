# pyright: reportMissingImports=false
"""Parsing contracts for per-modality embedding prices on the AWS pricing page.

The markup below mirrors the live ``data-pricing-markup`` tables (captured
2026-10) with hashes shortened.
"""

from decimal import Decimal

from app.services.embedding_models import MARENGO_MODEL_ID, NOVA_MODEL_ID
from app.services.embedding_pricing import parse_embedding_pricing

NOVA_MARKUP = (
    "<p>{regionSelector}</p><table><thead><tr>"
    "<th><strong>Amazon Nova models</strong></th>"
    "<th><strong>Price per 1M token text input</strong></th>"
    "<th><strong>Price per standard image input</strong></th>"
    "<th><strong>Price per document image input</strong></th>"
    "<th><strong>Price per second of video input</strong></th>"
    "<th><strong>Price per second of audio input</strong></th>"
    "</tr></thead><tbody>"
    "<tr><td>Amazon Nova Multimodal Embeddings (On-demand)</td>"
    "<td>{priceOf!bedrock/bedrock!NTEXT!*!1000}</td>"
    "<td>{priceOf!bedrock/bedrock!NSTD}</td>"
    "<td>{priceOf!bedrock/bedrock!NDOC}</td>"
    "<td>{priceOf!bedrock/bedrock!NVID}</td>"
    "<td>{priceOf!bedrock/bedrock!NAUD}</td></tr>"
    "<tr><td>Amazon Nova Multimodal Embeddings (Batch)</td>"
    "<td>{priceOf!bedrock/bedrock!BTEXT!*!1000}</td>"
    "<td>{priceOf!bedrock/bedrock!BSTD}</td>"
    "<td>{priceOf!bedrock/bedrock!BDOC}</td>"
    "<td>{priceOf!bedrock/bedrock!BVID}</td>"
    "<td>{priceOf!bedrock/bedrock!BAUD}</td></tr>"
    "</tbody></table>"
)

MARENGO_MARKUP = (
    "<h2>Geo and In-region Cross-region Inference</h2><p>{regionSelector}</p>"
    "<table><thead><tr><th><strong>TwelveLabs models</strong></th>"
    "<th><strong>Price per second of video input</strong></th>"
    "<th><strong>Price per second of audio input</strong></th>"
    "<th>Price per image input</th>"
    "<th><strong>Price per text request</strong></th>"
    "<th><strong>Price per 1M output tokens</strong></th></tr></thead><tbody>"
    "<tr><td>Marengo Embed 2.7</td>"
    "<td>{priceOf!bedrockfoundationmodels/bedrockfoundationmodels!OLDV!opt}</td>"
    "<td>NA</td><td>NA</td><td>NA</td><td>NA</td></tr>"
    "<tr><td>Marengo Embed 3.0</td>"
    "<td>{priceOf!bedrockfoundationmodels/bedrockfoundationmodels!MVID!opt}</td>"
    "<td>{priceOf!bedrockfoundationmodels/bedrockfoundationmodels!MAUD!opt}</td>"
    "<td>{priceOf!bedrockfoundationmodels/bedrockfoundationmodels!MIMG!opt}</td>"
    "<td>{priceOf!bedrockfoundationmodels/bedrockfoundationmodels!MTXT!opt}</td>"
    "<td>NA</td></tr></tbody></table>"
)

PRICE_TABLES = {
    "bedrock": {
        "US East (N. Virginia)": {
            "NTEXT": {"price": "0.0001350000"},
            "NSTD": {"price": "0.0000600000"},
            "NDOC": {"price": "0.0006000000"},
            "NVID": {"price": "0.0007000000"},
            "NAUD": {"price": "0.0001400000"},
            "BTEXT": {"price": "0.0000675000"},
            "BSTD": {"price": "0.0000300000"},
        },
        "AWS GovCloud (US)": {"NTEXT": {"price": "0.0001620000"}},
    },
    "bedrockfoundationmodels": {
        "US East (N. Virginia)": {
            "OLDV": {"price": "0.0009"},
            "MVID": {"price": "0.0007000000"},
            "MAUD": {"price": "0.0001400000"},
            "MIMG": {"price": "0.0001000000"},
            "MTXT": {"price": "0.0000700000"},
        },
        "EU (Ireland)": {"MIMG": {"price": "0.0001000000"}},
    },
}

REGION_CODES = {"US East (N. Virginia)": "us-east-1", "EU (Ireland)": "eu-west-1"}


def _prices(rows, model, region):
    return {
        row["unit"]: row["price_per_unit"]
        for row in rows
        if row["model_id"] == model and row["region"] == region
    }


def test_nova_on_demand_prices_are_parsed_per_unit():
    rows = parse_embedding_pricing([NOVA_MARKUP], PRICE_TABLES, REGION_CODES)

    # Only text and image units are stored; video/audio seconds are skipped,
    # and the 10x document-image price never leaks in as an image price.
    assert _prices(rows, NOVA_MODEL_ID, "us-east-1") == {
        # $0.000135 per 1K tokens on the JSON, shown as $0.135 per 1M.
        "text_token": Decimal("0.000000135"),
        "standard_image": Decimal("0.00006"),
    }


def test_nova_batch_row_and_unmapped_regions_are_ignored():
    rows = parse_embedding_pricing([NOVA_MARKUP], PRICE_TABLES, REGION_CODES)

    # Batch prices would otherwise win for keys missing from on-demand; the
    # on-demand standard image price must be the stored one.
    assert _prices(rows, NOVA_MODEL_ID, "us-east-1")["standard_image"] == Decimal(
        "0.00006"
    )
    # GovCloud has no region-code mapping and must not appear.
    assert {row["region"] for row in rows} == {"us-east-1"}


def test_marengo_3_prices_and_output_column_is_skipped():
    rows = parse_embedding_pricing([MARENGO_MARKUP], PRICE_TABLES, REGION_CODES)

    assert _prices(rows, MARENGO_MODEL_ID, "us-east-1") == {
        "image": Decimal("0.0001"),
        "text_request": Decimal("0.00007"),
    }
    assert _prices(rows, MARENGO_MODEL_ID, "eu-west-1") == {"image": Decimal("0.0001")}
    # Marengo 2.7 is not a supported model and must not be priced.
    assert all(row["model_id"] in {NOVA_MODEL_ID, MARENGO_MODEL_ID} for row in rows)


def test_missing_sections_produce_no_rows():
    assert (
        parse_embedding_pricing(["<table></table>"], PRICE_TABLES, REGION_CODES) == []
    )


def test_eu_price_json_names_map_to_region_codes():
    from app.services.embedding_pricing import region_codes_by_display_name

    codes = region_codes_by_display_name()
    assert codes["EU (Ireland)"] == "eu-west-1"
    assert codes["Europe (Ireland)"] == "eu-west-1"
    assert codes["US East (N. Virginia)"] == "us-east-1"


async def test_embedding_pricing_failure_is_isolated_from_token_pricing_stats():
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.services.pricing_updater import PricingUpdater

    db = MagicMock()
    db.rollback = AsyncMock()
    updater = PricingUpdater(db)
    settings = MagicMock(AWS_REGION="us-east-1")
    with (
        patch("app.services.pricing_updater.get_settings", return_value=settings),
        patch.object(PricingUpdater, "_build_dynamic_mapping", return_value={}),
        patch("app.services.pricing_updater.refresh_mantle_registry", AsyncMock()),
        patch.object(updater, "_fetch_from_price_list_api", AsyncMock(return_value=[])),
        patch.object(updater, "_scrape_aws_pricing_page", AsyncMock(return_value=[])),
        patch.object(
            updater, "_backfill_from_reference_region", AsyncMock(return_value=0)
        ),
        patch.object(
            updater, "ensure_official_profile_pricing", AsyncMock(return_value=0)
        ),
        patch.object(updater, "cleanup_stale_cross_region_entries", AsyncMock()),
        patch.object(
            updater,
            "_update_embedding_pricing",
            AsyncMock(side_effect=RuntimeError("pricing page down")),
        ),
    ):
        stats = await updater.update_all_pricing()

    assert stats["embedding_failed"] is True
    assert stats["embedding_count"] == 0
    assert stats["failed"] == 0
    db.rollback.assert_awaited_once()

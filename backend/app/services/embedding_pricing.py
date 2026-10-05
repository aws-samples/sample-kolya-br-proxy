# pyright: reportMissingImports=false, reportArgumentType=false, reportAttributeAccessIssue=false
"""Daily per-modality pricing for the two supported Bedrock embedding models.

AWS publishes embedding prices in the same two public sources the chat pricing
scraper already uses:

* ``https://aws.amazon.com/bedrock/pricing/`` — ``data-pricing-markup`` tables
  whose cells reference prices as ``{priceOf!dataset/dataset!HASH[!*!1000]}``.
* ``b0.p.awsstatic.com`` meteredUnitMaps JSON — the hash → USD price per region.

Nova Multimodal Embeddings lives in the ``bedrock`` dataset (its text cell
carries ``!*!1000``: JSON is per 1K tokens, the column is per 1M tokens).
Marengo Embed 3.0 lives in ``bedrockfoundationmodels`` with per-image and
per-text-request prices used as-is. Only text and image units are stored:
the gateway embeds text and inline images, nothing else.

Parsing is header-driven so column reordering does not mis-assign prices. A
failed or empty fetch never deletes existing rows: billing keeps using the
last successfully published prices.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from decimal import Decimal
from html import unescape
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embedding_pricing import EmbeddingPricing
from app.services.embedding_models import MARENGO_MODEL_ID, NOVA_MODEL_ID

logger = logging.getLogger(__name__)

PRICING_PAGE_URL = "https://aws.amazon.com/bedrock/pricing/"
PRICING_SOURCE = "aws-pricing-page"

# Billable units. Prices are stored per single unit (one token, one image,
# one request). Nova bills images as "standard"; Marengo has one image price.
TEXT_TOKEN = "text_token"  # noqa: S105 - billing unit name, not a credential
TEXT_REQUEST = "text_request"
IMAGE = "image"
STANDARD_IMAGE = "standard_image"

# Header substring → (unit or None to skip, divisor to per-unit price).
# First match wins. "document image" must be skipped explicitly: otherwise the
# generic "image input" rule would store Nova's 10x document-image price as
# its image price.
_HEADER_UNITS: tuple[tuple[str, str | None, int], ...] = (
    ("1m token text input", TEXT_TOKEN, 1_000_000),
    ("standard image", STANDARD_IMAGE, 1),
    ("document image", None, 1),
    ("text request", TEXT_REQUEST, 1),
    ("second of", None, 1),
    ("image input", IMAGE, 1),
)

# Exact (normalized) row labels. The Nova "(Batch)" row prices Bedrock batch
# inference jobs, which this gateway does not use, so it is deliberately absent.
_ROW_MODELS = {
    "amazon nova multimodal embeddings (on-demand)": NOVA_MODEL_ID,
    "marengo embed 3.0": MARENGO_MODEL_ID,
}

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_HEADER_CELL_RE = re.compile(r"<th[^>]*>(.*?)</th>", re.IGNORECASE | re.DOTALL)
_DATA_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_PRICE_REF_RE = re.compile(r"\{priceOf!([^}]+)\}")


def _text(cell: str) -> str:
    return " ".join(_TAG_RE.sub(" ", cell).split()).strip()


def _header_unit(header: str) -> tuple[str, int] | None:
    """Return ``(unit, divisor)`` for a priced column, or None to skip it."""
    normalized = header.lower()
    for needle, unit, divisor in _HEADER_UNITS:
        if needle in normalized:
            return None if unit is None else (unit, divisor)
    return None


def _parse_price_ref(ref: str) -> tuple[str, str, int]:
    """Return ``(dataset, hash, multiplier)`` for one ``priceOf`` reference."""
    parts = ref.split("!")
    dataset = parts[0].split("/")[0]
    hash_key = parts[1] if len(parts) > 1 else ref
    multiplier = 1000 if "*" in parts[2:] and "1000" in parts[2:] else 1
    return dataset, hash_key, multiplier


def parse_embedding_pricing(
    markups: list[str],
    price_tables: dict[str, dict[str, dict[str, Any]]],
    region_codes: dict[str, str],
) -> list[dict[str, Any]]:
    """Extract per-unit prices for supported embedding models.

    Args:
        markups: Decoded ``data-pricing-markup`` HTML fragments.
        price_tables: ``{dataset: {region display name: {hash: entry}}}``.
        region_codes: Region display name → region code.

    Returns:
        Rows of ``{model_id, region, unit, price_per_unit}``; the first
        occurrence of each ``(model, region, unit)`` wins.
    """
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for markup in markups:
        table_rows = _ROW_RE.findall(markup)
        headers: list[str] = []
        for row in table_rows:
            header_cells = _HEADER_CELL_RE.findall(row)
            if header_cells:
                headers = [_text(cell) for cell in header_cells]
                continue
            cells = _DATA_CELL_RE.findall(row)
            if not cells or not headers:
                continue
            model_id = _ROW_MODELS.get(_text(cells[0]).lower())
            if model_id is None:
                continue

            # Rows may have fewer cells than headers; extra columns are ignored.
            for header, cell in zip(headers[1:], cells[1:], strict=False):
                unit_info = _header_unit(header)
                ref_match = _PRICE_REF_RE.search(cell)
                if unit_info is None or ref_match is None:
                    continue
                unit, divisor = unit_info
                dataset, hash_key, multiplier = _parse_price_ref(ref_match.group(1))
                for region_name, entries in price_tables.get(dataset, {}).items():
                    region = region_codes.get(region_name)
                    entry = entries.get(hash_key)
                    if region is None or not entry or "price" not in entry:
                        continue
                    key = (model_id, region, unit)
                    if key in seen:
                        continue
                    try:
                        displayed = Decimal(str(entry["price"])) * multiplier
                    except ArithmeticError:
                        continue
                    seen.add(key)
                    rows.append(
                        {
                            "model_id": model_id,
                            "region": region,
                            "unit": unit,
                            "price_per_unit": displayed / divisor,
                        }
                    )
    return rows


async def fetch_embedding_pricing() -> list[dict[str, Any]]:
    """Download the pricing page plus price JSON and parse embedding prices."""
    from app.services.pricing_updater import PricingUpdater

    urls = PricingUpdater._PRICING_JSON_URLS
    async with httpx.AsyncClient(timeout=30.0) as client:
        page, foundation, bedrock = await asyncio.gather(
            client.get(PRICING_PAGE_URL),
            client.get(urls["bedrockfoundationmodels"]),
            client.get(urls["bedrock"]),
        )
    for response in (page, foundation, bedrock):
        response.raise_for_status()

    markups = [
        unescape(raw) for raw in re.findall(r'data-pricing-markup="([^"]*)"', page.text)
    ]
    price_tables = {
        "bedrockfoundationmodels": foundation.json().get("regions", {}),
        "bedrock": bedrock.json().get("regions", {}),
    }
    return parse_embedding_pricing(
        markups, price_tables, region_codes_by_display_name()
    )


def region_codes_by_display_name() -> dict[str, str]:
    """Map price-JSON region names to codes.

    The meteredUnitMaps JSON labels European regions "EU (Ireland)" while the
    shared display-name table uses "Europe (Ireland)"; accept both.
    """
    from app.services.pricing_updater import PricingUpdater

    codes: dict[str, str] = {}
    for code, name in PricingUpdater._REGION_DISPLAY_NAMES.items():
        codes[name] = code
        if name.startswith("Europe ("):
            codes["EU (" + name[len("Europe (") :]] = code
    return codes


async def save_embedding_pricing(
    db: AsyncSession, rows: list[dict[str, Any]], source: str = PRICING_SOURCE
) -> int:
    """Upsert rows; never removes prices that are absent from this fetch."""
    now = datetime.utcnow()
    for row in rows:
        result = await db.execute(
            select(EmbeddingPricing).where(
                EmbeddingPricing.model_id == row["model_id"],
                EmbeddingPricing.region == row["region"],
                EmbeddingPricing.unit == row["unit"],
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.price_per_unit = row["price_per_unit"]
            existing.source = source
            existing.last_updated = now
        else:
            db.add(
                EmbeddingPricing(
                    model_id=row["model_id"],
                    region=row["region"],
                    unit=row["unit"],
                    price_per_unit=row["price_per_unit"],
                    currency="USD",
                    source=source,
                    last_updated=now,
                    created_at=now,
                )
            )
    await db.commit()
    return len(rows)


async def update_embedding_pricing(db: AsyncSession) -> int:
    """Fetch and persist embedding prices; warn when a model disappears."""
    rows = await fetch_embedding_pricing()
    found = {row["model_id"] for row in rows}
    for model_id in (NOVA_MODEL_ID, MARENGO_MODEL_ID):
        if model_id not in found:
            logger.warning(
                "Embedding pricing for %s not found on the AWS pricing page; "
                "keeping previously stored prices",
                model_id,
            )
    if not rows:
        return 0
    return await save_embedding_pricing(db, rows)


async def get_embedding_prices(
    db: AsyncSession, model_id: str, region: str
) -> tuple[dict[str, Decimal], str | None]:
    """Return ``({unit: price}, pricing_region)`` for one model.

    Uses the routed region when AWS publishes prices there. Otherwise falls
    back to another published region (``us-east-1`` first): Nova is only
    priced in us-east-1, and Marengo prices are identical across regions.
    """
    result = await db.execute(
        select(EmbeddingPricing).where(EmbeddingPricing.model_id == model_id)
    )
    by_region: dict[str, dict[str, Decimal]] = {}
    for row in result.scalars().all():
        by_region.setdefault(str(row.region), {})[str(row.unit)] = Decimal(
            str(row.price_per_unit)
        )
    if not by_region:
        return {}, None
    if region in by_region:
        return by_region[region], region
    fallback = "us-east-1" if "us-east-1" in by_region else sorted(by_region)[0]
    return by_region[fallback], fallback

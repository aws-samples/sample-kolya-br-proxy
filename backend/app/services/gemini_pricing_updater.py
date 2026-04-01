"""
Gemini pricing updater — scrapes https://ai.google.dev/pricing.

Strategy:
  1. Fetch the pricing page HTML.
  2. Look for an embedded JSON blob (e.g. <script id="__NEXT_DATA__"> or
     similar) that contains model names and prices.
  3. Fall back to regex-based table parsing if no JSON blob is found.

Prices are stored per-token (divide per-1M values by 1_000_000) in the
existing model_pricing table with region="global" (Gemini has no regional
pricing).
"""

import json
import logging
import re
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_pricing import ModelPricing

logger = logging.getLogger(__name__)

GEMINI_PRICING_URL = "https://ai.google.dev/pricing"
GEMINI_PRICING_REGION = "global"


class GeminiPricingUpdater:
    """Scrapes Google AI pricing page and stores Gemini model pricing in DB."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def update_all_pricing(self) -> Dict:
        """
        Fetch and store Gemini pricing data.

        Returns:
            Dict with update statistics.
        """
        stats = {"updated": 0, "failed": 0, "source": "gemini-scraper"}
        try:
            html = await self._fetch_page()
            pricing_data = self._parse_pricing(html)
            if not pricing_data:
                logger.warning("GeminiPricingUpdater: no pricing data parsed from page")
                stats["failed"] = 1
                return stats
            updated = await self._save_pricing_data(pricing_data)
            stats["updated"] = updated
            logger.info(f"Gemini pricing updated: {updated} models saved")
        except Exception as e:
            logger.error(f"GeminiPricingUpdater failed: {e}", exc_info=True)
            stats["failed"] = 1
        return stats

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    async def _fetch_page(self) -> str:
        """Download the Gemini pricing page HTML."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; KBR-Proxy-PricingBot/1.0)"
            )
        }
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(GEMINI_PRICING_URL, headers=headers)
            resp.raise_for_status()
            return resp.text

    # ------------------------------------------------------------------
    # Parse
    # ------------------------------------------------------------------

    def _parse_pricing(self, html: str) -> List[Dict]:
        """
        Parse pricing data from HTML.

        Tries multiple strategies in order:
        1. Embedded __NEXT_DATA__ / __NUXT_DATA__ JSON blob
        2. Regex table extraction
        """
        data = (
            self._try_parse_json_blob(html)
            or self._try_parse_table_regex(html)
        )
        return data or []

    def _try_parse_json_blob(self, html: str) -> Optional[List[Dict]]:
        """
        Look for embedded JSON blobs that might contain pricing.
        Google's dev site often uses __NEXT_DATA__ or similar.
        """
        # Try __NEXT_DATA__
        m = re.search(
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )
        if m:
            try:
                next_data = json.loads(m.group(1))
                result = self._extract_from_next_data(next_data)
                if result:
                    logger.info(
                        f"Gemini pricing: parsed {len(result)} models from __NEXT_DATA__"
                    )
                    return result
            except (json.JSONDecodeError, Exception) as e:
                logger.debug(f"__NEXT_DATA__ parse failed: {e}")

        # Try any inline JSON that contains "gemini" and price patterns
        pattern = re.compile(
            r'(?:window\.__(?:data|pricing|models)\s*=\s*|'
            r'"pricing"\s*:\s*)(\{.*?\}|\[.*?\])',
            re.DOTALL,
        )
        for m in pattern.finditer(html):
            try:
                blob = json.loads(m.group(1))
                result = self._extract_from_blob(blob)
                if result:
                    logger.info(
                        f"Gemini pricing: parsed {len(result)} models from inline JSON"
                    )
                    return result
            except Exception:
                continue

        return None

    def _extract_from_next_data(self, data: dict) -> Optional[List[Dict]]:
        """Recursively search __NEXT_DATA__ for pricing rows."""
        return self._extract_from_blob(data)

    def _extract_from_blob(self, blob) -> Optional[List[Dict]]:
        """Recursively search a JSON structure for Gemini pricing entries."""
        results = []
        self._walk_for_pricing(blob, results)
        return results if results else None

    def _walk_for_pricing(self, node, results: list, depth: int = 0):
        """Walk JSON tree looking for {model, input_price, output_price} patterns."""
        if depth > 20:
            return
        if isinstance(node, dict):
            # Check if this node looks like a pricing entry
            entry = self._try_extract_pricing_entry(node)
            if entry:
                results.append(entry)
                return
            for v in node.values():
                self._walk_for_pricing(v, results, depth + 1)
        elif isinstance(node, list):
            for item in node:
                self._walk_for_pricing(item, results, depth + 1)

    def _try_extract_pricing_entry(self, node: dict) -> Optional[Dict]:
        """
        Try to extract a pricing entry from a dict node.
        Look for keys containing model name + input/output price.
        """
        # Possible key names used by Google's site
        name_keys = ("model", "modelName", "name", "displayName", "title")
        input_keys = ("inputPrice", "input_price", "input", "inputCost", "pricePerInputToken")
        output_keys = ("outputPrice", "output_price", "output", "outputCost", "pricePerOutputToken")
        cached_keys = ("cachedPrice", "cached_price", "cachedInputPrice", "cachePrice")

        model_name = None
        for k in name_keys:
            if k in node and isinstance(node[k], str) and "gemini" in node[k].lower():
                model_name = node[k]
                break

        if not model_name:
            return None

        input_val = None
        for k in input_keys:
            if k in node:
                input_val = self._parse_price(node[k])
                if input_val is not None:
                    break

        output_val = None
        for k in output_keys:
            if k in node:
                output_val = self._parse_price(node[k])
                if output_val is not None:
                    break

        if input_val is None or output_val is None:
            return None

        cached_val = None
        for k in cached_keys:
            if k in node:
                cached_val = self._parse_price(node[k])
                if cached_val is not None:
                    break

        model_id = self._normalize_model_name(model_name)
        if not model_id:
            return None

        return {
            "model_id": model_id,
            "region": GEMINI_PRICING_REGION,
            "input_price_per_token": input_val / Decimal("1000000"),
            "output_price_per_token": output_val / Decimal("1000000"),
            "cached_input_price_per_token": (
                cached_val / Decimal("1000000") if cached_val is not None else None
            ),
        }

    def _try_parse_table_regex(self, html: str) -> Optional[List[Dict]]:
        """
        Fallback: extract pricing via regex from HTML tables.

        Looks for patterns like:
          Gemini 2.5 Pro  |  $1.25 / 1M  |  $10.00 / 1M
        """
        results = []

        # Match table rows containing "Gemini" and price patterns
        row_pattern = re.compile(
            r"(Gemini\s+[\d.]+\s+\w+(?:\s+\w+)?)"  # model name
            r".*?"
            r"\$\s*([\d.]+)\s*/\s*1M\s*(?:tokens?)?"  # input price
            r".*?"
            r"\$\s*([\d.]+)\s*/\s*1M\s*(?:tokens?)?",  # output price
            re.IGNORECASE | re.DOTALL,
        )

        seen = set()
        for m in row_pattern.finditer(html):
            model_name = m.group(1).strip()
            input_price = Decimal(m.group(2))
            output_price = Decimal(m.group(3))

            model_id = self._normalize_model_name(model_name)
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)

            # Try to find cached price nearby
            cached_val = None
            start = max(0, m.start() - 200)
            end = min(len(html), m.end() + 200)
            context = html[start:end]
            cache_m = re.search(
                r"cached?.*?\$\s*([\d.]+)\s*/\s*1M", context, re.IGNORECASE
            )
            if cache_m:
                try:
                    cached_val = Decimal(cache_m.group(1))
                except Exception:
                    pass

            results.append(
                {
                    "model_id": model_id,
                    "region": GEMINI_PRICING_REGION,
                    "input_price_per_token": input_price / Decimal("1000000"),
                    "output_price_per_token": output_price / Decimal("1000000"),
                    "cached_input_price_per_token": (
                        cached_val / Decimal("1000000")
                        if cached_val is not None
                        else None
                    ),
                }
            )

        if results:
            logger.info(
                f"Gemini pricing: parsed {len(results)} models via table regex"
            )
        return results if results else None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_price(self, value) -> Optional[Decimal]:
        """Parse a price value (string like '$1.25', number 1.25, etc.) → Decimal."""
        if value is None:
            return None
        try:
            if isinstance(value, (int, float)):
                return Decimal(str(value))
            if isinstance(value, str):
                cleaned = re.sub(r"[^\d.]", "", value)
                if cleaned:
                    return Decimal(cleaned)
        except Exception:
            pass
        return None

    def _normalize_model_name(self, name: str) -> Optional[str]:
        """
        Convert display name to model_id used in API calls.

        Examples:
          "Gemini 2.5 Pro"         → "gemini-2.5-pro"
          "Gemini 2.0 Flash"       → "gemini-2.0-flash"
          "Gemini 2.5 Flash-Lite"  → "gemini-2.5-flash-lite"
          "gemini-2.5-pro"         → "gemini-2.5-pro"  (already an ID)
        """
        name = name.strip()

        # Already in ID format
        if re.match(r"^gemini-[\d]", name, re.IGNORECASE):
            return name.lower()

        # Convert display name → id
        # Remove "Gemini " prefix, lowercase, replace spaces/slashes with hyphens
        cleaned = re.sub(r"^gemini\s+", "", name, flags=re.IGNORECASE)
        model_id = "gemini-" + re.sub(r"[\s/]+", "-", cleaned).lower()
        model_id = re.sub(r"-+", "-", model_id).rstrip("-")

        # Verify it looks reasonable (contains a version number)
        if not re.search(r"\d", model_id):
            return None

        return model_id

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    async def _save_pricing_data(self, pricing_data: List[Dict]) -> int:
        """
        Upsert pricing data into model_pricing table.
        Follows the same pattern as PricingUpdater._save_pricing_data().
        """
        updated_count = 0
        now = datetime.utcnow()
        source = "gemini-scraper"

        for data in pricing_data:
            try:
                stmt = select(ModelPricing).where(
                    ModelPricing.model_id == data["model_id"],
                    ModelPricing.region == data["region"],
                )
                result = await self.db.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    existing.input_price_per_token = data["input_price_per_token"]
                    existing.output_price_per_token = data["output_price_per_token"]
                    existing.source = source
                    existing.last_updated = now
                    # Update cached price if column exists and we have data
                    if (
                        data.get("cached_input_price_per_token") is not None
                        and hasattr(existing, "cached_input_price_per_token")
                    ):
                        existing.cached_input_price_per_token = data[
                            "cached_input_price_per_token"
                        ]
                else:
                    kwargs = dict(
                        model_id=data["model_id"],
                        region=data["region"],
                        input_price_per_token=data["input_price_per_token"],
                        output_price_per_token=data["output_price_per_token"],
                        currency="USD",
                        source=source,
                        last_updated=now,
                        created_at=now,
                    )
                    # Only set cached price if column exists on the model
                    if (
                        data.get("cached_input_price_per_token") is not None
                        and hasattr(ModelPricing, "cached_input_price_per_token")
                    ):
                        kwargs["cached_input_price_per_token"] = data[
                            "cached_input_price_per_token"
                        ]
                    self.db.add(ModelPricing(**kwargs))

                updated_count += 1
            except Exception as e:
                logger.error(
                    f"Failed to save Gemini pricing for {data.get('model_id')}: {e}"
                )

        await self.db.commit()
        return updated_count

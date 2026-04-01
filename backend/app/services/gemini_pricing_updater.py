"""
Gemini pricing updater — three-tier strategy:

  1. Google official pricing page  (https://ai.google.dev/gemini-api/docs/pricing)
     Parse <table> elements preceded by <h2/h3> model headings.
     Works with Googlebot UA which receives SSR HTML.

  2. LiteLLM public JSON  (GitHub raw, no package installed)
     https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json
     Fills in models missing from the live page (e.g. preview/experimental models).

  3. Built-in static table
     Only legacy / deprecated models that neither live source reliably covers:
       gemini-1.5-pro, gemini-1.5-flash, gemini-1.5-flash-8b
     Prices verified against https://ai.google.dev/gemini-api/docs/pricing (2026-04).

Results from all three tiers are merged (later tiers only fill gaps, never overwrite).
Prices are stored per-token in model_pricing with region="global".
"""

import json
import logging
import re
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_pricing import ModelPricing

logger = logging.getLogger(__name__)

GEMINI_PRICING_URL = "https://ai.google.dev/gemini-api/docs/pricing"
LITELLM_PRICES_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main"
    "/model_prices_and_context_window.json"
)
GEMINI_PRICING_REGION = "global"

# ---------------------------------------------------------------------------
# Static fallback — ONLY legacy models not covered by live sources.
# Verified against Google official page 2026-04.
# Format: (model_id, input $/1M, output $/1M, cached_input $/1M or None)
# ---------------------------------------------------------------------------
_LEGACY_GEMINI_PRICING: List[Tuple] = [
    ("gemini-1.5-pro",      1.25,   5.00,  0.3125),
    ("gemini-1.5-flash",    0.075,  0.30,  0.01875),
    ("gemini-1.5-flash-8b", 0.0375, 0.15,  0.01),
]

# ---------------------------------------------------------------------------
# Pricing entry type alias
# ---------------------------------------------------------------------------
PricingEntry = Dict  # keys: model_id, region, input_price_per_token,
                     #       output_price_per_token, cached_input_price_per_token


class GeminiPricingUpdater:
    """Fetches Google Gemini model pricing via three-tier strategy and saves to DB."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # -----------------------------------------------------------------------
    # Public entry point
    # -----------------------------------------------------------------------

    async def update_all_pricing(self) -> Dict:
        """
        Run all three tiers and merge results, then save to DB.

        Returns:
            Dict with update statistics.
        """
        merged: Dict[str, PricingEntry] = {}  # model_id → entry

        # Tier 1: Google official page
        try:
            html = await self._fetch_google_page()
            google_data = self._parse_google_html(html)
            for entry in google_data:
                merged[entry["model_id"]] = entry
            logger.info(f"Gemini pricing tier-1 (Google): {len(google_data)} models")
        except Exception as e:
            logger.warning(f"Gemini pricing tier-1 failed: {e}")

        # Tier 2: LiteLLM public JSON (HTTP fetch, no package)
        try:
            litellm_data = await self._fetch_litellm_prices()
            added = 0
            for entry in litellm_data:
                if entry["model_id"] not in merged:
                    merged[entry["model_id"]] = entry
                    added += 1
            logger.info(f"Gemini pricing tier-2 (LiteLLM): {added} new models added")
        except Exception as e:
            logger.warning(f"Gemini pricing tier-2 failed: {e}")

        # Tier 3: static legacy table
        added = 0
        for entry in self._legacy_pricing_data():
            if entry["model_id"] not in merged:
                merged[entry["model_id"]] = entry
                added += 1
        logger.info(f"Gemini pricing tier-3 (static legacy): {added} models added")

        if not merged:
            logger.error("GeminiPricingUpdater: all three tiers failed, no pricing data")
            return {"updated": 0, "failed": 1, "source": "none"}

        pricing_list = list(merged.values())
        try:
            updated = await self._save_pricing_data(pricing_list)
            logger.info(f"Gemini pricing saved: {updated} models total")
            return {"updated": updated, "failed": 0, "source": "gemini-multi-tier"}
        except Exception as e:
            logger.error(f"GeminiPricingUpdater: save failed: {e}", exc_info=True)
            return {"updated": 0, "failed": 1, "source": "gemini-multi-tier"}

    # -----------------------------------------------------------------------
    # Tier 1: Google official page
    # -----------------------------------------------------------------------

    async def _fetch_google_page(self) -> str:
        """Fetch Google AI pricing page HTML using Googlebot UA (gets SSR content)."""
        headers = {
            "User-Agent": "Googlebot/2.1 (+http://www.google.com/bot.html)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(GEMINI_PRICING_URL, headers=headers)
            resp.raise_for_status()
            return resp.text

    def _parse_google_html(self, html: str) -> List[PricingEntry]:
        """
        Parse pricing tables from Google's SSR HTML.

        Strategy: find each <table> that contains "Input price" and "Output price",
        then look backwards for the nearest <h2>/<h3> that contains "Gemini N.N".
        The page renders two rows per model (standard + batch half-price); we take
        the first occurrence (standard pricing).
        """
        # Collect heading positions and text
        headings: List[Tuple[int, str]] = [
            (m.start(), re.sub(r"<[^>]+>", "", m.group()).strip())
            for m in re.finditer(r"<h[23][^>]*>.*?</h[23]>", html, re.DOTALL)
        ]

        # Find all <table>…</table> blocks with their start positions
        tables: List[Tuple[int, str]] = [
            (m.start(), m.group())
            for m in re.finditer(r"<table[^>]*>.*?</table>", html, re.DOTALL | re.IGNORECASE)
        ]

        seen_models: set = set()
        results: List[PricingEntry] = []

        for tpos, table_html in tables:
            clean = re.sub(r"<[^>]+>", " ", table_html)
            clean = re.sub(r"\s+", " ", clean)

            # Only process pricing tables
            if "Input price" not in clean or "Output price" not in clean:
                continue

            # Find closest preceding heading with a "Gemini N.N" pattern
            model_display = None
            for hpos, htext in reversed(headings):
                if hpos < tpos and re.search(r"Gemini\s+[\d.]", htext, re.IGNORECASE):
                    model_display = re.sub(r"\s+", " ", htext).strip()
                    break
            if not model_display:
                continue

            model_id = self._display_name_to_id(model_display)
            if not model_id or model_id in seen_models:
                continue
            seen_models.add(model_id)

            inp_m = re.search(r"Input price[^$]{0,80}\$([\d.]+)", clean)
            out_m = re.search(r"Output price[^$]{0,120}\$([\d.]+)", clean)
            if not inp_m or not out_m:
                continue

            cache_m = re.search(r"[Cc]ach(?:e|ing) price[^$]{0,80}\$([\d.]+)", clean)

            entry = self._make_entry(
                model_id=model_id,
                inp=Decimal(inp_m.group(1)),
                out=Decimal(out_m.group(1)),
                cache=Decimal(cache_m.group(1)) if cache_m else None,
            )
            results.append(entry)

        return results

    # -----------------------------------------------------------------------
    # Tier 2: LiteLLM public JSON (HTTP only, no package)
    # -----------------------------------------------------------------------

    async def _fetch_litellm_prices(self) -> List[PricingEntry]:
        """
        Fetch LiteLLM's open-source model price database from GitHub (raw JSON).
        No litellm package is installed — this is a plain HTTP GET.

        Filters:
        - Keys starting with "gemini" but NOT "gemini/" prefix (those are duplicates)
        - Must have non-zero input AND output prices
        """
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(LITELLM_PRICES_URL)
            resp.raise_for_status()
            data: dict = resp.json()

        results: List[PricingEntry] = []
        for key, info in data.items():
            # Only plain "gemini-*" keys (skip "gemini/gemini-*" duplicates)
            if not key.startswith("gemini") or key.startswith("gemini/"):
                continue
            if "input_cost_per_token" not in info:
                continue

            inp_per_token = info.get("input_cost_per_token", 0)
            out_per_token = info.get("output_cost_per_token", 0)

            # Skip free / zero-price entries (experimental models with no real pricing)
            if not inp_per_token or not out_per_token:
                continue

            cache_per_token = info.get("cache_read_input_token_cost")

            # Convert per-token → per-1M for make_entry (which expects $/1M)
            entry = self._make_entry(
                model_id=key,
                inp=Decimal(str(inp_per_token)) * Decimal("1000000"),
                out=Decimal(str(out_per_token)) * Decimal("1000000"),
                cache=(
                    Decimal(str(cache_per_token)) * Decimal("1000000")
                    if cache_per_token
                    else None
                ),
            )
            results.append(entry)

        return results

    # -----------------------------------------------------------------------
    # Tier 3: Static legacy table
    # -----------------------------------------------------------------------

    @staticmethod
    def _legacy_pricing_data() -> List[PricingEntry]:
        """
        Built-in prices for legacy / deprecated Gemini models.
        Only models that are no longer listed on the live Google pricing page
        and whose LiteLLM entries have missing or zero prices.

        Source: https://ai.google.dev/gemini-api/docs/pricing (archived, 2026-04)
        """
        results = []
        for model_id, inp, out, cached in _LEGACY_GEMINI_PRICING:
            results.append(
                GeminiPricingUpdater._make_entry(
                    model_id=model_id,
                    inp=Decimal(str(inp)),
                    out=Decimal(str(out)),
                    cache=Decimal(str(cached)) if cached is not None else None,
                )
            )
        return results

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _make_entry(
        model_id: str,
        inp: Decimal,
        out: Decimal,
        cache: Optional[Decimal],
    ) -> PricingEntry:
        """Build a pricing entry dict; inp/out/cache are in $/1M tokens."""
        return {
            "model_id": model_id,
            "region": GEMINI_PRICING_REGION,
            "input_price_per_token": inp / Decimal("1000000"),
            "output_price_per_token": out / Decimal("1000000"),
            "cached_input_price_per_token": (
                cache / Decimal("1000000") if cache is not None else None
            ),
        }

    @staticmethod
    def _display_name_to_id(name: str) -> Optional[str]:
        """
        Convert Google display name → API model ID.

        Examples:
          "Gemini 2.5 Pro"           → "gemini-2.5-pro"
          "Gemini 2.5 Flash-Lite"    → "gemini-2.5-flash-lite"
          "Gemini 2.0 Flash 🍌"       → "gemini-2.0-flash"
          "gemini-2.5-pro"           → "gemini-2.5-pro"  (already ID format)
        """
        name = name.strip()

        # Already in id format
        if re.match(r"^gemini-[\d]", name, re.IGNORECASE):
            return name.lower()

        # Strip emoji / parenthetical suffixes  (🍌, (Live API), etc.)
        name = re.sub(r"[\U00010000-\U0010ffff]", "", name)  # emoji
        name = re.sub(r"\(.*?\)", "", name)                   # parentheticals
        name = name.strip()

        # "Gemini X.Y Something" → "gemini-x.y-something"
        cleaned = re.sub(r"^[Gg]emini\s+", "", name)
        model_id = "gemini-" + re.sub(r"[\s/]+", "-", cleaned).lower()
        model_id = re.sub(r"-+", "-", model_id).rstrip("-")

        # Must contain a version number
        if not re.search(r"\d", model_id):
            return None

        return model_id

    # -----------------------------------------------------------------------
    # Save
    # -----------------------------------------------------------------------

    async def _save_pricing_data(self, pricing_data: List[PricingEntry]) -> int:
        """Upsert all pricing entries into model_pricing table."""
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

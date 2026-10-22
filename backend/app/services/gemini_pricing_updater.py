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

import logging
import re
from datetime import date, datetime
from html import unescape
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

# Bounds ($/1M tokens) for third-party price data; out-of-range values are
# treated as tampered/corrupt so they can't zero out or inflate billing.
_MIN_PRICE_PER_1M = Decimal("0.005")
_MAX_PRICE_PER_1M = Decimal("500")
_GEMINI_MODEL_ID_RE = re.compile(r"^gemini-[a-z0-9][a-z0-9.\-]{0,99}$")

# ---------------------------------------------------------------------------
# Static fallback — ONLY legacy models not covered by live sources.
# Verified against Google official page 2026-04.
# Format: (model_id, input $/1M, output $/1M, cached_input $/1M or None)
# ---------------------------------------------------------------------------
_LEGACY_GEMINI_PRICING: List[Tuple] = [
    ("gemini-1.5-pro", 1.25, 5.00, 0.3125),
    ("gemini-1.5-flash", 0.075, 0.30, 0.01875),
    ("gemini-1.5-flash-8b", 0.0375, 0.15, 0.01),
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
            litellm_data, litellm_tiered = await self._fetch_litellm_prices()
            added = 0
            for entry in litellm_data:
                if entry["model_id"] not in merged:
                    merged[entry["model_id"]] = entry
                    added += 1
            logger.info(f"Gemini pricing tier-2 (LiteLLM): {added} new models added")
            # Third-party tier data is not trusted for billing (it has been
            # stale before); surface it so an operator can check the model card.
            unverified = sorted(
                mid
                for mid in litellm_tiered
                if mid in merged and "long_context_threshold" not in merged[mid]
            )
            if unverified:
                logger.warning(
                    "Gemini pricing: LiteLLM lists context-tiered rates for "
                    f"{unverified}, which Google's page does not cover; billing "
                    "at the single LiteLLM base rate"
                )
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
            logger.error(
                "GeminiPricingUpdater: all three tiers failed, no pricing data"
            )
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

    def _parse_google_html(
        self, html: str, today: Optional[date] = None
    ) -> List[PricingEntry]:
        """
        Parse pricing tables from Google's SSR HTML.

        Strategy: find each <table> that contains "Input price" and "Output price",
        then look backwards for the nearest <h2>/<h3> that contains "Gemini N.N".
        Each model renders Standard first, then Batch/Flex/Priority tabs; we take
        the first occurrence (Standard pricing).

        Paid-tier cells may carry a long-context band ("$1.25, prompts <= 200k
        tokens<br>$2.50, prompts > 200k tokens") or a scheduled change ("$2.00
        through November 30, 2026. $4.00 starting December 1, 2026.").
        """
        today = today or datetime.utcnow().date()
        # Collect heading positions and text
        headings: List[Tuple[int, str]] = [
            (m.start(), re.sub(r"<[^>]+>", "", m.group()).strip())
            for m in re.finditer(r"<h[23][^>]*>.*?</h[23]>", html, re.DOTALL)
        ]

        # Find all <table>…</table> blocks with their start positions
        tables: List[Tuple[int, str]] = [
            (m.start(), m.group())
            for m in re.finditer(
                r"<table[^>]*>.*?</table>", html, re.DOTALL | re.IGNORECASE
            )
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

            model_ids = [
                mid
                for mid in (
                    self._display_name_to_id(name)
                    for name in self._split_heading(model_display)
                )
                if mid and mid not in seen_models
            ]
            if not model_ids:
                continue

            inp = self._parse_price_cell(
                self._paid_cell(table_html, "Input price"), today
            )
            out = self._parse_price_cell(
                self._paid_cell(table_html, "Output price"), today
            )
            cache = self._parse_price_cell(
                self._paid_cell(table_html, r"Context caching price"), today
            )
            if inp is None or out is None:
                continue

            long_threshold = (
                inp[2] if inp[1] is not None and out[1] is not None else None
            )
            for model_id in model_ids:
                seen_models.add(model_id)
                results.append(
                    self._make_entry(
                        model_id=model_id,
                        inp=inp[0],
                        out=out[0],
                        cache=cache[0] if cache else None,
                        long_threshold=long_threshold,
                        long_inp=inp[1] if long_threshold else None,
                        long_out=out[1] if long_threshold else None,
                        long_cache=cache[1] if cache and long_threshold else None,
                    )
                )

        return results

    @staticmethod
    def _split_heading(heading: str) -> List[str]:
        """'Gemini A, Gemini B, and Gemini C' → three names (one name otherwise)."""
        parts = [
            p.strip()
            for p in re.split(r",\s*(?:and\s+)?|\s+and\s+", heading)
            if p.strip()
        ]
        if len(parts) > 1 and all(re.match(r"(?i)gemini\b", p) for p in parts):
            return parts
        return [heading]

    @staticmethod
    def _paid_cell(table_html: str, label: str) -> Optional[str]:
        """Inner HTML of the last $-bearing cell in the row labelled *label*."""
        row = re.search(
            rf"<tr[^>]*>\s*<td[^>]*>\s*{label}.*?</tr>",
            table_html,
            re.DOTALL | re.IGNORECASE,
        )
        if not row:
            return None
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row.group(), re.DOTALL)
        priced = [c for c in cells[1:] if "$" in c]
        return priced[-1] if priced else None

    @staticmethod
    def _parse_price_cell(
        cell: Optional[str], today: date
    ) -> Optional[Tuple[Decimal, Optional[Decimal], Optional[int]]]:
        """(short $/1M, long $/1M or None, long threshold or None)."""
        if cell is None:
            return None
        # Real tags start with a letter or "/"; keep literal "<= 200k".
        text = re.sub(r"<br\s*/?>", " ; ", cell, flags=re.IGNORECASE)
        text = re.sub(r"</?[A-Za-z][^>]*>", " ", text)
        text = re.sub(r"\s+", " ", unescape(text)).strip()

        scheduled = re.search(
            r"\$([\d.]+) through ([A-Z][a-z]+ \d{1,2}, \d{4})\.?[\s;]*"
            r"\$([\d.]+) starting ([A-Z][a-z]+ \d{1,2}, \d{4})",
            text,
        )
        if scheduled:
            starts = datetime.strptime(scheduled.group(4), "%B %d, %Y").date()
            price = scheduled.group(3) if today >= starts else scheduled.group(1)
            return Decimal(price), None, None

        long_m = re.search(r"\$([\d.]+),\s*prompts\s*>\s*(\d+)\s*k", text)
        short_m = re.search(
            r"\$([\d.]+),\s*prompts\s*<=?\s*\d+\s*k", text
        ) or re.search(r"\$([\d.]+)", text)
        if not short_m:
            return None
        if long_m:
            return (
                Decimal(short_m.group(1)),
                Decimal(long_m.group(1)),
                int(long_m.group(2)) * 1000,
            )
        return Decimal(short_m.group(1)), None, None

    # -----------------------------------------------------------------------
    # Tier 2: LiteLLM public JSON (HTTP only, no package)
    # -----------------------------------------------------------------------

    async def _fetch_litellm_prices(self) -> Tuple[List[PricingEntry], List[str]]:
        """
        Fetch LiteLLM's open-source model price database from GitHub (raw JSON).
        No litellm package is installed — this is a plain HTTP GET.

        Filters:
        - Keys starting with "gemini" but NOT "gemini/" prefix (those are duplicates)
        - Must have non-zero input AND output prices
        """
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            resp = await client.get(LITELLM_PRICES_URL)
            resp.raise_for_status()
            data = resp.json()
        if not isinstance(data, dict):
            raise ValueError("LiteLLM price data is not a JSON object")

        results: List[PricingEntry] = []
        tiered: List[str] = []
        rejected = 0
        for key, info in data.items():
            # Only plain "gemini-*" keys (skip "gemini/gemini-*" duplicates)
            if not key.startswith("gemini") or key.startswith("gemini/"):
                continue
            if not isinstance(info, dict) or "input_cost_per_token" not in info:
                continue

            inp_per_token = info.get("input_cost_per_token", 0)
            out_per_token = info.get("output_cost_per_token", 0)

            # Skip free / zero-price entries (experimental models with no real pricing)
            if not inp_per_token or not out_per_token:
                continue

            cache_per_token = info.get("cache_read_input_token_cost")

            try:
                inp = Decimal(str(inp_per_token)) * Decimal("1000000")
                out = Decimal(str(out_per_token)) * Decimal("1000000")
                cache = (
                    Decimal(str(cache_per_token)) * Decimal("1000000")
                    if cache_per_token
                    else None
                )
            except (ArithmeticError, ValueError):
                rejected += 1
                continue

            if not self._is_sane_entry(key, inp, out, cache):
                rejected += 1
                continue

            results.append(
                self._make_entry(model_id=key, inp=inp, out=out, cache=cache)
            )
            if any(f.startswith("input_cost_per_token_above_") for f in info):
                tiered.append(key)

        if rejected:
            logger.warning(
                f"Gemini pricing tier-2 (LiteLLM): rejected {rejected} "
                "entries with invalid model id or out-of-range prices"
            )
        return results, tiered

    @staticmethod
    def _is_sane_entry(
        model_id: str, inp: Decimal, out: Decimal, cache: Optional[Decimal]
    ) -> bool:
        if not _GEMINI_MODEL_ID_RE.match(model_id):
            return False
        for price in (inp, out) + ((cache,) if cache is not None else ()):
            if not price.is_finite() or not (
                _MIN_PRICE_PER_1M <= price <= _MAX_PRICE_PER_1M
            ):
                return False
        return True

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
        long_threshold: Optional[int] = None,
        long_inp: Optional[Decimal] = None,
        long_out: Optional[Decimal] = None,
        long_cache: Optional[Decimal] = None,
    ) -> PricingEntry:
        """Build a pricing entry dict; prices are in $/1M tokens."""
        million = Decimal("1000000")
        entry = {
            "model_id": model_id,
            "region": GEMINI_PRICING_REGION,
            "input_price_per_token": inp / million,
            "output_price_per_token": out / million,
            "cached_input_price_per_token": (
                cache / million if cache is not None else None
            ),
        }
        if long_threshold and long_inp is not None and long_out is not None:
            entry["long_context_threshold"] = long_threshold
            entry["long_input_price_per_token"] = long_inp / million
            entry["long_output_price_per_token"] = long_out / million
            entry["long_cached_input_price_per_token"] = (
                long_cache / million if long_cache is not None else None
            )
        return entry

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
        name = re.sub(r"\(.*?\)", "", name)  # parentheticals
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
                    existing.apply_source_rates(data)
                    existing.source = source
                    existing.last_updated = now
                    if data.get("cached_input_price_per_token") is not None and hasattr(
                        existing, "cached_input_price_per_token"
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
                    if data.get("cached_input_price_per_token") is not None and hasattr(
                        ModelPricing, "cached_input_price_per_token"
                    ):
                        kwargs["cached_input_price_per_token"] = data[
                            "cached_input_price_per_token"
                        ]
                    record = ModelPricing(**kwargs)
                    record.apply_source_rates(data)
                    self.db.add(record)

                updated_count += 1
            except Exception as e:
                logger.error(
                    f"Failed to save Gemini pricing for {data.get('model_id')}: {e}"
                )

        await self.db.commit()
        return updated_count

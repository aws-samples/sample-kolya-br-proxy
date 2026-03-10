"""
Pricing updater service - fetches latest pricing from AWS.

Pricing is fetched only for the configured AWS_REGION.
Models are stored with two naming conventions:
  - Standard (on-demand): base model ID, e.g. "meta.llama3-3-70b-instruct-v1:0"
  - Cross-Region inference: geographic prefix, e.g. "us.amazon.nova-pro-v1:0"

Claude models are NOT in the AWS Price List API. They are extracted by
combining two public data sources — no browser automation required:
  1. Static HTML from https://aws.amazon.com/bedrock/pricing/ which contains
     ``data-pricing-markup`` attributes with model names and ``{priceOf!...!HASH}``
     token references.
  2. A JSON pricing endpoint at b0.p.awsstatic.com that maps the hash keys to
     actual USD prices, keyed by region display name.
"""

import asyncio
import logging
import re
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import get_settings
from app.models.model_pricing import ModelPricing

logger = logging.getLogger(__name__)


class PricingUpdater:
    """Service to update model pricing from AWS sources."""

    # AWS Price List API endpoint
    PRICE_LIST_API_URL = "https://pricing.us-east-1.amazonaws.com"

    def __init__(self, db: AsyncSession):
        self.db = db

    async def update_all_pricing(self) -> Dict[str, int]:
        """
        Update pricing for all models from AWS sources.
        Uses both API and web scraper to get complete pricing data.
        Only fetches pricing for the configured AWS_REGION.

        Returns:
            Dictionary with update statistics
        """
        settings = get_settings()
        stats = {
            "updated": 0,
            "failed": 0,
            "api_count": 0,
            "scraper_count": 0,
            "sources": [],
            "region": settings.AWS_REGION,
        }

        # 1. Fetch from AWS Price List API (primary — all models)
        api_model_ids: Set[str] = set()
        try:
            api_pricing_data = await self._fetch_from_price_list_api()
            if api_pricing_data:
                api_count = await self._save_pricing_data(api_pricing_data, "api")
                stats["api_count"] = api_count
                stats["updated"] += api_count
                stats["sources"].append("api")
                # Collect base model IDs found in API (without geo prefixes)
                for d in api_pricing_data:
                    api_model_ids.add(self._strip_prefix(d["model_id"]))
                logger.info(
                    f"Updated {api_count} pricing records from AWS Price List API"
                )
        except Exception as e:
            logger.warning(f"Failed to fetch from Price List API: {e}")
            stats["failed"] += 1

        # 2. Extract Claude pricing from AWS Bedrock pricing page (secondary)
        # Claude models are not in the AWS Price List API. Pricing is extracted
        # from the static HTML markup + a public JSON pricing endpoint.
        try:
            scraped_pricing_data = await self._scrape_aws_pricing_page()
            if scraped_pricing_data:
                # Only save scraped models NOT already found in API results
                new_scraped = [
                    d
                    for d in scraped_pricing_data
                    if self._strip_prefix(d["model_id"]) not in api_model_ids
                ]
                skipped = len(scraped_pricing_data) - len(new_scraped)
                if skipped > 0:
                    logger.info(
                        f"Skipped {skipped} scraped records already present from API"
                    )
                if new_scraped:
                    scraper_count = await self._save_pricing_data(
                        new_scraped, "aws-scraper"
                    )
                    stats["scraper_count"] = scraper_count
                    stats["updated"] += scraper_count
                    stats["sources"].append("aws-scraper")
                    logger.info(
                        f"Updated {scraper_count} pricing records from AWS scraper"
                    )
        except Exception as e:
            logger.warning(f"Failed to scrape AWS pricing page: {e}")
            stats["failed"] += 1

        # Set source summary
        if stats["sources"]:
            stats["source"] = "+".join(stats["sources"])
        else:
            stats["source"] = "none"

        logger.info(
            f"Pricing update completed for region {settings.AWS_REGION}: "
            f"{stats['updated']} total records "
            f"(API: {stats['api_count']}, Scraper: {stats['scraper_count']})"
        )

        return stats

    def _extract_price_from_terms(
        self, terms: dict, product_id: str
    ) -> Optional[Decimal]:
        """
        Extract per-token price from AWS Price List API terms.

        Args:
            terms: Full terms dictionary from the API
            product_id: Product SKU to look up

        Returns:
            Price per token as Decimal, or None
        """
        on_demand = terms.get("OnDemand", {}).get(product_id, {})
        for term_data in on_demand.values():
            for dim in term_data.get("priceDimensions", {}).values():
                price_str = dim.get("pricePerUnit", {}).get("USD")
                if price_str and price_str != "0.0000000000":
                    # Price is per 1000 tokens, convert to per token
                    return Decimal(price_str) / 1000
        return None

    async def _fetch_from_price_list_api(self) -> List[Dict]:
        """
        Fetch pricing from AWS Price List API.
        Only fetches for the configured AWS_REGION.
        Distinguishes Standard (on-demand) from Cross-Region inference.

        Standard products:
          - feature = "On-demand Inference"
          - inferenceType = "Input tokens" / "Output tokens"
          - Stored as base model ID

        Cross-Region products:
          - usagetype contains "cross-region-global"
          - inferenceType = "Text Input Tokens" / "Text Output Tokens"
          - Stored with geographic prefix (e.g., "us.")

        Returns:
            List of pricing dictionaries
        """
        settings = get_settings()
        target_region = settings.AWS_REGION
        pricing_data = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.PRICE_LIST_API_URL}/offers/v1.0/aws/AmazonBedrock/current/index.json"
            )
            response.raise_for_status()
            data = response.json()

            products = data.get("products", {})
            terms = data.get("terms", {})

            # Collect products for target region only, grouped by type
            # Standard: {model_name: {"Input tokens": sku, "Output tokens": sku}}
            standard_products = {}
            # Cross-Region: {model_name: {"Text Input Tokens": sku, "Text Output Tokens": sku}}
            cross_region_products = {}

            for product_id, product in products.items():
                attrs = product.get("attributes", {})

                # Only process products for our region
                if attrs.get("regionCode") != target_region:
                    continue

                model = attrs.get("model")
                inference_type = attrs.get("inferenceType")
                usagetype = attrs.get("usagetype", "")

                if not model or not inference_type:
                    continue

                if "cross-region-global" in usagetype:
                    # Cross-Region inference product
                    if inference_type in ("Text Input Tokens", "Text Output Tokens"):
                        cross_region_products.setdefault(model, {})[inference_type] = (
                            product_id
                        )
                elif attrs.get("feature") == "On-demand Inference":
                    # Standard on-demand product
                    if inference_type in ("Input tokens", "Output tokens"):
                        standard_products.setdefault(model, {})[inference_type] = (
                            product_id
                        )

            # Extract Standard pricing
            unmatched_standard = []
            for model, type_map in standard_products.items():
                input_id = type_map.get("Input tokens")
                output_id = type_map.get("Output tokens")
                if not input_id or not output_id:
                    continue

                input_price = self._extract_price_from_terms(terms, input_id)
                output_price = self._extract_price_from_terms(terms, output_id)

                if input_price is not None and output_price is not None:
                    model_id = self._map_model_name_to_id(model)
                    if model_id:
                        pricing_data.append(
                            {
                                "model_id": model_id,
                                "region": target_region,
                                "input_price_per_token": input_price,
                                "output_price_per_token": output_price,
                            }
                        )
                    else:
                        unmatched_standard.append(model)

            # Extract Cross-Region pricing
            # Store with geographic prefix only (e.g., "us.amazon.nova-pro-v1:0")
            # "global." is NOT a valid Bedrock identifier and is not used
            from app.services.bedrock import BedrockClient

            geo_prefix = BedrockClient.get_geo_prefix(target_region)

            unmatched_cross_region = []
            for model, type_map in cross_region_products.items():
                input_id = type_map.get("Text Input Tokens")
                output_id = type_map.get("Text Output Tokens")
                if not input_id or not output_id:
                    continue

                input_price = self._extract_price_from_terms(terms, input_id)
                output_price = self._extract_price_from_terms(terms, output_id)

                if input_price is not None and output_price is not None:
                    base_model_id = self._map_model_name_to_id(model)
                    if base_model_id:
                        pricing_data.append(
                            {
                                "model_id": f"{geo_prefix}.{base_model_id}",
                                "region": target_region,
                                "input_price_per_token": input_price,
                                "output_price_per_token": output_price,
                            }
                        )
                    else:
                        unmatched_cross_region.append(model)

            if unmatched_standard:
                logger.warning(
                    f"Unmatched standard model names from API (no mapping): {unmatched_standard}"
                )
            if unmatched_cross_region:
                logger.warning(
                    f"Unmatched cross-region model names from API (no mapping): {unmatched_cross_region}"
                )

        standard_count = len(
            [
                d
                for d in pricing_data
                if d["model_id"] == self._strip_prefix(d["model_id"])
            ]
        )
        cross_region_count = len(
            [
                d
                for d in pricing_data
                if d["model_id"] != self._strip_prefix(d["model_id"])
            ]
        )
        logger.info(
            f"Fetched {len(pricing_data)} pricing records from AWS Price List API "
            f"for region {target_region} (standard: {standard_count}, cross-region: {cross_region_count})"
        )
        return pricing_data

    @staticmethod
    def _strip_prefix(model_id: str) -> str:
        """Strip cross-region geographic prefix from a model ID to get the base ID."""
        for pfx in ("us.", "eu.", "apac.", "au.", "ca.", "jp."):
            if model_id.startswith(pfx):
                return model_id[len(pfx) :]
        return model_id

    # AWS region code → display name used in the pricing JSON
    _REGION_DISPLAY_NAMES = {
        "us-east-1": "US East (N. Virginia)",
        "us-east-2": "US East (Ohio)",
        "us-west-1": "US West (N. California)",
        "us-west-2": "US West (Oregon)",
        "ca-central-1": "Canada (Central)",
        "ca-west-1": "Canada West (Calgary)",
        "eu-central-1": "Europe (Frankfurt)",
        "eu-west-1": "Europe (Ireland)",
        "eu-west-2": "Europe (London)",
        "eu-west-3": "Europe (Paris)",
        "eu-north-1": "Europe (Stockholm)",
        "eu-central-2": "Europe (Zurich)",
        "ap-south-1": "Asia Pacific (Mumbai)",
        "ap-northeast-1": "Asia Pacific (Tokyo)",
        "ap-northeast-2": "Asia Pacific (Seoul)",
        "ap-northeast-3": "Asia Pacific (Osaka)",
        "ap-southeast-1": "Asia Pacific (Singapore)",
        "ap-southeast-2": "Asia Pacific (Sydney)",
        "ap-southeast-3": "Asia Pacific (Jakarta)",
        "sa-east-1": "South America (Sao Paulo)",
    }

    # Public JSON endpoints for Bedrock pricing (keyed by hash).
    # Different providers use different datasets:
    #   - "bedrockfoundationmodels" for Anthropic Claude models
    #   - "bedrock" for all other providers (Amazon, Meta, Mistral, etc.)
    _PRICING_JSON_URLS = {
        "bedrockfoundationmodels": (
            "https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps"
            "/bedrockfoundationmodels/USD/current/bedrockfoundationmodels.json"
        ),
        "bedrock": (
            "https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps"
            "/bedrock/USD/current/bedrock.json"
        ),
    }

    async def _scrape_aws_pricing_page(self) -> List[Dict]:
        """
        Extract model pricing from the AWS Bedrock pricing page.

        No browser needed.  The approach combines two public data sources:

        1. **Static HTML** from ``https://aws.amazon.com/bedrock/pricing/``
           Each provider section contains ``data-pricing-markup`` attributes
           with embedded HTML table templates.  Each ``<td>`` cell referencing
           a price uses the pattern ``{priceOf!path!HASH[!*!1000][!opt]}``.

        2. **JSON pricing endpoints** at ``b0.p.awsstatic.com``:
           - ``bedrockfoundationmodels.json`` — Anthropic Claude models.
             Values are per-1M-token prices (e.g. ``3.0``).
           - ``bedrock.json`` — all other providers.
             Values are per-1000-token prices; the markup ref includes a
             ``!*!1000`` multiplier to convert to per-1M-token.

        Only On-Demand text-inference sections are processed (headers must
        contain "input token" and "output token").  Reserved Tier, training,
        image generation, and embedding sections are skipped.

        Cross-region sections are identified by heading:
          - "Global Cross-region" → ``global.`` prefix
          - "Geo" / "In-region"  → geo prefix (e.g. ``us.``)
          - No heading            → base model ID (standard on-demand)

        Returns:
            List of pricing dictionaries for all mapped models found.
        """
        from app.services.bedrock import BedrockClient

        settings = get_settings()
        target_region = settings.AWS_REGION
        geo_prefix = BedrockClient.get_geo_prefix(target_region)

        region_display = self._REGION_DISPLAY_NAMES.get(target_region)
        if not region_display:
            logger.warning(
                f"No display name mapping for region {target_region}, "
                f"cannot look up pricing JSON"
            )
            return []

        # Fetch HTML + both pricing JSON endpoints concurrently
        async with httpx.AsyncClient(timeout=30.0) as client:
            html_resp, fm_resp, bk_resp = await asyncio.gather(
                client.get("https://aws.amazon.com/bedrock/pricing/"),
                client.get(self._PRICING_JSON_URLS["bedrockfoundationmodels"]),
                client.get(self._PRICING_JSON_URLS["bedrock"]),
            )
            html_resp.raise_for_status()
            fm_resp.raise_for_status()
            bk_resp.raise_for_status()

        html = html_resp.text

        # Build per-dataset hash→price lookups for the target region
        price_tables: Dict[str, dict] = {}
        for label, resp in [("bedrockfoundationmodels", fm_resp), ("bedrock", bk_resp)]:
            region_data = resp.json().get("regions", {}).get(region_display, {})
            price_tables[label] = region_data
            logger.info(
                f"Loaded {len(region_data)} price entries for '{region_display}' "
                f"from {label}.json"
            )

        # Decode all data-pricing-markup sections
        raw_markups = re.findall(r'data-pricing-markup="([^"]*)"', html)
        decoded_markups = []
        for m in raw_markups:
            decoded_markups.append(
                m.replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&amp;", "&")
                .replace("&quot;", '"')
            )

        # Filter: only On-Demand text-inference sections
        th_pattern = re.compile(r"<th[^>]*>(?:<[^>]*>)*([^<]*)")
        token_markups = []
        for markup in decoded_markups:
            ths = " ".join(t.strip().lower() for t in th_pattern.findall(markup))
            if "input token" in ths and "output token" in ths:
                if (
                    "per hour" not in ths
                    and "commitment" not in ths
                    and "train" not in ths
                ):
                    token_markups.append(markup)

        logger.info(
            f"Found {len(token_markups)} On-Demand text-inference markup sections "
            f"(out of {len(decoded_markups)} total)"
        )

        # Pattern: <td>ModelName</td><td>{priceOf!...}</td><td>{priceOf!...}</td>
        row_pattern = re.compile(
            r"<tr>\s*<td>([^<{]+?)</td>"
            r"\s*<td>\{priceOf!([^}]+)\}</td>"
            r"\s*<td>\{priceOf!([^}]+)\}</td>"
        )

        # Collect results, dedup by model_id (first occurrence wins)
        seen_model_ids: Set[str] = set()
        pricing_data: List[Dict] = []
        unmapped_names: Set[str] = set()

        for markup in token_markups:
            # Determine prefix from heading
            heading = markup[:200].lower()
            if "global cross-region" in heading:
                prefix = "global."
            elif "geo" in heading or "in-region" in heading:
                prefix = f"{geo_prefix}."
            else:
                prefix = ""

            for match in row_pattern.finditer(markup):
                model_name = match.group(1).strip()
                input_ref = match.group(2)
                output_ref = match.group(3)

                # Skip non-model rows and variants
                if model_name == "N/A" or "Long Context" in model_name:
                    continue
                if "(Preview)" in model_name or "latency optimized" in model_name:
                    continue

                # Parse token refs → (dataset, hash, multiplier)
                in_ds, in_hash, in_mult = self._parse_token_ref(input_ref)
                out_ds, out_hash, out_mult = self._parse_token_ref(output_ref)

                in_entry = price_tables.get(in_ds, {}).get(in_hash)
                out_entry = price_tables.get(out_ds, {}).get(out_hash)

                if not in_entry or not out_entry:
                    continue

                base_model_id = self._map_model_name_to_id(model_name)
                if not base_model_id:
                    unmapped_names.add(model_name)
                    continue

                model_id = f"{prefix}{base_model_id}"
                if model_id in seen_model_ids:
                    continue
                seen_model_ids.add(model_id)

                input_per_1m = Decimal(in_entry["price"]) * in_mult
                output_per_1m = Decimal(out_entry["price"]) * out_mult

                pricing_data.append(
                    {
                        "model_id": model_id,
                        "region": target_region,
                        "input_price_per_token": input_per_1m / 1_000_000,
                        "output_price_per_token": output_per_1m / 1_000_000,
                    }
                )

        if unmapped_names:
            logger.warning(
                f"Unmatched model names from AWS scraper (no mapping): "
                f"{sorted(unmapped_names)}"
            )

        global_count = sum(
            1 for d in pricing_data if d["model_id"].startswith("global.")
        )
        geo_count = sum(
            1 for d in pricing_data if d["model_id"].startswith(f"{geo_prefix}.")
        )
        standard_count = len(pricing_data) - global_count - geo_count
        logger.info(
            f"Extracted {len(pricing_data)} pricing records from static HTML+JSON "
            f"(standard: {standard_count}, global: {global_count}, geo: {geo_count}) "
            f"for region {target_region}"
        )
        return pricing_data

    @staticmethod
    def _parse_token_ref(token_ref: str) -> Tuple[str, str, int]:
        """
        Parse a ``{priceOf!...}`` token reference into its components.

        Token refs come in two flavours:

        1. ``bedrockfoundationmodels/bedrockfoundationmodels!HASH[!opt]``
           JSON values are already per-1M-token → multiplier = 1

        2. ``bedrock/bedrock!HASH[!*!1000][!opt]``
           JSON values are per-1000-token → multiplier = 1000

        Returns:
            Tuple of (dataset_key, hash_key, multiplier).
            ``dataset_key`` is ``"bedrockfoundationmodels"`` or ``"bedrock"``.
        """
        parts = token_ref.split("!")
        # parts[0] = "bedrock/bedrock" or "bedrockfoundationmodels/bedrockfoundationmodels"
        # parts[1] = HASH
        # parts[2..] = optional modifiers ("*", "1000", "opt")
        dataset = parts[0].split("/")[0] if "/" in parts[0] else parts[0]
        hash_key = parts[1] if len(parts) >= 2 else token_ref
        multiplier = 1000 if "*" in parts[2:] and "1000" in parts[2:] else 1
        return dataset, hash_key, multiplier

    async def _save_pricing_data(self, pricing_data: List[Dict], source: str) -> int:
        """
        Save pricing data to database.

        Args:
            pricing_data: List of pricing dictionaries
            source: Source of the data ('api' or 'scraper')

        Returns:
            Number of records updated
        """
        updated_count = 0
        now = datetime.utcnow()

        for data in pricing_data:
            try:
                # Check if record exists
                stmt = select(ModelPricing).where(
                    ModelPricing.model_id == data["model_id"],
                    ModelPricing.region == data["region"],
                )
                result = await self.db.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    # Update existing record
                    existing.input_price_per_token = data["input_price_per_token"]
                    existing.output_price_per_token = data["output_price_per_token"]
                    existing.source = source
                    existing.last_updated = now
                else:
                    # Create new record
                    new_pricing = ModelPricing(
                        model_id=data["model_id"],
                        region=data["region"],
                        input_price_per_token=data["input_price_per_token"],
                        output_price_per_token=data["output_price_per_token"],
                        currency="USD",
                        source=source,
                        last_updated=now,
                        created_at=now,
                    )
                    self.db.add(new_pricing)

                updated_count += 1
            except Exception as e:
                logger.error(f"Failed to save pricing for {data.get('model_id')}: {e}")

        await self.db.commit()
        return updated_count

    def _map_model_name_to_id(self, model_name: str) -> Optional[str]:
        """
        Map AWS model name to Bedrock model ID.

        Args:
            model_name: Model name from AWS API (e.g., "Claude 3 Haiku")

        Returns:
            Bedrock model ID or None if not recognized
        """
        model_mapping = {
            # ── Anthropic Claude ──────────────────────────────────
            # Claude 4.x
            "Claude Opus 4.6": "anthropic.claude-opus-4-6-v1",
            "Claude Sonnet 4.6": "anthropic.claude-sonnet-4-6",
            "Claude Haiku 4.5": "anthropic.claude-haiku-4-5-20251001-v1:0",
            "Claude Sonnet 4.5": "anthropic.claude-sonnet-4-5-20250929-v1:0",
            "Claude Opus 4.5": "anthropic.claude-opus-4-5-20251101-v1:0",
            "Claude Opus 4.1": "anthropic.claude-opus-4-1-20250805-v1:0",
            "Claude Sonnet 4": "anthropic.claude-sonnet-4-20250514-v1:0",
            "Claude Opus 4": "anthropic.claude-opus-4-20250514-v1:0",
            # Claude 3.x
            "Claude 3.7 Sonnet": "anthropic.claude-3-7-sonnet-20250219-v1:0",
            "Claude 3.5 Haiku": "anthropic.claude-3-5-haiku-20241022-v1:0",
            "Claude 3.5 Sonnet": "anthropic.claude-3-5-sonnet-20241022-v2:0",
            "Claude 3.5 Sonnet v1": "anthropic.claude-3-5-sonnet-20240620-v1:0",
            "Claude 3.5 Sonnet v2": "anthropic.claude-3-5-sonnet-20241022-v2:0",
            # Claude 3
            "Claude 3 Haiku": "anthropic.claude-3-haiku-20240307-v1:0",
            "Claude 3 Sonnet": "anthropic.claude-3-sonnet-20240229-v1:0",
            "Claude 3 Opus": "anthropic.claude-3-opus-20240229-v1:0",
            # Claude 2 (legacy)
            "Claude 2.1": "anthropic.claude-v2:1",
            "Claude 2.0": "anthropic.claude-v2",
            "Claude Instant": "anthropic.claude-instant-v1",
            # ── AI21 Labs ─────────────────────────────────────────
            "Jamba 1.5 Large": "ai21.jamba-1-5-large-v1:0",
            "Jamba 1.5 Mini": "ai21.jamba-1-5-mini-v1:0",
            "Jamba-Instruct": "ai21.jamba-instruct-v1:0",
            "Jurassic-2 Mid": "ai21.j2-mid-v1",
            "Jurassic-2 Ultra": "ai21.j2-ultra-v1",
            # ── Amazon Nova ───────────────────────────────────────
            # Names as they appear on the pricing page (with "Amazon" prefix)
            "Amazon Nova 2 Lite": "amazon.nova-2-lite-v1:0",
            "Amazon Nova 2.0 Lite": "amazon.nova-2-lite-v1:0",
            "Amazon Nova Micro": "amazon.nova-micro-v1:0",
            "Amazon Nova Lite": "amazon.nova-lite-v1:0",
            "Amazon Nova Pro": "amazon.nova-pro-v1:0",
            "Amazon Nova Premier": "amazon.nova-premier-v1:0",
            # Names as they appear in the AWS Price List API (without "Amazon")
            "Nova Pro": "amazon.nova-pro-v1:0",
            "Nova Lite": "amazon.nova-lite-v1:0",
            "Nova Micro": "amazon.nova-micro-v1:0",
            "Nova Premier": "amazon.nova-premier-v1:0",
            "Nova Sonic 2.0": "amazon.nova-2-sonic-v1:0",
            "Nova 2.0 Lite": "amazon.nova-2-lite-v1:0",
            "Nova 2.0 Pro": "amazon.nova-2-pro-v1:0",
            "Nova 2.0 Omni": "amazon.nova-2-omni-v1:0",
            "Nova Pro Latency Optimized": "amazon.nova-pro-v1:0",
            # ── Amazon Titan ──────────────────────────────────────
            "Amazon Titan Text Premier": "amazon.titan-text-premier-v1:0",
            "Amazon Titan Text Lite": "amazon.titan-text-lite-v1",
            "Amazon Titan Text Express": "amazon.titan-text-express-v1",
            # ── Cohere ────────────────────────────────────────────
            "Command R+": "cohere.command-r-plus-v1:0",
            "Command R": "cohere.command-r-v1:0",
            "Embed 3 English": "cohere.embed-english-v3",
            "Embed 3 Multilingual": "cohere.embed-multilingual-v3",
            # ── DeepSeek ──────────────────────────────────────────
            "DeepSeek-R1": "deepseek.r1-v1:0",
            "DeepSeek-V3.1": "deepseek.v3-v1:0",
            "DeepSeek V3.1": "deepseek.v3-v1:0",
            "DeepSeek v3.1": "deepseek.v3-v1:0",
            "DeepSeek v3.2": "deepseek.v3.2",
            "R1": "deepseek.r1-v1:0",
            # ── Meta Llama ────────────────────────────────────────
            # Pricing page uses "Instruct (XB)" format
            "Llama 4 Maverick 17B": "meta.llama4-maverick-17b-instruct-v1:0",
            "Llama 4 Scout 17B": "meta.llama4-scout-17b-instruct-v1:0",
            "Llama 3.3 Instruct (70B)": "meta.llama3-3-70b-instruct-v1:0",
            "Llama 3.3 70B": "meta.llama3-3-70b-instruct-v1:0",
            "Llama 3.2 Instruct (90B)": "meta.llama3-2-90b-instruct-v1:0",
            "Llama 3.2 Instruct (11B)": "meta.llama3-2-11b-instruct-v1:0",
            "Llama 3.2 Instruct (3B)": "meta.llama3-2-3b-instruct-v1:0",
            "Llama 3.2 Instruct (1B)": "meta.llama3-2-1b-instruct-v1:0",
            "Llama 3.2 90B": "meta.llama3-2-90b-instruct-v1:0",
            "Llama 3.2 11B": "meta.llama3-2-11b-instruct-v1:0",
            "Llama 3.2 3B": "meta.llama3-2-3b-instruct-v1:0",
            "Llama 3.2 1B": "meta.llama3-2-1b-instruct-v1:0",
            "Llama 3.1 Instruct (405B)": "meta.llama3-1-405b-instruct-v1:0",
            "Llama 3.1 Instruct (70B)": "meta.llama3-1-70b-instruct-v1:0",
            "Llama 3.1 Instruct (8B)": "meta.llama3-1-8b-instruct-v1:0",
            "Llama 3.1 405B": "meta.llama3-1-405b-instruct-v1:0",
            "Llama 3.1 70B": "meta.llama3-1-70b-instruct-v1:0",
            "Llama 3.1 70B Latency Optimized": "meta.llama3-1-70b-instruct-v1:0",
            "Llama 3.1 8B": "meta.llama3-1-8b-instruct-v1:0",
            "Llama 3 Instruct (70B)": "meta.llama3-70b-instruct-v1:0",
            "Llama 3 Instruct (8B)": "meta.llama3-8b-instruct-v1:0",
            "Llama 3 70B": "meta.llama3-70b-instruct-v1:0",
            "Llama 3 8B": "meta.llama3-8b-instruct-v1:0",
            # ── Mistral AI ────────────────────────────────────────
            "Mistral 7B": "mistral.mistral-7b-instruct-v0:2",
            "Mixtral 8x7B": "mistral.mixtral-8x7b-instruct-v0:1",
            "Mixtral 8*7B": "mistral.mixtral-8x7b-instruct-v0:1",
            "Mistral Small (24.02)": "mistral.mistral-small-2402-v1:0",
            "Mistral Small": "mistral.mistral-small-2402-v1:0",
            "Mistral Large (24.02)": "mistral.mistral-large-2402-v1:0",
            "Mistral Large": "mistral.mistral-large-2402-v1:0",
            "Mistral Large 2 (24.07)": "mistral.mistral-large-2407-v1:0",
            "Mistral Large 2407": "mistral.mistral-large-2407-v1:0",
            "Mistral Large 3": "mistral.mistral-large-3-675b-instruct",
            "Pixtral Large (25.02)": "mistral.pixtral-large-2502-v1:0",
            "Pixtral Large 25.02": "mistral.pixtral-large-2502-v1:0",
            "Magistral Small 1.2": "mistral.magistral-small-2509",
            "Ministral 14B 3.0": "mistral.ministral-3-14b-instruct",
            "Ministral 8B 3.0": "mistral.ministral-3-8b-instruct",
            "Ministral 3B 3.0": "mistral.ministral-3-3b-instruct",
            "Voxtral Mini 1.0": "mistral.voxtral-mini-3b-2507",
            "Voxtral Small 1.0": "mistral.voxtral-small-24b-2507",
            # ── Google ──────────────────────────────────────────────
            "Gemma 3 4B": "google.gemma-3-4b-it",
            "Gemma 3 12B": "google.gemma-3-12b-it",
            "Gemma 3 27B": "google.gemma-3-27b-pt",
            # ── MiniMax AI ─────────────────────────────────────────
            "Minimax M2": "minimax.minimax-m2",
            # ── Moonshot AI ────────────────────────────────────────
            "Kimi K2 Thinking": "moonshot.kimi-k2-thinking",
            # ── NVIDIA ─────────────────────────────────────────────
            "NVIDIA Nemotron Nano 2": "nvidia.nemotron-nano-12b-v2",
            "NVIDIA Nemotron Nano 2 VL": "nvidia.nemotron-nano-9b-v2",
            "Nemotron Nano 3 30B": "nvidia.nemotron-nano-3-30b",
            # ── OpenAI (gpt-oss on Bedrock) ───────────────────────
            "gpt-oss-20b": "openai.gpt-oss-20b-1:0",
            "gpt-oss-120b": "openai.gpt-oss-120b-1:0",
            "GPT OSS Safeguard 20B": "openai.gpt-oss-20b-1:0",
            "GPT OSS Safeguard 120B": "openai.gpt-oss-120b-1:0",
            # ── Qwen (Alibaba Cloud) ─────────────────────────────
            "Qwen3 32B": "qwen.qwen3-32b-v1:0",
            "Qwen3 235B A22B 2507": "qwen.qwen3-235b-a22b-2507-v1:0",
            "Qwen3 Coder 30B A3B": "qwen.qwen3-coder-30b-a3b-v1:0",
            "Qwen3 Coder 480B A35B": "qwen.qwen3-coder-480b-a35b-v1:0",
            "Qwen3 VL 235B A22B": "qwen.qwen3-vl-235b-a22b-v1:0",
            "Qwen3 Next 80B A3B": "qwen.qwen3-next-80b-a3b-v1:0",
            # ── Writer ─────────────────────────────────────────────
            "Palmyra X4": "writer.palmyra-x4-v1:0",
            "Palmyra X5": "writer.palmyra-x5-v1:0",
            # ── Z AI ──────────────────────────────────────────────
            "GLM 4.7": "zai.glm-4.7",
            "GLM 4.7 Flash": "zai.glm-4.7-flash",
            "GLM-4.7": "zai.glm-4.7",
            "GLM-4.7 Flash": "zai.glm-4.7-flash",
        }

        return model_mapping.get(model_name)

    async def get_pricing(
        self, model_id: str, region: str = None
    ) -> Optional[Tuple[Decimal, Decimal]]:
        """
        Get pricing for a model from database.

        Lookup order:
        1. Exact match on (model_id, region)
        2. If model_id has a cross-region prefix (us., eu., apac., etc.),
           fall back to base model (without prefix)

        Args:
            model_id: Model identifier (e.g. "meta.llama3-3-70b-instruct-v1:0",
                      "us.amazon.nova-pro-v1:0")
            region: AWS region (defaults to configured AWS_REGION)

        Returns:
            Tuple of (input_price_per_token, output_price_per_token) or None
        """
        from app.services.bedrock import BedrockClient

        if region is None:
            region = get_settings().AWS_REGION

        # Try exact match first
        stmt = select(ModelPricing).where(
            ModelPricing.model_id == model_id, ModelPricing.region == region
        )
        result = await self.db.execute(stmt)
        pricing = result.scalar_one_or_none()

        if pricing:
            return (pricing.input_price_per_token, pricing.output_price_per_token)

        # If model has a cross-region prefix, try fallbacks:
        # 1. Strip prefix → try base model ID (e.g. "anthropic.claude-opus-4-6-v1")
        # 2. Try with region's geo prefix (e.g. "global.X" → "us.X" in us-west-2)
        for prefix in BedrockClient.INFERENCE_PROFILE_PREFIXES:
            if model_id.startswith(prefix):
                base_model_id = model_id[len(prefix) :]

                # Fallback 1: try base model without any prefix
                stmt = select(ModelPricing).where(
                    ModelPricing.model_id == base_model_id,
                    ModelPricing.region == region,
                )
                result = await self.db.execute(stmt)
                pricing = result.scalar_one_or_none()

                if pricing:
                    logger.info(
                        f"Cross-region pricing not found for {model_id}, "
                        f"using standard pricing for {base_model_id}"
                    )
                    return (
                        pricing.input_price_per_token,
                        pricing.output_price_per_token,
                    )

                # Fallback 2: try with the region's geo prefix
                # (e.g. "global.anthropic.X" → "us.anthropic.X" in us-west-2)
                geo_prefix = BedrockClient.get_geo_prefix(region)
                geo_model_id = f"{geo_prefix}.{base_model_id}"
                if geo_model_id != model_id:
                    stmt = select(ModelPricing).where(
                        ModelPricing.model_id == geo_model_id,
                        ModelPricing.region == region,
                    )
                    result = await self.db.execute(stmt)
                    pricing = result.scalar_one_or_none()

                    if pricing:
                        logger.info(
                            f"Cross-region pricing not found for {model_id}, "
                            f"using geo-specific pricing for {geo_model_id}"
                        )
                        return (
                            pricing.input_price_per_token,
                            pricing.output_price_per_token,
                        )

                break

        return None

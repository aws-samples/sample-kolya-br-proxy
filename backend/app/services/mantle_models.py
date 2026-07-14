"""
OpenAI-on-Bedrock (mantle) model registry.

Mantle-served OpenAI models (GPT-5.x) go through the OpenAI Responses API
(``https://bedrock-mantle.{region}.api.aws/openai/v1``), **not** through the
standard boto3 ``converse`` / ``invoke_model`` paths.  They do not appear in
``list-foundation-models`` / ``list-inference-profiles`` or the Price List
API, so they need their own registry:

  * routing — each model is only available in specific regions, and requests
    must be sent to a region where the model lives (independent of the local
    ``AWS_REGION``).
  * model list — the admin "available models" endpoint injects these entries
    since the profile cache cannot discover them.
  * pricing — the price-page scraper maps display names back to these IDs.

This module is the single source of truth shared by chat routing, pricing, and
the admin model list.

The registry has two layers:

  * a static seed table (below) — always available, hand-maintained as a
    fallback;
  * a discovered layer populated by ``refresh_mantle_registry()``, which calls
    the mantle ``ListModels`` API (``GET /v1/models``, IAM action
    ``bedrock-mantle:ListModels``) per candidate region at startup and before
    every pricing update.  Discovered entries override the static seed per
    model; static models never disappear, so a failed discovery can only miss
    NEW models, never break existing routing.
"""

import asyncio
import logging
import re
from typing import Dict, List, Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Static seed: model ID → regions where it can be invoked (first entry is the
# preferred one).  Source: AWS Bedrock model cards ("Models at a glance" →
# OpenAI).  Kept as a fallback for when ListModels discovery is disabled or
# fails — discovered data (see refresh_mantle_registry) takes precedence.
MANTLE_MODEL_REGIONS: Dict[str, List[str]] = {
    "openai.gpt-5.6-sol": ["us-east-1", "us-east-2"],
    "openai.gpt-5.6-terra": ["us-east-1", "us-east-2", "us-west-2"],
    "openai.gpt-5.6-luna": ["us-east-1", "us-east-2", "us-west-2"],
    "openai.gpt-5.5": ["us-east-2"],
    "openai.gpt-5.4": ["us-east-2", "us-west-2"],
}

# Effective registry served to all callers.  Starts as the static seed;
# refresh_mantle_registry() replaces it with {**static, **discovered} so the
# merge cost is paid once per refresh, not on every request.
_model_regions: Dict[str, List[str]] = MANTLE_MODEL_REGIONS

# Escape hatch for models whose AWS display name is not a mechanical transform
# of the model ID (see mantle_display_name).  Empty today; add an entry here
# instead of patching the derivation heuristics when AWS breaks the convention.
MANTLE_DISPLAY_NAME_OVERRIDES: Dict[str, str] = {}

# mantle OpenAI-compatible endpoint base URL (per region).
MANTLE_BASE_URL = "https://bedrock-mantle.{region}.api.aws/openai/v1"

# mantle ListModels endpoint (per region).  NOTE: lives at /v1/models on the
# mantle host, NOT under the /openai/v1 prefix used for inference.
MANTLE_LIST_MODELS_URL = "https://bedrock-mantle.{region}.api.aws/v1/models"


def get_mantle_model_regions() -> Dict[str, List[str]]:
    """Effective registry: static seed, overridden per model by discovery."""
    return _model_regions


def mantle_display_name(model_id: str) -> str:
    """Derive the human/pricing-page display name from a mantle model ID.

    "openai.gpt-5.6-sol" → "GPT-5.6 Sol";  "openai.gpt-5.5" → "GPT-5.5".
    Splits the ID suffix before letter-led tokens only, so version dots and
    digits stay attached.  Kept consistent with the normalization in
    mantle_pricing_name_to_id so derived names round-trip.  For models whose
    AWS name breaks this convention, add a MANTLE_DISPLAY_NAME_OVERRIDES entry.
    """
    override = MANTLE_DISPLAY_NAME_OVERRIDES.get(model_id)
    if override:
        return override
    first, *rest = re.split(r"-(?=[a-z])", model_id.split(".", 1)[-1])
    return " ".join([first.upper(), *map(str.capitalize, rest)])


def mantle_pricing_name_to_id(display_name: str) -> Optional[str]:
    """Map an AWS pricing-page display name to a registry model ID.

    Normalizes "GPT-5.6 Sol" → "gpt-5.6-sol" and matches it against the
    ``openai.``-suffix of every registry entry, so newly discovered models
    match their pricing rows without a hand-maintained name table.
    """
    normalized = re.sub(r"[\s\-]+", "-", display_name.strip().lower())
    for model_id in _model_regions:
        if model_id.split(".", 1)[-1] == normalized:
            return model_id
    return None


async def _probe_region_models(client: httpx.AsyncClient, region: str) -> List[str]:
    """List mantle model IDs available in one region ([] on any failure)."""
    # Lazy import: mantle_signing pulls in BedrockClient at call time.
    from app.services.mantle_signing import signed_headers

    url = MANTLE_LIST_MODELS_URL.format(region=region)
    try:
        headers = await signed_headers("GET", url, b"", region)
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            logger.warning(
                f"mantle ListModels failed in {region}: "
                f"status={resp.status_code}, body={resp.text[:200]}"
            )
            return []
        entries = (resp.json() or {}).get("data") or []
    except Exception as e:
        logger.warning(f"mantle ListModels probe failed in {region}: {e}")
        return []
    return [
        entry["id"] for entry in entries if isinstance(entry, dict) and entry.get("id")
    ]


async def discover_mantle_models() -> Dict[str, List[str]]:
    """Discover mantle-served models via the ListModels API.

    Probes ``GET /v1/models`` (IAM action ``bedrock-mantle:ListModels``) in
    every candidate region from ``MANTLE_DISCOVERY_REGIONS`` concurrently and
    aggregates a model → available-regions map.  Region order follows the
    configured candidate order, so the first entry is a stable preferred
    region.

    Only ``openai.*`` model IDs are kept, and ``openai.gpt-oss-*`` is excluded
    — the open-weight models run through the standard Bedrock converse path,
    not the mantle Responses API (see is_openai_mantle_model).

    A region probe failing (permission, throttle, endpoint missing) skips that
    region with a warning; an empty overall result means callers should keep
    the previous registry.
    """
    regions = get_settings().get_mantle_discovery_regions()
    if not regions:
        return {}

    async with httpx.AsyncClient(timeout=30.0) as client:
        results = await asyncio.gather(
            *(_probe_region_models(client, region) for region in regions)
        )

    model_regions: Dict[str, List[str]] = {}
    for region, model_ids in zip(regions, results):
        for model_id in model_ids:
            if not model_id.startswith("openai.") or "gpt-oss" in model_id:
                continue
            model_regions.setdefault(model_id, []).append(region)

    if model_regions:
        logger.info(
            f"mantle ListModels discovered {len(model_regions)} models: "
            f"{sorted(model_regions)}"
        )
    return model_regions


async def refresh_mantle_registry() -> Dict[str, List[str]]:
    """Refresh the effective registry from ListModels; returns the new mapping.

    New models (absent from the current registry) are logged prominently so
    operators notice launches — but note the model is NOT usable for billing
    until the pricing update also finds its price row (calculate_cost raises
    for unpriced models; update_all_pricing calls this before matching rows).

    Never raises: discovery is best-effort, and on empty discovery (probes
    failed / no permission / discovery disabled) the previous registry is kept.
    """
    global _model_regions

    if not get_settings().get_mantle_discovery_regions():
        logger.info("mantle model discovery disabled; using static registry")
        return _model_regions

    try:
        discovered = await discover_mantle_models()
    except Exception as e:
        logger.warning(f"mantle model discovery failed: {e}")
        return _model_regions
    if not discovered:
        logger.warning("mantle model discovery returned nothing; keeping registry")
        return _model_regions

    new_models = set(discovered) - set(_model_regions)
    if new_models:
        logger.warning(
            f"mantle discovery found NEW models not in the static registry: "
            f"{sorted(new_models)} — they will be routed automatically; "
            f"verify pricing rows exist after the next pricing update"
        )
    _model_regions = {**MANTLE_MODEL_REGIONS, **discovered}
    return _model_regions


def is_openai_mantle_model(model_id: str) -> bool:
    """Return True if *model_id* is served via the mantle Responses API.

    Exact-match against the registry on purpose — a prefix match on ``openai.``
    would wrongly capture the open-weight ``openai.gpt-oss-*`` models, which run
    through the standard Bedrock converse path.
    """
    return model_id in _model_regions


def resolve_mantle_region(model_id: str) -> str:
    """Pick the region to route *model_id* to.

    Prefer the local ``AWS_REGION`` when the model is available there (saves
    cross-region latency); otherwise use the model's preferred region.  Raises
    KeyError for non-mantle models — callers guard with is_openai_mantle_model.
    """
    regions = _model_regions[model_id]
    local = get_settings().AWS_REGION
    return local if local in regions else regions[0]


def get_mantle_models() -> List[Dict]:
    """Return UI-compatible model entries for the admin "available models" list.

    Shaped identically to the Bedrock / Gemini entries produced in
    ``list_aws_available_models`` so the frontend renders them uniformly.
    """
    models: List[Dict] = []
    for model_id in _model_regions:
        models.append(
            {
                "model_id": model_id,
                "model_name": mantle_display_name(model_id),
                "friendly_name": mantle_display_name(model_id),
                "provider": "openai-mantle",
                "is_cross_region": False,
                "cross_region_type": None,
                "streaming_supported": True,
                "is_fallback": False,
            }
        )
    return models

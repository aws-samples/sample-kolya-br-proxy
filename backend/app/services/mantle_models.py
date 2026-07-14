"""
OpenAI-on-Bedrock (mantle) model registry.

GPT-5.6 (Sol/Terra/Luna) and GPT-5.5 / GPT-5.4 are served by AWS's "mantle"
inference engine through the
OpenAI Responses API (``https://bedrock-mantle.{region}.api.aws/openai/v1``),
**not** through the standard boto3 ``converse`` / ``invoke_model`` paths.  They
do not appear in ``list-foundation-models`` / ``list-inference-profiles`` or the
Price List API, so they need their own static registry:

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
    ``bedrock-mantle:ListModels``) per candidate region at startup and on a
    daily schedule.  Discovered entries override the static seed per model;
    static models never disappear, so a failed discovery can only miss NEW
    models, never break existing routing.
"""

import logging
import re
from typing import Dict, List, Optional

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

# Discovered layer — set by refresh_mantle_registry(), None until first run.
_discovered_model_regions: Optional[Dict[str, List[str]]] = None

# mantle OpenAI-compatible endpoint base URL (per region).
MANTLE_BASE_URL = "https://bedrock-mantle.{region}.api.aws/openai/v1"

# mantle ListModels endpoint (per region).  NOTE: lives at /v1/models on the
# mantle host, NOT under the /openai/v1 prefix used for inference.
MANTLE_LIST_MODELS_URL = "https://bedrock-mantle.{region}.api.aws/v1/models"


def get_mantle_model_regions() -> Dict[str, List[str]]:
    """Effective registry: discovered entries override the static seed.

    Static models missing from the discovered layer are preserved so a partial
    discovery (e.g. one region probe failing) never removes known models.
    """
    if _discovered_model_regions:
        merged = dict(MANTLE_MODEL_REGIONS)
        merged.update(_discovered_model_regions)
        return merged
    return MANTLE_MODEL_REGIONS


def set_discovered_mantle_models(regions: Optional[Dict[str, List[str]]]) -> None:
    """Replace the discovered layer (called by refresh_mantle_registry)."""
    global _discovered_model_regions
    _discovered_model_regions = regions


def mantle_display_name(model_id: str) -> str:
    """Derive the human/pricing-page display name from a mantle model ID.

    "openai.gpt-5.6-sol" → "GPT-5.6 Sol";  "openai.gpt-5.5" → "GPT-5.5".
    Digit-led tokens attach to the previous token with a hyphen; the rest are
    capitalized words.  This is the inverse of the normalization used by
    mantle_pricing_name_to_id, so the two stay consistent for new models.
    """
    tokens = model_id.split(".", 1)[-1].split("-")
    parts: List[str] = []
    for token in tokens:
        if parts and token[:1].isdigit():
            parts[-1] += f"-{token}"
        elif token.lower().startswith("gpt"):
            parts.append(token.upper())
        else:
            parts.append(token.capitalize())
    return " ".join(parts)


async def discover_mantle_models() -> Dict[str, List[str]]:
    """Discover mantle-served models via the ListModels API.

    Probes ``GET /v1/models`` (IAM action ``bedrock-mantle:ListModels``) in
    every candidate region from ``MANTLE_DISCOVERY_REGIONS`` and aggregates a
    model → available-regions map.  Region order follows the configured
    candidate order, so the first entry is a stable preferred region.

    Only ``openai.*`` model IDs are kept, and ``openai.gpt-oss-*`` is excluded
    — the open-weight models run through the standard Bedrock converse path,
    not the mantle Responses API (see is_openai_mantle_model).

    A region probe failing (permission, throttle, endpoint missing) skips that
    region with a warning; an empty overall result means callers should keep
    the previous registry.
    """
    import httpx

    # Lazy import: mantle_client imports from this module at module level.
    from app.services.mantle_client import _signed_headers

    model_regions: Dict[str, List[str]] = {}
    for region in get_settings().get_mantle_discovery_regions():
        url = MANTLE_LIST_MODELS_URL.format(region=region)
        try:
            headers = await _signed_headers("GET", url, b"", region)
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                logger.warning(
                    f"mantle ListModels failed in {region}: "
                    f"status={resp.status_code}, body={resp.text[:200]}"
                )
                continue
            entries = (resp.json() or {}).get("data") or []
        except Exception as e:
            logger.warning(f"mantle ListModels probe failed in {region}: {e}")
            continue

        for entry in entries:
            model_id = entry.get("id") if isinstance(entry, dict) else None
            if not model_id or not model_id.startswith("openai."):
                continue
            if "gpt-oss" in model_id:
                continue
            model_regions.setdefault(model_id, []).append(region)

    if model_regions:
        logger.info(
            f"mantle ListModels discovered {len(model_regions)} models: "
            f"{sorted(model_regions)}"
        )
    return model_regions


async def refresh_mantle_registry() -> Dict[str, List[str]]:
    """Refresh the discovered layer from ListModels; returns the new mapping.

    New models (absent from both the static seed and the previous discovered
    layer) are logged prominently so operators notice launches — but note the
    model is NOT usable for billing until the pricing update task also finds
    its price row (calculate_cost raises for unpriced models, and the pricing
    task runs right after this in the scheduler).

    On empty discovery (all probes failed / no permission) the previous
    registry is kept untouched.
    """
    previous = set(get_mantle_model_regions())
    discovered = await discover_mantle_models()
    if not discovered:
        logger.warning(
            "mantle model discovery returned nothing "
            "(missing bedrock-mantle:ListModels permission?); "
            "keeping existing registry"
        )
        return get_mantle_model_regions()

    new_models = set(discovered) - previous
    if new_models:
        logger.warning(
            f"mantle discovery found NEW models not in the static registry: "
            f"{sorted(new_models)} — they will be routed automatically; "
            f"verify pricing rows exist after the next pricing update"
        )
    set_discovered_mantle_models(discovered)
    return get_mantle_model_regions()


def mantle_pricing_name_to_id(display_name: str) -> Optional[str]:
    """Map an AWS pricing-page display name to a registry model ID.

    Normalizes "GPT-5.6 Sol" → "gpt-5.6-sol" and matches it against the
    ``openai.``-suffix of every registry entry, so newly discovered models
    match their pricing rows without a hand-maintained name table.
    """
    normalized = re.sub(r"[\s\-]+", "-", display_name.strip().lower())
    for model_id in get_mantle_model_regions():
        if model_id.split(".", 1)[-1] == normalized:
            return model_id
    return None


def is_openai_mantle_model(model_id: str) -> bool:
    """Return True if *model_id* is served via the mantle Responses API.

    Exact-match against the registry on purpose — a prefix match on ``openai.``
    would wrongly capture the open-weight ``openai.gpt-oss-*`` models, which run
    through the standard Bedrock converse path.
    """
    return model_id in get_mantle_model_regions()


def resolve_mantle_region(model_id: str) -> str:
    """Pick the region to route *model_id* to.

    Prefer the local ``AWS_REGION`` when the model is available there (saves
    cross-region latency); otherwise use the model's preferred region.  Raises
    KeyError for non-mantle models — callers guard with is_openai_mantle_model.
    """
    regions = get_mantle_model_regions()[model_id]
    local = get_settings().AWS_REGION
    return local if local in regions else regions[0]


def get_mantle_models() -> List[Dict]:
    """Return UI-compatible model entries for the admin "available models" list.

    Shaped identically to the Bedrock / Gemini entries produced in
    ``list_aws_available_models`` so the frontend renders them uniformly.
    """
    models: List[Dict] = []
    for model_id in get_mantle_model_regions():
        # "openai.gpt-5.6-sol" → "GPT-5.6 Sol"
        friendly_name = mantle_display_name(model_id)
        models.append(
            {
                "model_id": model_id,
                "model_name": friendly_name,
                "friendly_name": friendly_name,
                "provider": "openai-mantle",
                "is_cross_region": False,
                "cross_region_type": None,
                "streaming_supported": True,
                "is_fallback": False,
            }
        )
    return models

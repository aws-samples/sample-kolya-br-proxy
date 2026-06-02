"""
OpenAI-on-Bedrock (mantle) model registry.

GPT-5.5 / GPT-5.4 are served by AWS's "mantle" inference engine through the
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
"""

from typing import Dict, List

from app.core.config import get_settings

# Model ID → regions where it can be invoked (first entry is the preferred one).
# Source: AWS "Get started with OpenAI GPT-5.5 / GPT-5.4 on Amazon Bedrock".
MANTLE_MODEL_REGIONS: Dict[str, List[str]] = {
    "openai.gpt-5.5": ["us-east-2"],
    "openai.gpt-5.4": ["us-east-2", "us-west-2"],
}

# mantle OpenAI-compatible endpoint base URL (per region).
MANTLE_BASE_URL = "https://bedrock-mantle.{region}.api.aws/openai/v1"

# Display name on the AWS Bedrock pricing page → model ID (for the scraper).
MANTLE_PRICING_NAMES: Dict[str, str] = {
    "GPT-5.5": "openai.gpt-5.5",
    "GPT-5.4": "openai.gpt-5.4",
}


def is_openai_mantle_model(model_id: str) -> bool:
    """Return True if *model_id* is served via the mantle Responses API.

    Exact-match against the registry on purpose — a prefix match on ``openai.``
    would wrongly capture the open-weight ``openai.gpt-oss-*`` models, which run
    through the standard Bedrock converse path.
    """
    return model_id in MANTLE_MODEL_REGIONS


def resolve_mantle_region(model_id: str) -> str:
    """Pick the region to route *model_id* to.

    Prefer the local ``AWS_REGION`` when the model is available there (saves
    cross-region latency); otherwise use the model's preferred region.  Raises
    KeyError for non-mantle models — callers guard with is_openai_mantle_model.
    """
    regions = MANTLE_MODEL_REGIONS[model_id]
    local = get_settings().AWS_REGION
    return local if local in regions else regions[0]


def get_mantle_models() -> List[Dict]:
    """Return UI-compatible model entries for the admin "available models" list.

    Shaped identically to the Bedrock / Gemini entries produced in
    ``list_aws_available_models`` so the frontend renders them uniformly.
    """
    models: List[Dict] = []
    for model_id in MANTLE_MODEL_REGIONS:
        # "openai.gpt-5.5" → "GPT-5.5"
        friendly_name = model_id.split(".", 1)[-1].upper()
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

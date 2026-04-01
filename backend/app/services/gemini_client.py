"""
Google Gemini API client service.

Routes requests to the Google Gemini OpenAI-compatible endpoint.
All request fields (including Gemini-specific ones like thinking, grounding)
are passed through as-is, just like Anthropic models are passed through to Bedrock.
"""

import logging
import re
from typing import AsyncGenerator, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Google Gemini API endpoints
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_CHAT_URL = (
    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
)


def is_gemini_model(model: str) -> bool:
    """Return True if model should be routed to Google Gemini API."""
    return model.startswith("gemini-") or model.startswith("models/gemini-")


def _make_friendly_name(model_id: str, display_name: str) -> str:
    """Build a clean friendly name from Google's displayName."""
    # Google often returns names like "Gemini 2.5 Pro" directly
    if display_name:
        return display_name
    # Fallback: convert model_id like "gemini-2.5-pro" → "Gemini 2.5 Pro"
    parts = model_id.replace("gemini-", "").split("-")
    return "Gemini " + " ".join(p.capitalize() for p in parts)


class GeminiClient:
    """Client for Google Gemini API."""

    @classmethod
    async def list_models(cls, api_key: str) -> List[Dict]:
        """
        Fetch available Gemini models from Google API.

        Filters to Gemini 2+ models that support generateContent.
        Returns list in same format as Bedrock models for UI compatibility.
        """
        url = f"{GEMINI_MODELS_URL}?key={api_key}&pageSize=100"
        models = []

        async with httpx.AsyncClient(timeout=30) as client:
            while url:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()

                for model in data.get("models", []):
                    name = model.get("name", "")  # e.g. "models/gemini-2.5-pro"

                    # Only include gemini-{N}+ where N >= 2
                    m = re.match(r"models/gemini-([0-9]+)", name)
                    if not m:
                        continue
                    if int(m.group(1)) < 2:
                        continue

                    # Must support generateContent (text generation)
                    supported_methods = model.get("supportedGenerationMethods", [])
                    if "generateContent" not in supported_methods:
                        continue

                    # Exclude embedding / aqa models
                    model_id = name[len("models/"):]  # strip "models/" prefix
                    if any(kw in model_id for kw in ("embed", "aqa", "retrieval")):
                        continue

                    display_name = model.get("displayName", "")
                    friendly_name = _make_friendly_name(model_id, display_name)

                    models.append(
                        {
                            "model_id": model_id,
                            "model_name": friendly_name,
                            "friendly_name": friendly_name,
                            "provider": "google",
                            "is_cross_region": False,
                            "cross_region_type": None,
                            "streaming_supported": True,
                        }
                    )

                # Handle pagination
                next_page_token = data.get("nextPageToken")
                if next_page_token:
                    url = (
                        f"{GEMINI_MODELS_URL}?key={api_key}"
                        f"&pageSize=100&pageToken={next_page_token}"
                    )
                else:
                    url = None

        # Sort by model_id for stable ordering
        models.sort(key=lambda m: m["model_id"])
        logger.info(f"Fetched {len(models)} Gemini models from Google API")
        return models

    @classmethod
    async def invoke(
        cls,
        payload: dict,
        api_key: str,
    ) -> dict:
        """
        Non-streaming request to Gemini OpenAI-compatible endpoint.

        Returns the raw OpenAI-format response dict.
        """
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(GEMINI_CHAT_URL, headers=headers, json=payload)

        if resp.status_code != 200:
            logger.error(
                f"Gemini API error: status={resp.status_code}, body={resp.text[:500]}"
            )
            raise httpx.HTTPStatusError(
                f"Gemini API returned {resp.status_code}: {resp.text[:200]}",
                request=resp.request,
                response=resp,
            )

        return resp.json()

    @classmethod
    async def invoke_stream(
        cls,
        payload: dict,
        api_key: str,
    ) -> AsyncGenerator[str, None]:
        """
        Streaming request to Gemini OpenAI-compatible endpoint.

        Yields raw SSE text chunks exactly as received from Google.
        The caller is responsible for heartbeat injection.
        """
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST", GEMINI_CHAT_URL, headers=headers, json=payload
            ) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    raise httpx.HTTPStatusError(
                        f"Gemini stream error {resp.status_code}: "
                        f"{error_body[:200].decode(errors='replace')}",
                        request=resp.request,
                        response=resp,
                    )
                async for chunk in resp.aiter_text():
                    if chunk:
                        yield chunk


def extract_cached_tokens(response: dict) -> int:
    """
    Extract cached token count from a Gemini non-streaming response.

    Google returns cached tokens in:
      usage.prompt_tokens_details[].cached_tokens
    or
      usage.prompt_tokens_details.cached_tokens
    """
    usage = response.get("usage", {})
    details = usage.get("prompt_tokens_details")
    if not details:
        return 0

    if isinstance(details, list):
        # List of detail objects
        for item in details:
            if isinstance(item, dict) and "cached_tokens" in item:
                return int(item["cached_tokens"])
    elif isinstance(details, dict):
        return int(details.get("cached_tokens", 0))

    return 0


def extract_cached_tokens_from_chunk(data: dict) -> Optional[int]:
    """
    Extract cached token count from a Gemini streaming chunk's usage field.
    Returns None if no usage data in this chunk.
    """
    usage = data.get("usage")
    if not usage:
        return None
    return extract_cached_tokens({"usage": usage})

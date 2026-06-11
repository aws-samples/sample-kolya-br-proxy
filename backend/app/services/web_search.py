"""
Web search service for handling Anthropic built-in web_search tool.

Supports two backends:
  - tavily: Tavily API (paid, $0.001/request)
  - searxng: Self-hosted SearXNG instance (free)

Each API token selects its provider via token_metadata.web_search_provider.
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import get_settings
from app.schemas.anthropic import AnthropicToolDefinition

logger = logging.getLogger(__name__)

TAVILY_API_URL = "https://api.tavily.com/search"
SEARXNG_BASE_URL = "http://searxng.kbp.svc.cluster.local:8080"

WEB_SEARCH_TOOL_DEFINITION = AnthropicToolDefinition(
    name="web_search",
    description="Search the web for current information. Returns relevant web page titles, URLs, and content snippets.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to look up on the web.",
            }
        },
        "required": ["query"],
    },
)

VALID_PROVIDERS = ("tavily", "searxng")


def get_available_providers() -> List[str]:
    """Return list of providers that are configured."""
    settings = get_settings()
    providers = []
    if settings.TAVILY_API_KEY:
        providers.append("tavily")
    # SearXNG is always available (cluster-internal, fixed address)
    providers.append("searxng")
    return providers


def is_web_search_configured(provider: Optional[str] = None) -> bool:
    """Check if the requested provider (or any provider) is configured."""
    available = get_available_providers()
    if provider:
        return provider in available
    return len(available) > 0


async def execute_web_search(
    query: str, provider: Optional[str] = None, max_results: int = 5
) -> Dict[str, Any]:
    """Execute a web search via the specified provider."""
    if provider == "searxng":
        return await _search_searxng(query, max_results)
    return await _search_tavily(query, max_results)


async def _search_tavily(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Execute a web search via Tavily API."""
    settings = get_settings()
    api_key = settings.TAVILY_API_KEY

    if not api_key:
        return {
            "type": "web_search_result",
            "error": "Tavily is not configured (TAVILY_API_KEY not set)",
        }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                TAVILY_API_URL,
                json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": max_results,
                    "include_answer": True,
                    "search_depth": "basic",
                },
            )
            response.raise_for_status()
            data = response.json()

        results = []
        for r in data.get("results", []):
            results.append(
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                }
            )

        output: Dict[str, Any] = {
            "type": "web_search_result",
            "query": query,
        }
        if data.get("answer"):
            output["answer"] = data["answer"]
        output["results"] = results
        return output

    except httpx.HTTPStatusError as e:
        logger.error(f"Tavily API error: {e.response.status_code} {e.response.text}")
        return {
            "type": "web_search_result",
            "error": f"Search API returned status {e.response.status_code}",
        }
    except Exception as e:
        logger.error(f"Web search (tavily) failed: {e}", exc_info=True)
        return {
            "type": "web_search_result",
            "error": f"Search failed: {str(e)}",
        }


async def _search_searxng(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Execute a web search via SearXNG instance."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{SEARXNG_BASE_URL}/search",
                params={
                    "q": query,
                    "format": "json",
                    "number_of_results": max_results,
                },
            )
            response.raise_for_status()
            data = response.json()

        results = []
        for r in data.get("results", [])[:max_results]:
            results.append(
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                }
            )

        return {
            "type": "web_search_result",
            "query": query,
            "results": results,
        }

    except httpx.HTTPStatusError as e:
        logger.error(f"SearXNG error: {e.response.status_code} {e.response.text}")
        return {
            "type": "web_search_result",
            "error": f"SearXNG returned status {e.response.status_code}",
        }
    except Exception as e:
        logger.error(f"Web search (searxng) failed: {e}", exc_info=True)
        return {
            "type": "web_search_result",
            "error": f"Search failed: {str(e)}",
        }

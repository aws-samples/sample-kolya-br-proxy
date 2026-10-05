"""The Gemini API key travels in a header, never in a logged URL."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import gemini_client

API_KEY = "AIza-test-key"  # pragma: allowlist secret


def _settings(**overrides):
    values = {"GEMINI_API_KEY": API_KEY, "GCP_PROJECT_ID": None, "GCP_REGION": None}
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_ai_studio_key_is_sent_as_header_not_query():
    with patch.object(gemini_client, "get_settings", return_value=_settings()):
        url, headers = await gemini_client.build_gemini_url_and_headers(
            "gemini-2.5-flash", "generateContent"
        )

    assert API_KEY not in url
    assert "key=" not in url
    assert headers == {"x-goog-api-key": API_KEY}
    assert url.endswith("/gemini-2.5-flash:generateContent")


@pytest.mark.asyncio
async def test_model_listing_pages_without_key_in_url():
    pages = [
        {"models": [], "nextPageToken": "page-2"},
        {"models": []},
    ]
    responses = []
    for page in pages:
        response = MagicMock()
        response.json.return_value = page
        responses.append(response)
    client = MagicMock()
    client.get = AsyncMock(side_effect=responses)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)

    with patch.object(gemini_client.httpx, "AsyncClient", return_value=context):
        await gemini_client.GeminiClient._list_models_aistudio(API_KEY)

    calls = client.get.await_args_list
    assert len(calls) == 2
    for call in calls:
        assert API_KEY not in str(call.args[0])
        assert call.kwargs["headers"] == {"x-goog-api-key": API_KEY}
    assert calls[1].kwargs["params"] == {"pageSize": 100, "pageToken": "page-2"}


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        ({"prompt_tokens_details": [{"cached_tokens": 12}]}, 12),
        ({"prompt_tokens_details": [{"cached_tokens": None}]}, 0),
        ({"prompt_tokens_details": {"cached_tokens": "n/a"}}, 0),
        ({"prompt_tokens_details": {"cached_tokens": -3}}, 0),
    ],
)
def test_malformed_cached_token_counts_do_not_raise(usage, expected):
    assert gemini_client.extract_cached_tokens({"usage": usage}) == expected

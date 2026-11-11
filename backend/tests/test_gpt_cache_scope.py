"""GPT (Mantle / Runtime Responses) prompt cache is scoped per API key.

Same idea as the Claude path (test_prompt_cache_scope.py): a stable
per-key marker ahead of every implicit breakpoint, plus a per-key
prompt_cache_key the client cannot override.
"""

from types import SimpleNamespace

import pytest

from app.services import cache_scope
from app.services.cache_scope import cache_key, marker_text, scope_responses_cache
from app.services.mantle_client import _openai_to_responses


def _first_text(body):
    return body["input"][0]["content"][0]["text"]


def test_marker_and_cache_key_differ_per_key():
    a, b = {"input": "hi"}, {"input": "hi"}
    scope_responses_cache(a, "key-a")
    scope_responses_cache(b, "key-b")
    assert _first_text(a) != _first_text(b)
    assert a["prompt_cache_key"] != b["prompt_cache_key"]
    assert a["input"][1:] == b["input"][1:]


def test_same_key_is_stable():
    a1, a2 = {"input": "hi"}, {"input": "hi"}
    scope_responses_cache(a1, "key-a")
    scope_responses_cache(a2, "key-a")
    assert a1 == a2


def test_marker_leads_instructions_and_input():
    body = {
        "instructions": "be brief",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "q"}]}],
    }
    scope_responses_cache(body, "key-a")
    assert body["instructions"].startswith(marker_text("key-a"))
    assert body["input"][0]["role"] == "developer"
    assert _first_text(body) == marker_text("key-a")
    assert body["input"][1]["content"][0]["text"] == "q"


def test_string_input_is_wrapped():
    body = {"input": "hello"}
    scope_responses_cache(body, "key-a")
    assert body["input"][1] == {
        "role": "user",
        "content": [{"type": "input_text", "text": "hello"}],
    }


def test_client_prompt_cache_key_is_overwritten():
    body = {"input": "hi", "prompt_cache_key": "someone-elses-partition"}
    scope_responses_cache(body, "key-a")
    assert body["prompt_cache_key"] == cache_key("key-a")


def test_translated_chat_body_is_scoped():
    body = _openai_to_responses(
        {
            "model": "openai.gpt-6-luna",
            "messages": [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
            ],
        }
    )
    scope_responses_cache(body, "key-a")
    assert _first_text(body) == marker_text("key-a")


@pytest.mark.parametrize("scope", [None, ""])
def test_no_scope_no_change(scope):
    body = {"input": "hi"}
    scope_responses_cache(body, scope)
    assert body == {"input": "hi"}


def test_isolation_can_be_disabled(monkeypatch):
    monkeypatch.setattr(
        cache_scope,
        "get_settings",
        lambda: SimpleNamespace(PROMPT_CACHE_TENANT_ISOLATION=False),
    )
    body = {"input": "hi", "prompt_cache_key": "client"}
    scope_responses_cache(body, "key-a")
    assert body == {"input": "hi", "prompt_cache_key": "client"}

"""The prompt cache is partitioned per API key.

Every key shares the gateway's AWS account, so without a per-key marker a
key could learn whether another key sent a given prefix from the
cache-read counters (pentest 2026-11-10).
"""

from types import SimpleNamespace

import pytest

from app.schemas.anthropic import AnthropicMessagesRequest
from app.services import bedrock as bedrock_mod
from app.services.anthropic_translator import AnthropicRequestTranslator
from app.services.bedrock import BedrockClient

CC = {"type": "ephemeral"}
MODEL = "anthropic.claude-haiku-5-5"


def _body(scope, *, tools=True, system="shared system prompt", auto_cache=True):
    payload = {
        "model": MODEL,
        "max_tokens": 16,
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "again"},
        ],
    }
    if system is not None:
        payload["system"] = system
    if tools:
        payload["tools"] = [
            {"name": "lookup", "description": "d", "input_schema": {"type": "object"}}
        ]
    req = AnthropicRequestTranslator.to_bedrock(
        AnthropicMessagesRequest.model_validate(payload)
    )
    req.auto_cache = auto_cache
    req.cache_scope = scope
    return BedrockClient._build_anthropic_body(req, model_id=MODEL)


def _breakpoints(body):
    return len(BedrockClient._collect_cache_blocks(body))


def test_different_keys_get_different_cached_prefixes():
    a, b = _body("key-a"), _body("key-b")
    assert a["system"][0]["text"].startswith("[cache scope ")
    assert a["system"][0] != b["system"][0]
    # Everything after the marker is identical, so only the marker differs.
    assert a["system"][1:] == b["system"][1:]


def test_same_key_keeps_a_stable_prefix():
    assert _body("key-a")["system"] == _body("key-a")["system"]


def test_tool_breakpoint_moves_behind_the_marker():
    body = _body("key-a")
    assert all("cache_control" not in t for t in body["tools"])
    assert "cache_control" in body["system"][-1]


def test_breakpoint_budget_not_exceeded():
    unscoped, scoped = _body(None), _body("key-a")
    assert _breakpoints(scoped) <= _breakpoints(unscoped) <= 4


def test_marker_added_when_client_sent_no_system():
    body = _body("key-a", system=None)
    assert body["system"][0]["text"].startswith("[cache scope ")
    # The moved tool breakpoint lands on the marker itself.
    assert body["system"][-1].get("cache_control") is not None


def test_uncached_request_left_untouched():
    body = _body("key-a", tools=False, system=None, auto_cache=False)
    assert "system" not in body


def test_client_breakpoint_on_user_message_is_scoped():
    req = AnthropicRequestTranslator.to_bedrock(
        AnthropicMessagesRequest.model_validate(
            {
                "model": MODEL,
                "max_tokens": 16,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "doc", "cache_control": CC}
                        ],
                    }
                ],
            }
        )
    )
    req.auto_cache = False
    req.cache_scope = "key-a"
    body = BedrockClient._build_anthropic_body(req, model_id=MODEL)
    assert body["system"][0]["text"].startswith("[cache scope ")


def test_isolation_can_be_disabled(monkeypatch):
    real = bedrock_mod.get_settings()
    monkeypatch.setattr(
        bedrock_mod,
        "get_settings",
        lambda: SimpleNamespace(
            PROMPT_CACHE_TENANT_ISOLATION=False,
            PROMPT_CACHE_AUTO_INJECT=real.PROMPT_CACHE_AUTO_INJECT,
            PROMPT_CACHE_TTL=real.PROMPT_CACHE_TTL,
        ),
    )
    body = _body("key-a")
    assert "[cache scope" not in str(body.get("system"))
    assert "cache_control" in body["tools"][-1]


@pytest.mark.parametrize("scope", [None, ""])
def test_no_scope_means_no_marker(scope):
    body = _body(scope)
    assert "[cache scope" not in str(body["system"])

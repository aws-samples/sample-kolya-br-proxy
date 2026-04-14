"""
Tests for automatic prompt cache breakpoint injection.

Tests call BedrockClient._inject_prompt_cache_breakpoints() directly
on plain dicts — no AWS mocking required.

Strategy (aligned with claudecode-bedrock-proxy):
1. Upgrade TTL on pre-existing breakpoints
2. Inject up to 4 breakpoints (budget = 4 - existing):
   a. Last tool
   b. System prompt (last block)
   c. Last assistant message (last non-thinking block)
"""

from unittest.mock import patch

from app.services.bedrock import BedrockClient

# Default marker with 1h TTL (matching default config) — global model only
MARKER_TTL = {"type": "ephemeral", "ttl": "1h"}
# Marker without TTL — for non-global models or 5m default
MARKER = {"type": "ephemeral"}

TTL_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"  # Claude 4.5 supports ttl
NO_TTL_MODEL = "us.anthropic.claude-sonnet-4-20250514-v1:0"  # Claude 4 does not

LONG_TEXT = "x" * 5000


def _mock_settings(**overrides):
    """Create a mock settings object with prompt cache defaults."""
    defaults = {
        "PROMPT_CACHE_AUTO_INJECT": True,
        "PROMPT_CACHE_TTL": "1h",
    }
    defaults.update(overrides)

    class FakeSettings:
        pass

    s = FakeSettings()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def _inject(body, ttl="1h", model_id=TTL_MODEL):
    """Helper: inject breakpoints with mocked settings."""
    with patch(
        "app.services.bedrock.get_settings",
        return_value=_mock_settings(PROMPT_CACHE_TTL=ttl),
    ):
        BedrockClient._inject_prompt_cache_breakpoints(body, model_id=model_id)


# ---------------------------------------------------------------------------
# Tools (Priority 1)
# ---------------------------------------------------------------------------


def test_inject_last_tool():
    """Last tool gets cache_control."""
    tools = [
        {"name": "a", "description": LONG_TEXT, "input_schema": {}},
        {"name": "b", "description": "short", "input_schema": {}},
    ]
    body = {"tools": tools, "messages": []}
    _inject(body)
    assert "cache_control" not in tools[0]
    assert tools[1]["cache_control"] == MARKER_TTL


def test_inject_single_tool():
    """Single tool gets cache_control."""
    tools = [{"name": "a", "description": "b", "input_schema": {}}]
    body = {"tools": tools, "messages": []}
    _inject(body)
    assert tools[0]["cache_control"] == MARKER_TTL


# ---------------------------------------------------------------------------
# System prompt (Priority 2)
# ---------------------------------------------------------------------------


def test_inject_system_string():
    """System string → converted to array with cache_control."""
    body = {"system": LONG_TEXT, "messages": []}
    _inject(body)
    assert isinstance(body["system"], list)
    assert len(body["system"]) == 1
    assert body["system"][0]["cache_control"] == MARKER_TTL
    assert body["system"][0]["text"] == LONG_TEXT


def test_inject_system_short_string():
    """Short system string → still injected (no threshold)."""
    body = {"system": "hi", "messages": []}
    _inject(body)
    assert isinstance(body["system"], list)
    assert body["system"][0]["cache_control"] == MARKER_TTL


def test_inject_system_array():
    """System already an array → last block gets cache_control."""
    body = {
        "system": [
            {"type": "text", "text": LONG_TEXT},
            {"type": "text", "text": "extra"},
        ],
        "messages": [],
    }
    _inject(body)
    assert "cache_control" not in body["system"][0]
    assert body["system"][1]["cache_control"] == MARKER_TTL


# ---------------------------------------------------------------------------
# Last assistant message (Priority 3)
# ---------------------------------------------------------------------------


def test_inject_last_assistant_msg():
    """Last assistant message gets cache_control."""
    body = {
        "messages": [
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "followup"},
        ],
    }
    _inject(body)
    assistant = body["messages"][1]
    assert isinstance(assistant["content"], list)
    assert assistant["content"][0]["cache_control"] == MARKER_TTL


def test_inject_assistant_skips_thinking():
    """Thinking blocks are skipped; cache_control goes on last non-thinking block."""
    body = {
        "messages": [
            {"role": "user", "content": "question"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "answer"},
                    {"type": "thinking", "thinking": "internal"},
                ],
            },
            {"role": "user", "content": "followup"},
        ],
    }
    _inject(body)
    content = body["messages"][1]["content"]
    # Thinking block should NOT get cache_control
    assert "cache_control" not in content[1]
    # Text block should get it
    assert content[0]["cache_control"] == MARKER_TTL


def test_inject_assistant_skips_redacted_thinking():
    """Redacted thinking blocks are also skipped."""
    body = {
        "messages": [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "a"},
                    {"type": "redacted_thinking", "data": "..."},
                ],
            },
            {"role": "user", "content": "q2"},
        ],
    }
    _inject(body)
    content = body["messages"][1]["content"]
    assert "cache_control" not in content[1]
    assert content[0]["cache_control"] == MARKER_TTL


def test_no_assistant_message():
    """No assistant message → only tools/system injected, no error."""
    body = {
        "system": "prompt",
        "messages": [{"role": "user", "content": "hello"}],
    }
    _inject(body)
    # System should be injected
    assert isinstance(body["system"], list)
    assert body["system"][0]["cache_control"] == MARKER_TTL
    # User message should NOT be touched
    assert body["messages"][0]["content"] == "hello"


# ---------------------------------------------------------------------------
# TTL configuration
# ---------------------------------------------------------------------------


def test_ttl_5m_no_ttl_field():
    """With TTL=5m, marker should be just {"type": "ephemeral"} (no ttl field)."""
    body = {"system": "prompt", "messages": []}
    _inject(body, ttl="5m")
    assert body["system"][0]["cache_control"] == MARKER
    assert "ttl" not in body["system"][0]["cache_control"]


def test_ttl_1h_has_ttl_field_supported_model():
    """With TTL=1h on Claude 4.5 model, marker should include ttl field."""
    body = {"system": "prompt", "messages": []}
    _inject(body, ttl="1h", model_id=TTL_MODEL)
    assert body["system"][0]["cache_control"]["ttl"] == "1h"


def test_ttl_1h_no_ttl_field_unsupported_model():
    """With TTL=1h on Claude 4 model, marker should NOT include ttl field."""
    body = {"system": "prompt", "messages": []}
    _inject(body, ttl="1h", model_id=NO_TTL_MODEL)
    assert "ttl" not in body["system"][0]["cache_control"]
    assert body["system"][0]["cache_control"] == MARKER


def test_upgrade_existing_ttl_supported_model():
    """Pre-existing breakpoints get their TTL upgraded on supported models."""
    body = {
        "system": [
            {"type": "text", "text": "prompt", "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [],
    }
    _inject(body, ttl="1h", model_id=TTL_MODEL)
    # TTL should be upgraded on existing marker
    assert body["system"][0]["cache_control"]["ttl"] == "1h"


def test_strip_existing_ttl_unsupported_model():
    """Pre-existing breakpoints get ttl stripped on unsupported models."""
    body = {
        "system": [
            {
                "type": "text",
                "text": "prompt",
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }
        ],
        "messages": [],
    }
    _inject(body, ttl="1h", model_id=NO_TTL_MODEL)
    # TTL should be stripped for unsupported model
    assert "ttl" not in body["system"][0]["cache_control"]


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------


def test_budget_limit():
    """With 4 pre-existing breakpoints, no new ones are added."""
    body = {
        "system": [
            {"type": "text", "text": "s", "cache_control": {"type": "ephemeral"}}
        ],
        "tools": [
            {"name": "t1", "description": "d", "cache_control": {"type": "ephemeral"}},
            {"name": "t2", "description": "d", "cache_control": {"type": "ephemeral"}},
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "q",
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            },
        ],
    }
    _inject(body, ttl="1h")
    # No new breakpoints should be added (budget exhausted)
    # But TTL should be upgraded (global model)
    assert body["system"][0]["cache_control"]["ttl"] == "1h"
    assert body["tools"][0]["cache_control"]["ttl"] == "1h"


def test_partial_budget():
    """With 2 pre-existing breakpoints, inject up to 2 more."""
    body = {
        "system": [
            {"type": "text", "text": "s", "cache_control": {"type": "ephemeral"}}
        ],
        "tools": [
            {"name": "t1", "description": "d", "cache_control": {"type": "ephemeral"}},
            {"name": "t2", "description": "d"},
        ],
        "messages": [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": "q2"},
        ],
    }
    _inject(body)
    # t2 should get cache_control (tools priority)
    assert body["tools"][1]["cache_control"] == MARKER_TTL
    # Assistant message should also get it (budget allows 2 more)
    assert isinstance(body["messages"][1]["content"], list)
    assert body["messages"][1]["content"][0]["cache_control"] == MARKER_TTL


# ---------------------------------------------------------------------------
# Skip when client already manages caching
# ---------------------------------------------------------------------------


def test_body_has_cache_control_detection():
    """_body_has_cache_control detects existing markers."""
    body = {
        "system": [
            {"type": "text", "text": "s", "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [],
    }
    assert BedrockClient._body_has_cache_control(body) is True


def test_body_has_cache_control_in_tools():
    body = {
        "tools": [{"name": "a", "description": "b", "cache_control": MARKER}],
        "messages": [],
    }
    assert BedrockClient._body_has_cache_control(body) is True


def test_body_has_cache_control_in_messages():
    body = {
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "hi", "cache_control": MARKER}],
            }
        ],
    }
    assert BedrockClient._body_has_cache_control(body) is True


def test_body_no_cache_control():
    body = {"messages": [{"role": "user", "content": "hello"}]}
    assert BedrockClient._body_has_cache_control(body) is False


# ---------------------------------------------------------------------------
# Combined / edge cases
# ---------------------------------------------------------------------------


def test_no_system_no_tools():
    """Minimal body with only messages → no error."""
    body = {"messages": [{"role": "user", "content": "hello"}]}
    _inject(body)
    assert body["messages"][0]["content"] == "hello"


def test_combined_all_breakpoints():
    """Tools + system + assistant message all injected (3 breakpoints)."""
    body = {
        "system": LONG_TEXT,
        "tools": [
            {
                "name": "tool1",
                "description": LONG_TEXT,
                "input_schema": {"type": "object"},
            },
        ],
        "messages": [
            {"role": "user", "content": LONG_TEXT},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "new question"},
        ],
    }
    _inject(body)

    # Last tool → cache_control
    assert body["tools"][0]["cache_control"] == MARKER_TTL

    # System → array with cache_control
    assert isinstance(body["system"], list)
    assert body["system"][0]["cache_control"] == MARKER_TTL

    # Last assistant message → array with cache_control
    assistant = body["messages"][1]
    assert isinstance(assistant["content"], list)
    assert assistant["content"][0]["cache_control"] == MARKER_TTL


def test_empty_system_not_injected():
    """Empty system string → not converted."""
    body = {"system": "", "messages": []}
    _inject(body)
    assert body["system"] == ""


# ---------------------------------------------------------------------------
# Per-request TTL parameter
# ---------------------------------------------------------------------------


def test_inject_with_explicit_ttl_5m():
    """Passing ttl='5m' directly produces marker without ttl field."""
    body = {"system": "prompt", "messages": []}
    with patch(
        "app.services.bedrock.get_settings",
        return_value=_mock_settings(PROMPT_CACHE_TTL="1h"),
    ):
        BedrockClient._inject_prompt_cache_breakpoints(
            body, ttl="5m", model_id=TTL_MODEL
        )
    assert body["system"][0]["cache_control"] == MARKER
    assert "ttl" not in body["system"][0]["cache_control"]


def test_inject_with_explicit_ttl_1h():
    """Passing ttl='1h' directly overrides server default of 5m (supported model)."""
    body = {"system": "prompt", "messages": []}
    with patch(
        "app.services.bedrock.get_settings",
        return_value=_mock_settings(PROMPT_CACHE_TTL="5m"),
    ):
        BedrockClient._inject_prompt_cache_breakpoints(
            body, ttl="1h", model_id=TTL_MODEL
        )
    assert body["system"][0]["cache_control"] == MARKER_TTL


def test_inject_with_explicit_ttl_1h_unsupported():
    """Passing ttl='1h' on unsupported model produces marker without ttl."""
    body = {"system": "prompt", "messages": []}
    with patch(
        "app.services.bedrock.get_settings",
        return_value=_mock_settings(PROMPT_CACHE_TTL="5m"),
    ):
        BedrockClient._inject_prompt_cache_breakpoints(
            body, ttl="1h", model_id=NO_TTL_MODEL
        )
    assert body["system"][0]["cache_control"] == MARKER
    assert "ttl" not in body["system"][0]["cache_control"]


def test_inject_ttl_none_uses_server_default():
    """Passing ttl=None falls back to server setting (supported model)."""
    body = {"system": "prompt", "messages": []}
    with patch(
        "app.services.bedrock.get_settings",
        return_value=_mock_settings(PROMPT_CACHE_TTL="1h"),
    ):
        BedrockClient._inject_prompt_cache_breakpoints(
            body, ttl=None, model_id=TTL_MODEL
        )
    assert body["system"][0]["cache_control"] == MARKER_TTL

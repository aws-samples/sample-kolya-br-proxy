"""
Tests for automatic prompt cache breakpoint injection.

Tests call BedrockClient._inject_prompt_cache_breakpoints() directly
on plain dicts — no AWS mocking required.
"""

import copy


from app.services.bedrock import BedrockClient

MARKER = {"type": "ephemeral"}
THRESHOLD = BedrockClient.MIN_CACHEABLE_CHARS
LONG_TEXT = "x" * (THRESHOLD + 1)
SHORT_TEXT = "hi"


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


def test_inject_system_string():
    """Long system string → converted to array with cache_control."""
    body = {"system": LONG_TEXT, "messages": []}
    BedrockClient._inject_prompt_cache_breakpoints(body)
    assert isinstance(body["system"], list)
    assert len(body["system"]) == 1
    assert body["system"][0]["cache_control"] == MARKER
    assert body["system"][0]["text"] == LONG_TEXT


def test_inject_system_below_threshold():
    """Short system string → unchanged."""
    body = {"system": SHORT_TEXT, "messages": []}
    BedrockClient._inject_prompt_cache_breakpoints(body)
    assert body["system"] == SHORT_TEXT


def test_inject_system_array():
    """System already an array → last block gets cache_control."""
    body = {
        "system": [
            {"type": "text", "text": LONG_TEXT},
            {"type": "text", "text": "extra"},
        ],
        "messages": [],
    }
    BedrockClient._inject_prompt_cache_breakpoints(body)
    assert "cache_control" not in body["system"][0]
    assert body["system"][1]["cache_control"] == MARKER


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def test_inject_last_tool():
    """Last tool gets cache_control when total chars exceed threshold."""
    tools = [
        {"name": "a", "description": LONG_TEXT, "input_schema": {}},
        {"name": "b", "description": "short", "input_schema": {}},
    ]
    body = {"tools": tools, "messages": []}
    BedrockClient._inject_prompt_cache_breakpoints(body)
    assert "cache_control" not in tools[0]
    assert tools[1]["cache_control"] == MARKER


def test_inject_tools_below_threshold():
    """Small tools list → no injection."""
    tools = [{"name": "a", "description": "b", "input_schema": {}}]
    body = {"tools": tools, "messages": []}
    BedrockClient._inject_prompt_cache_breakpoints(body)
    assert "cache_control" not in tools[0]


# ---------------------------------------------------------------------------
# Messages (second-to-last user)
# ---------------------------------------------------------------------------


def test_inject_second_to_last_user_msg():
    """Multiple user msgs → second-to-last user gets cache_control."""
    body = {
        "messages": [
            {"role": "user", "content": LONG_TEXT},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "latest question"},
        ],
    }
    BedrockClient._inject_prompt_cache_breakpoints(body)
    first_user = body["messages"][0]
    # Should have been converted to array
    assert isinstance(first_user["content"], list)
    assert first_user["content"][0]["cache_control"] == MARKER


def test_skip_single_user_msg():
    """Single user message → no messages injection."""
    body = {
        "messages": [
            {"role": "user", "content": LONG_TEXT},
        ],
    }
    original = copy.deepcopy(body)
    BedrockClient._inject_prompt_cache_breakpoints(body)
    assert body["messages"] == original["messages"]


def test_inject_user_msg_array_content():
    """User message with array content → last block gets cache_control."""
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": LONG_TEXT},
                    {"type": "text", "text": "more"},
                ],
            },
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "latest"},
        ],
    }
    BedrockClient._inject_prompt_cache_breakpoints(body)
    blocks = body["messages"][0]["content"]
    assert "cache_control" not in blocks[0]
    assert blocks[1]["cache_control"] == MARKER


# ---------------------------------------------------------------------------
# Skip when client already manages caching
# ---------------------------------------------------------------------------


def test_skip_when_client_cache_control():
    """Body already has cache_control → _body_has_cache_control returns True."""
    body = {
        "system": [
            {"type": "text", "text": LONG_TEXT, "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [],
    }
    assert BedrockClient._body_has_cache_control(body) is True


def test_body_has_cache_control_in_tools():
    body = {
        "tools": [
            {
                "name": "a",
                "description": "b",
                "input_schema": {},
                "cache_control": MARKER,
            }
        ],
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


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_no_system_no_tools():
    """Minimal body with only messages → no error."""
    body = {"messages": [{"role": "user", "content": "hello"}]}
    BedrockClient._inject_prompt_cache_breakpoints(body)
    # Should not raise; message content unchanged (only 1 user msg)
    assert body["messages"][0]["content"] == "hello"


def test_combined_all_breakpoints():
    """System + tools + messages all injected simultaneously."""
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
    BedrockClient._inject_prompt_cache_breakpoints(body)

    # System → array with cache_control
    assert isinstance(body["system"], list)
    assert body["system"][0]["cache_control"] == MARKER

    # Last tool → cache_control
    assert body["tools"][0]["cache_control"] == MARKER

    # Second-to-last user msg → array with cache_control
    first_user = body["messages"][0]
    assert isinstance(first_user["content"], list)
    assert first_user["content"][0]["cache_control"] == MARKER

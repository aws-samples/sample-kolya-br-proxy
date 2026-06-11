"""Tests for built-in tool handling (web_search, computer, etc.)."""

import json
from unittest.mock import patch

import pytest

from app.schemas.anthropic import AnthropicToolDefinition
from app.services.builtin_tools import (
    is_builtin_tool,
    is_web_search_tool,
    process_builtin_tools,
)
from app.services.tool_execution import (
    build_continuation_messages,
    execute_server_tools,
    extract_tool_calls,
    response_has_server_tool_use,
)


class TestBuiltinToolDetection:
    def test_is_builtin_tool_web_search(self):
        tool = AnthropicToolDefinition(
            type="web_search_20250305", name="web_search", max_uses=5
        )
        assert is_builtin_tool(tool)

    def test_is_builtin_tool_computer(self):
        tool = AnthropicToolDefinition(type="computer_20250124", name="computer")
        assert is_builtin_tool(tool)

    def test_is_not_builtin_tool_regular(self):
        tool = AnthropicToolDefinition(
            name="my_func", input_schema={"type": "object"}
        )
        assert not is_builtin_tool(tool)

    def test_is_web_search_tool(self):
        tool = AnthropicToolDefinition(
            type="web_search_20250305", name="web_search"
        )
        assert is_web_search_tool(tool)

    def test_is_web_search_tool_older_version(self):
        tool = AnthropicToolDefinition(
            type="web_search_20250115", name="web_search"
        )
        assert is_web_search_tool(tool)

    def test_is_not_web_search_tool(self):
        tool = AnthropicToolDefinition(type="computer_20250124", name="computer")
        assert not is_web_search_tool(tool)


class TestProcessBuiltinTools:
    @patch("app.services.builtin_tools.is_web_search_configured", return_value=True)
    def test_web_search_converted_to_regular_tool(self, mock_cfg):
        tools = [
            AnthropicToolDefinition(
                type="web_search_20250305", name="web_search", max_uses=3
            ),
        ]
        filtered, has_ws, max_uses = process_builtin_tools(tools, web_search_allowed=True)
        assert has_ws is True
        assert max_uses == 3
        assert len(filtered) == 1
        assert filtered[0].name == "web_search"
        assert filtered[0].input_schema is not None
        assert "query" in filtered[0].input_schema.get("properties", {})

    @patch("app.services.builtin_tools.is_web_search_configured", return_value=False)
    def test_web_search_not_added_without_config(self, mock_cfg):
        tools = [
            AnthropicToolDefinition(
                type="web_search_20250305", name="web_search", max_uses=5
            ),
        ]
        filtered, has_ws, max_uses = process_builtin_tools(tools, web_search_allowed=True)
        assert has_ws is False
        assert filtered is None  # No tools remain

    def test_web_search_blocked_without_token_permission(self):
        tools = [
            AnthropicToolDefinition(
                type="web_search_20250305", name="web_search", max_uses=5
            ),
        ]
        filtered, has_ws, max_uses = process_builtin_tools(tools, web_search_allowed=False)
        assert has_ws is False
        assert filtered is None

    def test_unsupported_tools_filtered(self):
        tools = [
            AnthropicToolDefinition(type="computer_20250124", name="computer"),
            AnthropicToolDefinition(type="bash_20250124", name="bash"),
            AnthropicToolDefinition(
                name="keep_me", input_schema={"type": "object"}
            ),
        ]
        filtered, has_ws, _ = process_builtin_tools(tools)
        assert has_ws is False
        assert len(filtered) == 1
        assert filtered[0].name == "keep_me"

    @patch("app.services.builtin_tools.is_web_search_configured", return_value=True)
    def test_mixed_tools(self, mock_cfg):
        tools = [
            AnthropicToolDefinition(
                type="web_search_20250305", name="web_search", max_uses=8
            ),
            AnthropicToolDefinition(type="computer_20250124", name="computer"),
            AnthropicToolDefinition(
                name="custom", description="desc", input_schema={"type": "object"}
            ),
        ]
        filtered, has_ws, max_uses = process_builtin_tools(tools, web_search_allowed=True)
        assert has_ws is True
        assert max_uses == 8
        assert len(filtered) == 2
        names = {t.name for t in filtered}
        assert names == {"custom", "web_search"}

    def test_none_tools(self):
        filtered, has_ws, max_uses = process_builtin_tools(None)
        assert filtered is None
        assert has_ws is False
        assert max_uses == 0

    def test_default_max_uses(self):
        tools = [
            AnthropicToolDefinition(
                type="web_search_20250305", name="web_search"
            ),
        ]
        with patch(
            "app.services.builtin_tools.is_web_search_configured", return_value=True
        ):
            _, _, max_uses = process_builtin_tools(tools, web_search_allowed=True)
        assert max_uses == 5


class TestToolExecution:
    @pytest.mark.asyncio
    async def test_execute_web_search(self):
        mock_result = {
            "answer": "Python is a language",
            "results": [
                {
                    "title": "Python.org",
                    "url": "https://python.org",
                    "content": "Python programming language",
                }
            ],
        }

        with patch("app.services.tool_execution.execute_web_search") as mock_search:
            mock_search.return_value = {
                "type": "web_search_result",
                "query": "what is python",
                "answer": "Python is a language",
                "results": mock_result["results"],
            }

            tool_calls = [{"id": "call_123", "name": "web_search", "input": {"query": "what is python"}}]
            results = await execute_server_tools(tool_calls)

            assert len(results) == 1
            assert results[0]["tool_use_id"] == "call_123"
            content = json.loads(results[0]["content"])
            assert content["type"] == "web_search_result"
            assert content["query"] == "what is python"

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        tool_calls = [{"id": "call_456", "name": "unknown_tool", "input": {}}]
        results = await execute_server_tools(tool_calls)
        assert len(results) == 1
        assert results[0]["is_error"] is True
        content = json.loads(results[0]["content"])
        assert "not available" in content["error"]


class TestResponseInspection:
    def _make_response(self, stop_reason, content_blocks):
        from unittest.mock import MagicMock

        resp = MagicMock()
        resp.stop_reason = stop_reason
        resp.content = content_blocks
        return resp

    def _make_block(self, btype, **kwargs):
        from unittest.mock import MagicMock

        block = MagicMock()
        block.type = btype
        for k, v in kwargs.items():
            setattr(block, k, v)
        return block

    def test_response_has_server_tool_use_true(self):
        blocks = [
            self._make_block("tool_use", name="web_search", id="c1", input={"query": "q"}),
        ]
        resp = self._make_response("tool_use", blocks)
        assert response_has_server_tool_use(resp)

    def test_response_has_server_tool_use_false_different_tool(self):
        blocks = [
            self._make_block("tool_use", name="custom_tool", id="c1", input={}),
        ]
        resp = self._make_response("tool_use", blocks)
        assert not response_has_server_tool_use(resp)

    def test_response_has_server_tool_use_false_end_turn(self):
        blocks = [
            self._make_block("text", text="hello"),
        ]
        resp = self._make_response("end_turn", blocks)
        assert not response_has_server_tool_use(resp)

    def test_extract_tool_calls(self):
        blocks = [
            self._make_block("thinking", thinking="let me search"),
            self._make_block(
                "tool_use", name="web_search", id="c1", input={"query": "test"}
            ),
        ]
        resp = self._make_response("tool_use", blocks)
        calls = extract_tool_calls(resp)
        assert len(calls) == 1
        assert calls[0]["name"] == "web_search"
        assert calls[0]["id"] == "c1"
        assert calls[0]["input"] == {"query": "test"}


class TestContinuationMessages:
    def test_build_continuation_messages(self):
        original = [
            {"role": "user", "content": "search for python"},
        ]
        assistant_content = [
            {"type": "text", "text": "Let me search."},
            {"type": "tool_use", "id": "c1", "name": "web_search", "input": {"query": "python"}},
        ]
        tool_results = [
            {"type": "tool_result", "tool_use_id": "c1", "content": '{"results": []}'},
        ]

        messages = build_continuation_messages(original, assistant_content, tool_results)
        assert len(messages) == 3
        assert messages[0] == {"role": "user", "content": "search for python"}
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == assistant_content
        assert messages[2]["role"] == "user"
        assert messages[2]["content"] == tool_results

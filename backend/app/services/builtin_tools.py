"""
Built-in tool handling for Anthropic API compatibility.

Anthropic's API supports built-in tools (web_search, computer, text_editor,
bash, code_execution) that use a ``type`` field instead of ``input_schema``.
Bedrock does not support these; KBP must either:
  - web_search: convert to a regular tool and execute searches server-side
  - others: filter out and log a warning
"""

import logging
from typing import List, Optional, Tuple

from app.schemas.anthropic import AnthropicToolDefinition
from app.services.web_search import (
    WEB_SEARCH_TOOL_DEFINITION,
    is_web_search_configured,
)

logger = logging.getLogger(__name__)

WEB_SEARCH_BUILTIN_TYPES = frozenset(
    {
        "web_search_20250305",
        "web_search_20250115",
    }
)

UNSUPPORTED_BUILTIN_TYPES = frozenset(
    {
        "computer_20250124",
        "text_editor_20250124",
        "bash_20250124",
        "code_execution_20250522",
    }
)

BUILTIN_TOOL_TYPES = WEB_SEARCH_BUILTIN_TYPES | UNSUPPORTED_BUILTIN_TYPES


REGULAR_WEB_SEARCH_NAMES = frozenset({"WebSearch"})


def is_builtin_tool(tool: AnthropicToolDefinition) -> bool:
    return tool.type is not None and tool.type in BUILTIN_TOOL_TYPES


def is_regular_web_search_tool(tool: AnthropicToolDefinition) -> bool:
    """Detect client-side web search tools sent as regular tools (e.g. Claude Code's WebSearch)."""
    return tool.name is not None and tool.name in REGULAR_WEB_SEARCH_NAMES


def is_web_search_tool(tool: AnthropicToolDefinition) -> bool:
    return tool.type is not None and tool.type.startswith("web_search_")


def process_builtin_tools(
    tools: Optional[List[AnthropicToolDefinition]],
    web_search_allowed: bool = False,
    web_search_provider: Optional[str] = None,
) -> Tuple[Optional[List[AnthropicToolDefinition]], bool, int]:
    """
    Process tools list, handling built-in tools.

    Args:
        tools: list of tool definitions from the request
        web_search_allowed: whether the token has web_search enabled
        web_search_provider: which search provider to use ("tavily" or "searxng")

    Returns:
        (filtered_tools, has_web_search, web_search_max_uses)
        - filtered_tools: tools list with built-in tools removed/converted
        - has_web_search: whether web_search was requested AND allowed
        - web_search_max_uses: max number of search calls allowed (from client)
    """
    if not tools:
        return tools, False, 0

    filtered: List[AnthropicToolDefinition] = []
    has_web_search = False
    has_regular_web_search = False
    web_search_max_uses = 5
    unsupported_warned: List[str] = []

    for tool in tools:
        if is_regular_web_search_tool(tool):
            has_web_search = True
            has_regular_web_search = True
            filtered.append(tool)
            continue

        if not is_builtin_tool(tool):
            filtered.append(tool)
            continue

        if is_web_search_tool(tool):
            has_web_search = True
            if tool.max_uses is not None:
                web_search_max_uses = tool.max_uses
        elif tool.type in UNSUPPORTED_BUILTIN_TYPES:
            unsupported_warned.append(tool.type)

    if unsupported_warned:
        logger.warning(
            f"Unsupported built-in tools filtered: {unsupported_warned}. "
            "These require a local execution environment."
        )

    if has_web_search and not web_search_allowed:
        logger.warning(
            "Client requested web_search but token does not have "
            "web_search_enabled=true in metadata. Tool will not be available."
        )
        has_web_search = False
    elif has_web_search and not is_web_search_configured(web_search_provider):
        logger.warning(
            f"Client requested web_search (provider={web_search_provider}) "
            "but it is not configured. Tool will not be available."
        )
        has_web_search = False
    elif has_web_search and not has_regular_web_search:
        # Only inject our tool definition for built-in type web_search;
        # regular tools like WebSearch already have their own definition.
        filtered.append(WEB_SEARCH_TOOL_DEFINITION)

    return filtered if filtered else None, has_web_search, web_search_max_uses

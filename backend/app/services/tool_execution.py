"""
Server-side tool execution loop for built-in tools.

When Claude returns a tool_use for web_search, this module executes the search
and re-invokes Claude with the results, repeating until Claude produces a final
response or the max_uses limit is reached.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List

from app.schemas.bedrock import BedrockResponse
from app.services.web_search import execute_web_search

logger = logging.getLogger(__name__)

SERVER_EXECUTED_TOOLS = frozenset({"web_search", "WebSearch"})


def response_has_server_tool_use(response: BedrockResponse) -> bool:
    """Check if a Bedrock response contains ONLY server-executed tool_use blocks.

    Returns True only when ALL tool_use blocks in the response are server-executed.
    If the response mixes server and client tools, return False so the response
    streams back to the client (which will handle its own tools).
    """
    if response.stop_reason != "tool_use":
        return False
    tool_blocks = [b for b in (response.content or []) if b.type == "tool_use"]
    if not tool_blocks:
        return False
    return all(b.name in SERVER_EXECUTED_TOOLS for b in tool_blocks)


def extract_tool_calls(response: BedrockResponse) -> List[Dict[str, Any]]:
    """Extract all tool_use blocks from a Bedrock response."""
    calls = []
    for block in response.content or []:
        if block.type == "tool_use":
            calls.append(
                {
                    "id": block.id,
                    "name": block.name,
                    "input": block.input or {},
                }
            )
    return calls


async def _execute_single_tool(
    call: Dict[str, Any], provider: str | None = None
) -> Dict[str, Any]:
    """Execute a single server-side tool call and return a tool_result block."""
    if call["name"] in ("web_search", "WebSearch"):
        query = call["input"].get("query", "")
        search_result = await execute_web_search(query, provider=provider)
        return {
            "type": "tool_result",
            "tool_use_id": call["id"],
            "content": json.dumps(search_result, ensure_ascii=False),
        }
    return {
        "type": "tool_result",
        "tool_use_id": call["id"],
        "content": json.dumps(
            {"error": f"Tool '{call['name']}' is not available server-side."}
        ),
        "is_error": True,
    }


async def execute_server_tools(
    tool_calls: List[Dict[str, Any]],
    provider: str | None = None,
) -> List[Dict[str, Any]]:
    """
    Execute server-side tools concurrently and return tool_result blocks.

    Returns list of dicts suitable for inserting as content blocks in a user message.
    """
    return list(
        await asyncio.gather(*[_execute_single_tool(c, provider) for c in tool_calls])
    )


def build_continuation_messages(
    original_messages: List[Any],
    assistant_content: List[Dict[str, Any]],
    tool_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Build the messages array for a continuation request after tool execution.

    Appends:
    1. The assistant message with all content blocks from the response
    2. A user message containing the tool_result blocks
    """
    messages = []
    for msg in original_messages:
        if isinstance(msg, dict):
            messages.append(msg)
        elif hasattr(msg, "model_dump"):
            messages.append(msg.model_dump(exclude_none=True))
        else:
            messages.append({"role": msg.role, "content": msg.content})

    messages.append({"role": "assistant", "content": assistant_content})
    messages.append({"role": "user", "content": tool_results})
    return messages


def serialize_response_content(response: BedrockResponse) -> List[Dict[str, Any]]:
    """Serialize Bedrock response content blocks to dicts."""
    blocks = []
    for block in response.content or []:
        if block.type == "text":
            blocks.append({"type": "text", "text": block.text or ""})
        elif block.type == "tool_use":
            blocks.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input or {},
                }
            )
        elif block.type == "thinking":
            b = {"type": "thinking", "thinking": block.thinking or ""}
            if block.signature:
                b["signature"] = block.signature
            blocks.append(b)
        elif block.type == "redacted_thinking":
            blocks.append({"type": "redacted_thinking", "data": block.data or ""})
        else:
            if hasattr(block, "model_dump"):
                blocks.append(block.model_dump(exclude_none=True))
    return blocks

"""
Request/response translator between Anthropic Messages API and Bedrock formats.

Since Bedrock Anthropic models natively use the Messages API format,
most of the translation is near-passthrough. The main work is in
streaming event format conversion.
"""

import logging

from app.schemas.anthropic import (
    AnthropicMessagesRequest,
    AnthropicMessagesResponse,
    AnthropicResponseRedactedThinkingContent,
    AnthropicResponseTextContent,
    AnthropicResponseThinkingContent,
    AnthropicResponseToolUseContent,
    AnthropicUsage,
)
from app.schemas.bedrock import (
    BedrockContentPart,
    BedrockMessage,
    BedrockRequest,
    BedrockResponse,
    BedrockStreamEvent,
    BedrockTool,
)

logger = logging.getLogger(__name__)


class AnthropicRequestTranslator:
    """Translates Anthropic Messages API requests to Bedrock format."""

    @staticmethod
    def to_bedrock(request: AnthropicMessagesRequest) -> BedrockRequest:
        """
        Convert Anthropic Messages API request to internal BedrockRequest.

        The formats are very similar since Bedrock Anthropic models use
        the Messages API natively. Main conversion is structural.
        """
        # Convert messages
        messages = []
        for msg in request.messages:
            if isinstance(msg.content, str):
                messages.append(BedrockMessage(role=msg.role, content=msg.content))
            elif isinstance(msg.content, list):
                parts = []
                for block in msg.content:
                    if isinstance(block, dict):
                        part_dict = block
                    else:
                        part_dict = block.model_dump(exclude_none=True)

                    block_type = part_dict.get("type")

                    if block_type == "text":
                        part = BedrockContentPart(
                            type="text", text=part_dict.get("text", "")
                        )
                        if "cache_control" in part_dict:
                            # cache_control is passed through via the raw dict later
                            pass
                        parts.append(part)
                    elif block_type == "image":
                        source = part_dict.get("source", {})
                        parts.append(
                            BedrockContentPart(
                                type="image",
                                source={
                                    "type": source.get("type", "base64"),
                                    "media_type": source.get(
                                        "media_type", "image/jpeg"
                                    ),
                                    "data": source.get("data", ""),
                                },
                            )
                        )
                    elif block_type == "tool_use":
                        parts.append(
                            BedrockContentPart(
                                type="tool_use",
                                id=part_dict.get("id", ""),
                                name=part_dict.get("name", ""),
                                input=part_dict.get("input", {}),
                            )
                        )
                    elif block_type == "tool_result":
                        content_val = part_dict.get("content", "")
                        if isinstance(content_val, list):
                            # Extract text from content blocks
                            content_val = " ".join(
                                item.get("text", "")
                                for item in content_val
                                if isinstance(item, dict) and item.get("type") == "text"
                            )
                        parts.append(
                            BedrockContentPart(
                                type="tool_result",
                                tool_use_id=part_dict.get("tool_use_id", ""),
                                content=content_val
                                if isinstance(content_val, str)
                                else str(content_val),
                            )
                        )
                    elif block_type == "thinking":
                        parts.append(
                            BedrockContentPart(
                                type="thinking",
                                thinking=part_dict.get("thinking", ""),
                                signature=part_dict.get("signature"),
                            )
                        )
                    elif block_type == "redacted_thinking":
                        parts.append(
                            BedrockContentPart(
                                type="redacted_thinking",
                                data=part_dict.get("data", ""),
                            )
                        )
                    else:
                        # Unknown type - pass through as dict
                        parts.append(part_dict)

                messages.append(BedrockMessage(role=msg.role, content=parts))

        # Extract system message
        system_text = None
        if request.system:
            if isinstance(request.system, str):
                system_text = request.system
            elif isinstance(request.system, list):
                # List of system blocks - extract text
                system_text = " ".join(
                    block.text for block in request.system if hasattr(block, "text")
                )

        # Build additional_model_request_fields for thinking, top_k, etc.
        additional_fields = {}
        if request.thinking:
            thinking_dict = request.thinking.model_dump(exclude_none=True)
            additional_fields["thinking"] = thinking_dict
        if request.top_k is not None:
            additional_fields["top_k"] = request.top_k

        if request.disable_parallel_tool_use is not None:
            additional_fields["disable_parallel_tool_use"] = (
                request.disable_parallel_tool_use
            )

        # Convert tools
        bedrock_tools = None
        if request.tools:
            bedrock_tools = [
                BedrockTool(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.input_schema,
                    strict=tool.strict,
                )
                for tool in request.tools
            ]

        bedrock_request = BedrockRequest(
            max_tokens=request.max_tokens,
            messages=messages,
            temperature=request.temperature,
            top_p=request.top_p,
            system=system_text,
            stop_sequences=request.stop_sequences,
            tools=bedrock_tools,
            tool_choice=request.tool_choice,
            additional_model_request_fields=additional_fields
            if additional_fields
            else None,
        )

        logger.info(
            f"Anthropic→Bedrock: {len(messages)} messages, model={request.model}"
        )
        return bedrock_request

    @staticmethod
    def to_bedrock_with_passthrough(request: AnthropicMessagesRequest) -> dict:
        """
        Build the raw Anthropic Messages API body for direct passthrough to
        invoke_model. This preserves cache_control markers and other native fields
        that would be lost in the BedrockRequest conversion.

        Returns a dict that can be passed to _build_anthropic_body logic or
        directly to invoke_model.
        """
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": request.max_tokens,
        }

        # Messages - serialize directly preserving all fields
        messages = []
        for msg in request.messages:
            if isinstance(msg.content, str):
                messages.append({"role": msg.role, "content": msg.content})
            elif isinstance(msg.content, list):
                parts = []
                for block in msg.content:
                    if isinstance(block, dict):
                        part = dict(block)
                    else:
                        part = block.model_dump(exclude_none=True)
                    parts.append(part)
                messages.append({"role": msg.role, "content": parts})
        body["messages"] = messages

        # System
        if request.system:
            if isinstance(request.system, str):
                body["system"] = request.system
            elif isinstance(request.system, list):
                body["system"] = [
                    block.model_dump(exclude_none=True) for block in request.system
                ]

        # Optional fields
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.top_p is not None:
            body["top_p"] = request.top_p
        if request.top_k is not None:
            body["top_k"] = request.top_k
        if request.stop_sequences:
            body["stop_sequences"] = request.stop_sequences

        # Tools
        if request.tools:
            tools = []
            for tool in request.tools:
                tool_dict = {
                    "name": tool.name,
                    "input_schema": tool.input_schema,
                }
                if tool.description:
                    tool_dict["description"] = tool.description
                if tool.cache_control:
                    tool_dict["cache_control"] = tool.cache_control
                tools.append(tool_dict)
            body["tools"] = tools

        if request.tool_choice:
            body["tool_choice"] = request.tool_choice

        # Thinking
        if request.thinking:
            body["thinking"] = request.thinking.model_dump(exclude_none=True)

        # Metadata
        if request.metadata:
            body["metadata"] = request.metadata

        return body


class AnthropicResponseTranslator:
    """Translates Bedrock responses to Anthropic Messages API format."""

    @staticmethod
    def bedrock_to_anthropic(
        bedrock_response: BedrockResponse, model: str, request_id: str
    ) -> AnthropicMessagesResponse:
        """Convert Bedrock response to Anthropic Messages API format."""
        content = []

        for block in bedrock_response.content:
            if block.type == "text" and block.text:
                content.append(AnthropicResponseTextContent(text=block.text))
            elif block.type == "tool_use":
                content.append(
                    AnthropicResponseToolUseContent(
                        id=block.id or "",
                        name=block.name or "",
                        input=block.input or {},
                    )
                )
            elif block.type == "thinking":
                if block.thinking is not None:
                    content.append(
                        AnthropicResponseThinkingContent(
                            thinking=block.thinking,
                            signature=block.signature,
                        )
                    )
            elif block.type == "redacted_thinking":
                if block.data is not None:
                    content.append(
                        AnthropicResponseRedactedThinkingContent(data=block.data)
                    )

        usage = AnthropicUsage(
            input_tokens=bedrock_response.usage.input_tokens or 0,
            output_tokens=bedrock_response.usage.output_tokens or 0,
            cache_creation_input_tokens=bedrock_response.usage.cache_creation_input_tokens
            or None,
            cache_read_input_tokens=bedrock_response.usage.cache_read_input_tokens
            or None,
        )

        return AnthropicMessagesResponse(
            id=bedrock_response.id or request_id,
            content=content,
            model=model,
            stop_reason=bedrock_response.stop_reason,
            stop_sequence=bedrock_response.stop_sequence,
            usage=usage,
        )

    @staticmethod
    def create_stream_event(event_type: str, data: dict) -> str:
        """Create an Anthropic SSE formatted event.

        Anthropic format: "event: {type}\\ndata: {json}\\n\\n"
        """
        import json

        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    @staticmethod
    def bedrock_stream_to_anthropic_events(
        event: BedrockStreamEvent,
        model: str,
        request_id: str,
        accumulated_usage: dict,
    ) -> list[str]:
        """
        Convert a BedrockStreamEvent to Anthropic SSE event string(s).

        Args:
            event: Bedrock stream event
            model: Model name
            request_id: Request ID
            accumulated_usage: Mutable dict tracking usage across events

        Returns:
            List of SSE formatted strings
        """
        import json

        results = []

        if event.type == "message_start":
            # Collect input usage
            if event.usage:
                accumulated_usage["input_tokens"] = event.usage.input_tokens or 0
                accumulated_usage["cache_creation_input_tokens"] = (
                    event.usage.cache_creation_input_tokens or 0
                )
                accumulated_usage["cache_read_input_tokens"] = (
                    event.usage.cache_read_input_tokens or 0
                )

            # Build message_start with initial message object
            usage_dict = {
                "input_tokens": accumulated_usage.get("input_tokens", 0),
                "output_tokens": 0,
            }
            cache_create = accumulated_usage.get("cache_creation_input_tokens", 0)
            cache_read = accumulated_usage.get("cache_read_input_tokens", 0)
            if cache_create:
                usage_dict["cache_creation_input_tokens"] = cache_create
            if cache_read:
                usage_dict["cache_read_input_tokens"] = cache_read

            message_data = {
                "type": "message_start",
                "message": {
                    "id": request_id,
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": model,
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": usage_dict,
                },
            }
            results.append(
                f"event: message_start\ndata: {json.dumps(message_data)}\n\n"
            )

            # Send ping after message_start
            results.append(f"event: ping\ndata: {json.dumps({'type': 'ping'})}\n\n")

        elif event.type == "content_block_start":
            content_block = {}
            if event.content_block:
                if isinstance(event.content_block, dict):
                    content_block = event.content_block
                else:
                    content_block = {
                        "type": event.content_block.type,
                    }
                    if event.content_block.id:
                        content_block["id"] = event.content_block.id
                    if event.content_block.name:
                        content_block["name"] = event.content_block.name

                # Add default fields based on type
                block_type = content_block.get("type", "text")
                if block_type == "text" and "text" not in content_block:
                    content_block["text"] = ""
                elif block_type == "tool_use" and "input" not in content_block:
                    content_block["input"] = {}
                elif block_type == "thinking" and "thinking" not in content_block:
                    content_block["thinking"] = ""

            data = {
                "type": "content_block_start",
                "index": event.index or 0,
                "content_block": content_block,
            }
            results.append(f"event: content_block_start\ndata: {json.dumps(data)}\n\n")

        elif event.type == "content_block_delta":
            delta = {}
            if event.delta:
                if "text" in event.delta:
                    delta = {"type": "text_delta", "text": event.delta["text"]}
                elif "partial_json" in event.delta:
                    delta = {
                        "type": "input_json_delta",
                        "partial_json": event.delta["partial_json"],
                    }
                elif "thinking" in event.delta:
                    delta = {
                        "type": "thinking_delta",
                        "thinking": event.delta["thinking"],
                    }
                elif "signature" in event.delta:
                    delta = {
                        "type": "signature_delta",
                        "signature": event.delta["signature"],
                    }

            data = {
                "type": "content_block_delta",
                "index": event.index or 0,
                "delta": delta,
            }
            results.append(f"event: content_block_delta\ndata: {json.dumps(data)}\n\n")

        elif event.type == "content_block_stop":
            data = {
                "type": "content_block_stop",
                "index": event.index or 0,
            }
            results.append(f"event: content_block_stop\ndata: {json.dumps(data)}\n\n")

        elif event.type == "message_delta":
            # Collect output usage
            if event.usage:
                accumulated_usage["output_tokens"] = event.usage.output_tokens or 0

            stop_reason = event.delta.get("stop_reason") if event.delta else None

            usage_dict = {"output_tokens": accumulated_usage.get("output_tokens", 0)}

            data = {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": usage_dict,
            }
            results.append(f"event: message_delta\ndata: {json.dumps(data)}\n\n")

        elif event.type == "message_stop":
            data = {"type": "message_stop"}
            results.append(f"event: message_stop\ndata: {json.dumps(data)}\n\n")

        return results

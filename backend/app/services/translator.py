"""
Request/response translator between OpenAI and Bedrock formats.
"""

import time

from app.schemas.bedrock import BedrockMessage, BedrockRequest, BedrockResponse
from app.schemas.openai import (
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    UsageInfo,
)


class RequestTranslator:
    """Translates OpenAI requests to Bedrock format."""

    @staticmethod
    def _parse_base64_image(data_url: str):
        """
        Parse base64 encoded image from data URL.

        Args:
            data_url: Data URL like "data:image/jpeg;base64,..."

        Returns:
            BedrockContentPart with image data
        """
        from app.schemas.bedrock import BedrockContentPart

        # Parse data URL
        if not data_url.startswith("data:"):
            raise ValueError("Invalid data URL format")

        # Extract media type and base64 data
        header, data = data_url.split(",", 1)
        media_type = header.split(":")[1].split(";")[0]  # e.g., "image/jpeg"

        return BedrockContentPart(
            type="image",
            source={"type": "base64", "media_type": media_type, "data": data},
        )

    @staticmethod
    def _fetch_and_encode_image(image_url: str):
        """
        Fetch image from URL and encode as base64.

        Args:
            image_url: URL to image

        Returns:
            BedrockContentPart with image data
        """
        import base64
        import requests
        from app.schemas.bedrock import BedrockContentPart

        try:
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()

            # Determine media type from content-type header
            media_type = response.headers.get("content-type", "image/jpeg")

            # Encode to base64
            image_data = base64.b64encode(response.content).decode("utf-8")

            return BedrockContentPart(
                type="image",
                source={"type": "base64", "media_type": media_type, "data": image_data},
            )
        except Exception as e:
            raise ValueError(f"Failed to fetch image from URL: {str(e)}")

    @staticmethod
    def openai_to_bedrock(request: ChatCompletionRequest) -> BedrockRequest:
        """
        Convert OpenAI chat completion request to Bedrock format.

        Args:
            request: OpenAI format request

        Returns:
            Bedrock format request
        """
        from app.schemas.bedrock import BedrockContentPart

        import logging

        logger = logging.getLogger(__name__)

        # Warn about ignored OpenAI parameters
        if request.n and request.n != 1:
            logger.warning(
                f"OpenAI parameter 'n' (n={request.n}) is not supported by Bedrock and will be ignored. "
                "Only single completion (n=1) is supported."
            )
        if request.presence_penalty and request.presence_penalty != 0.0:
            logger.warning(
                f"OpenAI parameter 'presence_penalty' ({request.presence_penalty}) is not supported by Bedrock and will be ignored."
            )
        if request.frequency_penalty and request.frequency_penalty != 0.0:
            logger.warning(
                f"OpenAI parameter 'frequency_penalty' ({request.frequency_penalty}) is not supported by Bedrock and will be ignored."
            )

        # Extract system message if present
        system_message = None
        messages = []

        # Track tool_use IDs to validate tool_result blocks
        expected_tool_results = set()

        # Collect consecutive tool messages to merge into one user message
        i = 0
        while i < len(request.messages):
            msg = request.messages[i]

            # Handle tool role messages - collect all consecutive tool messages
            if msg.role == "tool":
                tool_results = []
                while i < len(request.messages) and request.messages[i].role == "tool":
                    tool_msg = request.messages[i]

                    # Only include tool results that have corresponding tool_use
                    if tool_msg.tool_call_id not in expected_tool_results:
                        logger.warning(
                            f"Dropping invalid tool result: tool_call_id={tool_msg.tool_call_id} has no corresponding tool_use. "
                            f"Expected tool_use IDs: {expected_tool_results}. "
                            "This tool result will be silently dropped from the Bedrock request."
                        )
                        i += 1
                        continue

                    # Extract text content from msg.content
                    content_text = ""
                    if isinstance(tool_msg.content, str):
                        content_text = tool_msg.content
                    elif isinstance(tool_msg.content, list):
                        # Extract text from ContentPart list
                        content_text = " ".join(
                            part.text
                            for part in tool_msg.content
                            if hasattr(part, "text") and part.text
                        )

                    tool_results.append(
                        BedrockContentPart(
                            type="tool_result",
                            tool_use_id=tool_msg.tool_call_id,
                            content=content_text,
                        )
                    )
                    expected_tool_results.discard(tool_msg.tool_call_id)
                    i += 1

                # Add all tool results as one user message (if any valid results)
                if tool_results:
                    messages.append(BedrockMessage(role="user", content=tool_results))
                continue

            # Handle assistant messages with tool_calls
            if msg.role == "assistant" and msg.tool_calls:
                # Check if next message(s) are tool results
                # If not, skip this assistant message with tool_calls to avoid validation error
                has_tool_results = False
                if i + 1 < len(request.messages):
                    next_msg = request.messages[i + 1]
                    if next_msg.role == "tool":
                        has_tool_results = True

                # Only include assistant message with tool_calls if followed by tool results
                if not has_tool_results:
                    logger.warning(
                        f"Skipping assistant message with tool_calls at index {i} "
                        "because it's not followed by tool results"
                    )
                    i += 1
                    continue

                # Track tool_use IDs for validation
                for tool_call in msg.tool_calls:
                    expected_tool_results.add(tool_call.id)
                # Convert tool_calls to Bedrock format
                import json

                content_parts = []
                # Add text content if present
                if msg.content:
                    if isinstance(msg.content, str):
                        content_parts.append(
                            BedrockContentPart(type="text", text=msg.content)
                        )
                    elif isinstance(msg.content, list):
                        # Extract text from ContentPart list
                        for part in msg.content:
                            if (
                                hasattr(part, "type")
                                and part.type == "text"
                                and hasattr(part, "text")
                            ):
                                content_parts.append(
                                    BedrockContentPart(type="text", text=part.text)
                                )
                # Add tool_use blocks
                for tool_call in msg.tool_calls:
                    if tool_call.type == "function":
                        content_parts.append(
                            BedrockContentPart(
                                type="tool_use",
                                id=tool_call.id,
                                name=tool_call.function.get("name", ""),
                                input=json.loads(
                                    tool_call.function.get("arguments", "{}")
                                ),
                            )
                        )
                messages.append(BedrockMessage(role="assistant", content=content_parts))
                i += 1
                continue

            # Handle both string and array content formats
            if isinstance(msg.content, list):
                # Multimodal format - preserve images and text
                content_parts = []
                for part in msg.content:
                    if part.type == "text" and part.text:
                        content_parts.append(
                            BedrockContentPart(type="text", text=part.text)
                        )
                    elif part.type == "image_url" and part.image_url:
                        # Convert OpenAI image_url format to Bedrock format
                        image_url = part.image_url.get("url", "")
                        if image_url.startswith("data:"):
                            # Base64 encoded image
                            content_parts.append(
                                RequestTranslator._parse_base64_image(image_url)
                            )
                        else:
                            # URL-based image - fetch and convert to base64
                            content_parts.append(
                                RequestTranslator._fetch_and_encode_image(image_url)
                            )

                if msg.role == "system":
                    # System messages should be text only
                    system_message = " ".join(
                        part.text
                        for part in content_parts
                        if part.type == "text" and part.text
                    )
                else:
                    messages.append(
                        BedrockMessage(role=msg.role, content=content_parts)
                    )
                i += 1
                continue

            # String content format
            if msg.role == "system":
                system_message = msg.content
            else:
                messages.append(BedrockMessage(role=msg.role, content=msg.content))
            i += 1

        # Build Bedrock request
        # Use temperature if provided, otherwise use top_p (but not both)
        bedrock_request = BedrockRequest(
            max_tokens=request.max_tokens or 4096,
            messages=messages,
            temperature=request.temperature
            if request.temperature is not None
            else None,
            top_p=request.top_p
            if request.temperature is None and request.top_p is not None
            else None,
            system=system_message,
            # Pass through Bedrock-specific parameters
            guardrail_config=request.bedrock_guardrail_config,
            additional_model_request_fields=request.bedrock_additional_model_request_fields,
            trace=request.bedrock_trace,
            performance_config=request.bedrock_performance_config,
            prompt_caching=request.bedrock_prompt_caching,
            prompt_variables=request.bedrock_prompt_variables,
            additional_model_response_field_paths=request.bedrock_additional_model_response_field_paths,
            request_metadata=request.bedrock_request_metadata,
        )

        # Debug logging
        import logging

        logger = logging.getLogger(__name__)
        logger.info(f"Bedrock request messages: {len(messages)} messages")
        for idx, msg in enumerate(messages):
            if isinstance(msg.content, list):
                content_types = [c.type for c in msg.content]
                logger.info(
                    f"  Message {idx}: role={msg.role}, content_types={content_types}"
                )
            else:
                logger.info(f"  Message {idx}: role={msg.role}, content=string")

        # Add stop sequences if provided
        if request.stop:
            if isinstance(request.stop, str):
                bedrock_request.stop_sequences = [request.stop]
            else:
                bedrock_request.stop_sequences = request.stop

        # Convert tools if provided
        if request.tools:
            from app.schemas.bedrock import BedrockTool

            bedrock_tools = []
            for tool in request.tools:
                if tool.get("type") == "function":
                    func = tool.get("function", {})
                    bedrock_tools.append(
                        BedrockTool(
                            name=func.get("name", ""),
                            description=func.get("description", ""),
                            input_schema=func.get("parameters", {}),
                        )
                    )
            if bedrock_tools:
                bedrock_request.tools = bedrock_tools

        # Convert tool_choice if provided
        if request.tool_choice:
            if isinstance(request.tool_choice, str):
                if request.tool_choice == "auto":
                    bedrock_request.tool_choice = {"type": "auto"}
                elif request.tool_choice == "none":
                    bedrock_request.tool_choice = {"type": "none"}
                elif request.tool_choice == "required":
                    bedrock_request.tool_choice = {"type": "any"}
            elif isinstance(request.tool_choice, dict):
                # {"type": "function", "function": {"name": "..."}}
                if request.tool_choice.get("type") == "function":
                    func_name = request.tool_choice.get("function", {}).get("name")
                    if func_name:
                        bedrock_request.tool_choice = {
                            "type": "tool",
                            "name": func_name,
                        }

        return bedrock_request


class ResponseTranslator:
    """Translates Bedrock responses to OpenAI format."""

    @staticmethod
    def bedrock_to_openai(
        bedrock_response: BedrockResponse, model: str, request_id: str
    ) -> ChatCompletionResponse:
        """
        Convert Bedrock response to OpenAI format.

        Args:
            bedrock_response: Bedrock format response
            model: Model name used
            request_id: Unique request ID

        Returns:
            OpenAI format response
        """
        import json
        from app.schemas.openai import ToolCall

        # Extract text content and tool calls from Bedrock response
        content = ""
        tool_calls = []

        for block in bedrock_response.content:
            if block.type == "thinking":
                # Skip thinking blocks (not compatible with OpenAI format)
                continue
            if block.type == "text" and block.text:
                content += block.text
            elif block.type == "tool_use":
                # Convert Bedrock tool_use to OpenAI tool_call format
                tool_call = ToolCall(
                    id=block.id or f"call_{len(tool_calls)}",
                    type="function",
                    function={
                        "name": block.name or "",
                        "arguments": json.dumps(block.input or {}),
                    },
                )
                tool_calls.append(tool_call)

        # Create OpenAI format message
        message = ChatMessage(
            role="assistant",
            content=content if content else None,
            tool_calls=tool_calls if tool_calls else None,
        )

        # Map Bedrock stop_reason to OpenAI finish_reason
        finish_reason = bedrock_response.stop_reason or "stop"
        if finish_reason == "tool_use":
            finish_reason = "tool_calls"

        # Create choice
        choice = ChatCompletionChoice(
            index=0,
            message=message,
            finish_reason=finish_reason,
        )

        # Create usage info
        usage = UsageInfo(
            prompt_tokens=bedrock_response.usage.input_tokens,
            completion_tokens=bedrock_response.usage.output_tokens,
            total_tokens=bedrock_response.usage.input_tokens
            + bedrock_response.usage.output_tokens,
        )

        # Build OpenAI response
        return ChatCompletionResponse(
            id=request_id,
            created=int(time.time()),
            model=model,
            choices=[choice],
            usage=usage,
        )

    @staticmethod
    def create_stream_chunk(
        request_id: str,
        model: str,
        delta_content: str = "",
        finish_reason: str | None = None,
        tool_calls: list | None = None,
    ) -> str:
        """
        Create OpenAI streaming response chunk in SSE format.

        Args:
            request_id: Unique request ID
            model: Model name
            delta_content: Content delta for this chunk
            finish_reason: Finish reason if stream is ending
            tool_calls: Tool calls delta for this chunk

        Returns:
            SSE formatted string
        """
        from app.schemas.openai import (
            ChatCompletionStreamChoice,
            ChatCompletionStreamResponse,
        )

        # Build delta
        delta = {}
        if delta_content:
            delta["content"] = delta_content
        if tool_calls:
            delta["tool_calls"] = tool_calls
        if finish_reason:
            delta["finish_reason"] = finish_reason

        # Create choice
        choice = ChatCompletionStreamChoice(
            index=0, delta=delta, finish_reason=finish_reason
        )

        # Create stream response
        chunk = ChatCompletionStreamResponse(
            id=request_id,
            created=int(time.time()),
            model=model,
            choices=[choice],
        )

        # Format as SSE
        return f"data: {chunk.model_dump_json()}\n\n"

    @staticmethod
    def create_stream_usage_chunk(
        request_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> str:
        """
        Create a final streaming chunk with usage information.

        Per OpenAI spec, this chunk has empty choices and includes usage.
        """
        from app.schemas.openai import (
            ChatCompletionStreamResponse,
            UsageInfo,
        )

        usage = UsageInfo(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

        chunk = ChatCompletionStreamResponse(
            id=request_id,
            created=int(time.time()),
            model=model,
            choices=[],
            usage=usage,
        )

        return f"data: {chunk.model_dump_json()}\n\n"

    @staticmethod
    def create_stream_done() -> str:
        """Create stream done marker."""
        return "data: [DONE]\n\n"

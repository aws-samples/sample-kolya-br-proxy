"""
AWS Bedrock client service.

Anthropic models use InvokeModel / InvokeModelWithResponseStream so that
native parameters (thinking, effort, prompt caching, etc.) are passed
through directly in the Messages API body.

Non-Anthropic models (Nova, DeepSeek, etc.) use the Bedrock Converse /
ConverseStream API, which is model-agnostic and handles format conversion
automatically.
"""

import asyncio
import json
import logging
import time
from typing import AsyncGenerator, Optional

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.schemas.bedrock import (
    BedrockContentBlock,
    BedrockRequest,
    BedrockResponse,
    BedrockStreamEvent,
    BedrockUsage,
)

logger = logging.getLogger(__name__)


class BedrockClient:
    """AWS Bedrock client using async aioboto3."""

    _instance: Optional["BedrockClient"] = None

    def __init__(self):
        """Initialize Bedrock client with aioboto3 session."""
        import os

        settings = get_settings()

        # Configure with retry logic and connection pooling
        self.config = Config(
            region_name=settings.AWS_REGION,
            retries={"max_attempts": 3, "mode": "adaptive"},
            connect_timeout=60,  # 60 seconds for connection
            read_timeout=1800,  # 30 minutes for long-running tasks
            max_pool_connections=settings.BEDROCK_MAX_CONCURRENT_REQUESTS,
            tcp_keepalive=True,  # Enable TCP keepalive
        )

        # Semaphore to limit concurrent Bedrock requests and provide
        # backpressure instead of queuing against the connection pool
        self._semaphore = asyncio.Semaphore(settings.BEDROCK_MAX_CONCURRENT_REQUESTS)

        # Set AWS profile if configured
        if settings.AWS_PROFILE:
            os.environ["AWS_PROFILE"] = settings.AWS_PROFILE
            logger.info(f"Using AWS profile: {settings.AWS_PROFILE}")

        # Create aioboto3 session
        session_kwargs = {}
        if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
            session_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
            session_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY

        self.session = aioboto3.Session(**session_kwargs)
        self.region_name = settings.AWS_REGION

    @classmethod
    def get_instance(cls) -> "BedrockClient":
        """Get the singleton BedrockClient instance. Created on first call."""
        if cls._instance is None:
            cls._instance = cls()
            logger.info("BedrockClient singleton initialized")
        return cls._instance

    # Models that require cross-region inference profile
    # These models don't support direct on-demand invocation
    CROSS_REGION_MODEL_PREFIXES = (
        "amazon.nova-",
        "anthropic.claude-haiku-4",
        "anthropic.claude-sonnet-4",
        "anthropic.claude-opus-4",
        "anthropic.claude-3-5-haiku",
        "anthropic.claude-3-5-sonnet-v2",
    )

    # Valid cross-region inference profile prefixes
    INFERENCE_PROFILE_PREFIXES = ("global.", "us.", "eu.", "apac.", "au.", "ca.", "jp.")

    # Prefixes that identify Anthropic models (base or with inference profile)
    ANTHROPIC_BASE_PREFIX = "anthropic."

    @classmethod
    def is_anthropic_model(cls, model_id: str) -> bool:
        """Return True if *model_id* refers to an Anthropic model.

        Handles both bare IDs (``anthropic.claude-...``) and inference-profile
        IDs (``us.anthropic.claude-...``).
        """
        # Strip optional inference-profile geo prefix
        base = model_id
        for prefix in cls.INFERENCE_PROFILE_PREFIXES:
            if model_id.startswith(prefix):
                base = model_id[len(prefix) :]
                break
        return base.startswith(cls.ANTHROPIC_BASE_PREFIX)

    # Map AWS region prefix to geographic inference profile prefix
    REGION_TO_GEO_PREFIX = {
        "us": "us",
        "eu": "eu",
        "ap": "apac",
        "ca": "ca",
        "me": "eu",  # Middle East uses EU prefix
        "af": "eu",  # Africa uses EU prefix
        "sa": "us",  # South America uses US prefix
    }

    @classmethod
    def is_cross_region_model(cls, base_model_id: str) -> bool:
        """Check if a base model ID requires cross-region inference profile."""
        return any(base_model_id.startswith(p) for p in cls.CROSS_REGION_MODEL_PREFIXES)

    @classmethod
    def get_geo_prefix(cls, aws_region: str) -> str:
        """
        Get the geographic inference profile prefix for an AWS region.

        Examples:
            us-west-2 → "us"
            eu-central-1 → "eu"
            ap-northeast-1 → "apac"

        Args:
            aws_region: AWS region code (e.g., "us-west-2")

        Returns:
            Geographic prefix (e.g., "us")
        """
        region_prefix = aws_region.split("-")[0]
        return cls.REGION_TO_GEO_PREFIX.get(region_prefix, "us")

    def get_model_id(self, model_name: str) -> str:
        """
        Get Bedrock model ID from model name.

        The model_name stored in the database is already a valid Bedrock
        model ID (with geographic prefix for cross-region models, e.g.
        "us.amazon.nova-pro-v1:0"), so it is passed through as-is.

        Args:
            model_name: Bedrock model ID, with or without inference profile prefix

        Returns:
            Bedrock model ID (passed through unchanged)
        """
        return model_name

    @staticmethod
    def _build_anthropic_body(request: BedrockRequest) -> dict:
        """
        Build an Anthropic Messages API request body from a BedrockRequest.

        This body is sent as JSON to invoke_model / invoke_model_with_response_stream.
        """
        from app.schemas.bedrock import BedrockContentPart

        # --- messages ---
        messages = []
        for msg in request.messages:
            if isinstance(msg.content, str):
                messages.append({"role": msg.role, "content": msg.content})
            elif isinstance(msg.content, list):
                parts = []
                for part in msg.content:
                    if isinstance(part, BedrockContentPart):
                        parts.append(part.model_dump(exclude_none=True))
                    else:
                        parts.append(part)
                messages.append({"role": msg.role, "content": parts})

        body: dict = {
            "anthropic_version": request.anthropic_version,
            "max_tokens": request.max_tokens,
            "messages": messages,
        }

        # --- optional scalar fields ---
        if request.system:
            body["system"] = request.system
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.top_p is not None:
            body["top_p"] = request.top_p
        if request.stop_sequences:
            body["stop_sequences"] = request.stop_sequences

        # --- tools / tool_choice ---
        if request.tools:
            body["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in request.tools
            ]
        if request.tool_choice:
            body["tool_choice"] = request.tool_choice

        # --- additional_model_request_fields (thinking / effort live here) ---
        if request.additional_model_request_fields:
            body.update(request.additional_model_request_fields)

        # --- prompt caching ---
        if request.prompt_caching:
            body.update(request.prompt_caching)

        # --- effort parameter: requires beta flag + output_config wrapper ---
        # Users may pass "effort" as a top-level field (via additional_model_request_fields).
        # Bedrock invoke_model expects it inside "output_config" with a beta flag.
        if "effort" in body:
            effort_value = body.pop("effort")
            # Wrap in output_config
            output_config = body.get("output_config", {})
            output_config["effort"] = effort_value
            body["output_config"] = output_config
            # Ensure the beta flag is present
            beta_flags = body.get("anthropic_beta", [])
            effort_beta = "effort-2025-11-24"
            if effort_beta not in beta_flags:
                beta_flags.append(effort_beta)
            body["anthropic_beta"] = beta_flags
            logger.info(
                f"Effort parameter '{effort_value}' wrapped in output_config with beta flag"
            )

        # --- auto-fix max_tokens vs thinking.budget_tokens constraint ---
        # Anthropic requires max_tokens > thinking.budget_tokens.
        thinking_cfg = body.get("thinking")
        if isinstance(thinking_cfg, dict) and "budget_tokens" in thinking_cfg:
            budget = thinking_cfg["budget_tokens"]
            if body["max_tokens"] <= budget:
                new_max = budget + body["max_tokens"]
                logger.info(
                    f"Adjusting max_tokens from {body['max_tokens']} to {new_max} "
                    f"(must be > thinking.budget_tokens={budget})"
                )
                body["max_tokens"] = new_max

        # --- fields not supported by invoke_model — warn and skip ---
        if request.prompt_variables:
            logger.warning(
                "prompt_variables is not supported by invoke_model; ignoring"
            )
        if request.request_metadata:
            logger.warning(
                "request_metadata is not supported by invoke_model; ignoring"
            )
        if request.additional_model_response_field_paths:
            logger.warning(
                "additional_model_response_field_paths is not supported by invoke_model; ignoring"
            )

        return body

    @staticmethod
    def _build_invoke_kwargs(request: BedrockRequest, model_id: str) -> dict:
        """
        Build the top-level keyword arguments for invoke_model /
        invoke_model_with_response_stream (everything except ``body``).
        """
        kwargs: dict = {
            "modelId": model_id,
            "contentType": "application/json",
            "accept": "application/json",
        }

        # Guardrail config → top-level parameters
        if request.guardrail_config:
            gc = request.guardrail_config
            if "guardrailIdentifier" in gc:
                kwargs["guardrailIdentifier"] = gc["guardrailIdentifier"]
            if "guardrailVersion" in gc:
                kwargs["guardrailVersion"] = gc["guardrailVersion"]

        # Trace (invoke_model supports it as a top-level parameter)
        if request.trace:
            kwargs["trace"] = request.trace

        # Performance config
        if request.performance_config:
            kwargs["performanceConfig"] = request.performance_config

        return kwargs

    # ------------------------------------------------------------------
    # Converse API helpers (non-Anthropic models)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_converse_params(request: BedrockRequest, model_id: str) -> dict:
        """Build parameters for the Converse / ConverseStream API.

        Converts the internal ``BedrockRequest`` (which uses Anthropic-style
        field names) into the structure expected by
        ``bedrock-runtime.converse()`` / ``converse_stream()``.
        """
        from app.schemas.bedrock import BedrockContentPart
        import base64

        # --- messages ---
        messages = []
        for msg in request.messages:
            converse_content: list[dict] = []

            if isinstance(msg.content, str):
                converse_content.append({"text": msg.content})
            elif isinstance(msg.content, list):
                for part in msg.content:
                    if isinstance(part, BedrockContentPart):
                        part_dict = part.model_dump(exclude_none=True)
                    else:
                        part_dict = part

                    ptype = part_dict.get("type")

                    if ptype == "text":
                        converse_content.append({"text": part_dict.get("text", "")})

                    elif ptype == "image":
                        # Anthropic format: source.type="base64", source.media_type, source.data
                        source = part_dict.get("source", {})
                        media_type = source.get("media_type", "image/jpeg")
                        # Converse wants format without the "image/" prefix
                        fmt = media_type.split("/")[-1]  # e.g. "jpeg", "png"
                        raw_bytes = base64.b64decode(source.get("data", ""))
                        converse_content.append(
                            {
                                "image": {
                                    "format": fmt,
                                    "source": {"bytes": raw_bytes},
                                }
                            }
                        )

                    elif ptype == "tool_use":
                        converse_content.append(
                            {
                                "toolUse": {
                                    "toolUseId": part_dict.get("id", ""),
                                    "name": part_dict.get("name", ""),
                                    "input": part_dict.get("input", {}),
                                }
                            }
                        )

                    elif ptype == "tool_result":
                        result_content = []
                        text_val = part_dict.get("content")
                        if text_val:
                            result_content.append({"text": text_val})
                        converse_content.append(
                            {
                                "toolResult": {
                                    "toolUseId": part_dict.get("tool_use_id", ""),
                                    "content": result_content,
                                }
                            }
                        )

            messages.append({"role": msg.role, "content": converse_content})

        params: dict = {
            "modelId": model_id,
            "messages": messages,
        }

        # --- system ---
        if request.system:
            params["system"] = [{"text": request.system}]

        # --- inferenceConfig ---
        inference_config: dict = {"maxTokens": request.max_tokens}
        if request.temperature is not None:
            inference_config["temperature"] = request.temperature
        if request.top_p is not None:
            inference_config["topP"] = request.top_p
        if request.stop_sequences:
            inference_config["stopSequences"] = request.stop_sequences
        params["inferenceConfig"] = inference_config

        # --- toolConfig ---
        if request.tools:
            tool_specs = []
            for t in request.tools:
                tool_specs.append(
                    {
                        "toolSpec": {
                            "name": t.name,
                            "description": t.description,
                            "inputSchema": {"json": t.input_schema},
                        }
                    }
                )
            tool_config: dict = {"tools": tool_specs}

            # tool_choice mapping (already in Anthropic-style dict from translator)
            if request.tool_choice:
                tc_type = request.tool_choice.get("type")
                if tc_type == "auto":
                    tool_config["toolChoice"] = {"auto": {}}
                elif tc_type == "any":
                    tool_config["toolChoice"] = {"any": {}}
                elif tc_type == "tool":
                    tool_config["toolChoice"] = {
                        "tool": {"name": request.tool_choice.get("name", "")}
                    }

            params["toolConfig"] = tool_config

        # --- guardrail ---
        if request.guardrail_config:
            gc = request.guardrail_config
            guardrail: dict = {}
            if "guardrailIdentifier" in gc:
                guardrail["guardrailIdentifier"] = gc["guardrailIdentifier"]
            if "guardrailVersion" in gc:
                guardrail["guardrailVersion"] = gc["guardrailVersion"]
            if guardrail:
                params["guardrailConfig"] = guardrail

        # --- additional model request fields (pass-through) ---
        if request.additional_model_request_fields:
            params["additionalModelRequestFields"] = (
                request.additional_model_request_fields
            )

        # --- performance config ---
        if request.performance_config:
            params["performanceConfig"] = request.performance_config

        return params

    def _parse_converse_response(
        self, response: dict, model_name: str
    ) -> BedrockResponse:
        """Convert a Converse API response dict into a ``BedrockResponse``."""
        output = response.get("output", {})
        message = output.get("message", {})
        content_list = message.get("content", [])

        content_blocks: list[BedrockContentBlock] = []
        for item in content_list:
            if "text" in item:
                content_blocks.append(
                    BedrockContentBlock(type="text", text=item["text"])
                )
            elif "toolUse" in item:
                tu = item["toolUse"]
                content_blocks.append(
                    BedrockContentBlock(
                        type="tool_use",
                        id=tu.get("toolUseId"),
                        name=tu.get("name"),
                        input=tu.get("input"),
                    )
                )

        usage_data = response.get("usage", {})
        usage = BedrockUsage(
            input_tokens=usage_data.get("inputTokens", 0),
            output_tokens=usage_data.get("outputTokens", 0),
        )

        stop_reason_raw = response.get("stopReason", "end_turn")
        # Converse uses "end_turn", "tool_use", "max_tokens", "stop_sequence"
        # which aligns with our internal format already.

        return BedrockResponse(
            id=response.get("ResponseMetadata", {}).get("RequestId", ""),
            type="message",
            role="assistant",
            content=content_blocks,
            model=model_name,
            stop_reason=stop_reason_raw,
            usage=usage,
        )

    @staticmethod
    def _converse_stream_event_to_bedrock(
        event: dict,
    ) -> Optional[BedrockStreamEvent]:
        """Convert a Converse Stream event into a ``BedrockStreamEvent``.

        The Converse stream yields dicts with exactly one key per event:
        ``messageStart``, ``contentBlockStart``, ``contentBlockDelta``,
        ``contentBlockStop``, ``messageStop``, ``metadata``.
        """
        if "messageStart" in event:
            data = event["messageStart"]
            return BedrockStreamEvent(
                type="message_start",
                message={"role": data.get("role", "assistant")},
            )

        if "contentBlockStart" in event:
            data = event["contentBlockStart"]
            index = data.get("contentBlockIndex", 0)
            start = data.get("start", {})

            if "toolUse" in start:
                tu = start["toolUse"]
                return BedrockStreamEvent(
                    type="content_block_start",
                    index=index,
                    content_block={
                        "type": "tool_use",
                        "id": tu.get("toolUseId", ""),
                        "name": tu.get("name", ""),
                    },
                )
            else:
                return BedrockStreamEvent(
                    type="content_block_start",
                    index=index,
                    content_block={"type": "text"},
                )

        if "contentBlockDelta" in event:
            data = event["contentBlockDelta"]
            index = data.get("contentBlockIndex", 0)
            delta = data.get("delta", {})

            if "text" in delta:
                return BedrockStreamEvent(
                    type="content_block_delta",
                    index=index,
                    delta={"text": delta["text"]},
                )
            elif "toolUse" in delta:
                return BedrockStreamEvent(
                    type="content_block_delta",
                    index=index,
                    delta={"partial_json": delta["toolUse"].get("input", "")},
                )

        if "contentBlockStop" in event:
            data = event["contentBlockStop"]
            return BedrockStreamEvent(
                type="content_block_stop",
                index=data.get("contentBlockIndex", 0),
            )

        if "messageStop" in event:
            data = event["messageStop"]
            return BedrockStreamEvent(
                type="message_delta",
                delta={"stop_reason": data.get("stopReason", "end_turn")},
            )

        if "metadata" in event:
            meta = event["metadata"]
            usage_data = meta.get("usage", {})
            return BedrockStreamEvent(
                type="message_delta",
                usage=BedrockUsage(
                    input_tokens=usage_data.get("inputTokens", 0),
                    output_tokens=usage_data.get("outputTokens", 0),
                ),
            )

        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def invoke(self, model_name: str, request: BedrockRequest) -> BedrockResponse:
        """
        Invoke Bedrock model with retry logic (async).

        Args:
            model_name: Model name
            request: Bedrock request

        Returns:
            Bedrock response

        Raises:
            Exception: If all retries fail
        """
        async with self._semaphore:
            return await self._invoke_inner(model_name, request)

    async def _invoke_inner(
        self, model_name: str, request: BedrockRequest
    ) -> BedrockResponse:
        """Inner invoke logic with retry, called under semaphore."""
        model_id = self.get_model_id(model_name)
        use_converse = not self.is_anthropic_model(model_id)

        if use_converse:
            converse_params = self._build_converse_params(request, model_id)
            logger.info(
                "Using Converse API for non-Anthropic model",
                extra={"model": model_name, "model_id": model_id},
            )
        else:
            body = self._build_anthropic_body(request)
            invoke_kwargs = self._build_invoke_kwargs(request, model_id)

        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries):
            try:
                start_time = time.time()

                async with self.session.client(
                    "bedrock-runtime",
                    region_name=self.region_name,
                    config=self.config,
                ) as client:
                    if use_converse:
                        response = await client.converse(**converse_params)
                        duration = time.time() - start_time
                        bedrock_response = self._parse_converse_response(
                            response, model_name
                        )
                    else:
                        response = await client.invoke_model(
                            body=json.dumps(body), **invoke_kwargs
                        )
                        duration = time.time() - start_time

                        # Parse Anthropic Messages API response
                        response_body = json.loads(await response["body"].read())

                        # Build content blocks
                        content_blocks = []
                        for item in response_body.get("content", []):
                            block_type = item.get("type")
                            if block_type == "text":
                                content_blocks.append(
                                    BedrockContentBlock(type="text", text=item["text"])
                                )
                            elif block_type == "tool_use":
                                content_blocks.append(
                                    BedrockContentBlock(
                                        type="tool_use",
                                        id=item.get("id"),
                                        name=item.get("name"),
                                        input=item.get("input"),
                                    )
                                )
                            elif block_type == "thinking":
                                logger.debug(
                                    "Skipping thinking content block in non-streaming response"
                                )
                                content_blocks.append(
                                    BedrockContentBlock(type="thinking")
                                )

                        # Usage — Anthropic format uses snake_case
                        usage_data = response_body.get("usage", {})
                        usage = BedrockUsage(
                            input_tokens=usage_data.get("input_tokens", 0),
                            output_tokens=usage_data.get("output_tokens", 0),
                        )

                        bedrock_response = BedrockResponse(
                            id=response_body.get("id", ""),
                            type="message",
                            role="assistant",
                            content=content_blocks,
                            model=model_name,
                            stop_reason=response_body.get("stop_reason", "end_turn"),
                            usage=usage,
                        )

                    logger.info(
                        "Bedrock invocation successful",
                        extra={
                            "model": model_name,
                            "model_id": model_id,
                            "api": "converse" if use_converse else "invoke_model",
                            "attempt": attempt + 1,
                            "duration_seconds": round(duration, 3),
                            "input_tokens": bedrock_response.usage.input_tokens,
                            "output_tokens": bedrock_response.usage.output_tokens,
                        },
                    )

                    return bedrock_response

            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "Unknown")
                error_message = e.response.get("Error", {}).get("Message", str(e))

                logger.warning(
                    f"Bedrock invocation failed (attempt {attempt + 1}/{max_retries})",
                    extra={
                        "model": model_name,
                        "error_code": error_code,
                        "error_message": error_message,
                    },
                )

                # Don't retry on client errors (4xx)
                if error_code in [
                    "ValidationException",
                    "AccessDeniedException",
                    "ThrottlingException",
                ]:
                    raise

                # Retry on server errors (5xx) with exponential backoff
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    import random

                    delay = delay * (0.5 + random.random())
                    logger.info(f"Retrying in {delay:.2f} seconds...")
                    await asyncio.sleep(delay)
                else:
                    raise

            except Exception as e:
                logger.error(
                    f"Unexpected error in Bedrock invocation (attempt {attempt + 1}/{max_retries})",
                    extra={"model": model_name, "error": str(e)},
                    exc_info=True,
                )

                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    await asyncio.sleep(delay)
                else:
                    raise

    async def invoke_stream(
        self, model_name: str, request: BedrockRequest
    ) -> AsyncGenerator[BedrockStreamEvent, None]:
        """
        Invoke Bedrock model with streaming via invoke_model_with_response_stream.

        Sends an Anthropic Messages API body directly, so native parameters
        like thinking / effort are supported without extra mapping.

        Retry logic only applies to errors BEFORE streaming starts.
        The semaphore is held for the entire duration of the stream.

        Args:
            model_name: Model name
            request: Bedrock request

        Yields:
            BedrockStreamEvent instances
        """
        async with self._semaphore:
            async for event in self._invoke_stream_inner(model_name, request):
                yield event

    async def _invoke_stream_inner(
        self, model_name: str, request: BedrockRequest
    ) -> AsyncGenerator[BedrockStreamEvent, None]:
        """Inner streaming logic with retry, called under semaphore."""
        model_id = self.get_model_id(model_name)
        use_converse = not self.is_anthropic_model(model_id)

        if use_converse:
            converse_params = self._build_converse_params(request, model_id)
            logger.info(
                "Using ConverseStream API for non-Anthropic model",
                extra={"model": model_name, "model_id": model_id},
            )
        else:
            body = self._build_anthropic_body(request)
            invoke_kwargs = self._build_invoke_kwargs(request, model_id)

        max_retries = 4
        base_delay = 1.0
        stream_started = False

        for attempt in range(max_retries):
            try:
                start_time = time.time()

                async with self.session.client(
                    "bedrock-runtime",
                    region_name=self.region_name,
                    config=self.config,
                ) as client:
                    if use_converse:
                        response = await client.converse_stream(**converse_params)
                    else:
                        response = await client.invoke_model_with_response_stream(
                            body=json.dumps(body), **invoke_kwargs
                        )

                    logger.info(
                        "Bedrock streaming started",
                        extra={
                            "model": model_name,
                            "model_id": model_id,
                            "api": "converse_stream"
                            if use_converse
                            else "invoke_model_stream",
                            "attempt": attempt + 1,
                        },
                    )

                    event_count = 0

                    if use_converse:
                        async for event in response["stream"]:
                            stream_started = True
                            bedrock_event = self._converse_stream_event_to_bedrock(
                                event
                            )
                            if bedrock_event:
                                yield bedrock_event
                                event_count += 1
                    else:
                        async for event in response["body"]:
                            stream_started = True
                            chunk_bytes = event.get("chunk", {}).get("bytes")
                            if not chunk_bytes:
                                continue

                            anthropic_event = json.loads(chunk_bytes)
                            bedrock_event = self._anthropic_event_to_bedrock(
                                anthropic_event
                            )
                            if bedrock_event:
                                yield bedrock_event
                                event_count += 1

                    duration = time.time() - start_time
                    logger.info(
                        "Bedrock streaming completed",
                        extra={
                            "model": model_name,
                            "duration_seconds": round(duration, 3),
                            "events_processed": event_count,
                        },
                    )

                    # Success — exit retry loop
                    return

            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "Unknown")
                error_message = e.response.get("Error", {}).get("Message", str(e))

                if stream_started:
                    logger.error(
                        "Stream failed mid-stream, cannot retry",
                        extra={
                            "model": model_name,
                            "error_code": error_code,
                            "error_message": error_message,
                        },
                    )
                    raise

                logger.warning(
                    f"Bedrock streaming failed before stream started (attempt {attempt + 1}/{max_retries})",
                    extra={
                        "model": model_name,
                        "error_code": error_code,
                        "error_message": error_message,
                    },
                )

                if error_code in ["ValidationException", "AccessDeniedException"]:
                    raise

                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    import random

                    delay = delay * (0.5 + random.random())
                    logger.info(f"Retrying streaming in {delay:.2f} seconds...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Bedrock streaming failed after all retries",
                        extra={"model": model_name, "error_code": error_code},
                    )
                    raise

            except Exception as e:
                if stream_started:
                    logger.error(
                        "Stream failed mid-stream, cannot retry",
                        extra={"model": model_name, "error": str(e)},
                        exc_info=True,
                    )
                    raise

                logger.error(
                    f"Unexpected error in Bedrock streaming before stream started (attempt {attempt + 1}/{max_retries})",
                    extra={"model": model_name, "error": str(e)},
                    exc_info=True,
                )

                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    import random

                    delay = delay * (0.5 + random.random())
                    logger.info(f"Retrying streaming in {delay:.2f} seconds...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Bedrock streaming failed after all retries",
                        extra={"model": model_name},
                    )
                    raise

    @staticmethod
    def _anthropic_event_to_bedrock(
        event: dict,
    ) -> Optional[BedrockStreamEvent]:
        """
        Convert an Anthropic Messages API streaming event to BedrockStreamEvent.

        Args:
            event: Parsed JSON event from invoke_model_with_response_stream

        Returns:
            BedrockStreamEvent or None if the event should be skipped
        """
        event_type = event.get("type")

        if event_type == "message_start":
            message = event.get("message", {})
            usage_data = message.get("usage", {})
            return BedrockStreamEvent(
                type="message_start",
                message={"role": message.get("role", "assistant")},
                usage=BedrockUsage(
                    input_tokens=usage_data.get("input_tokens", 0),
                    output_tokens=0,
                ),
            )

        elif event_type == "content_block_start":
            index = event.get("index", 0)
            content_block = event.get("content_block", {})
            block_type = content_block.get("type", "text")

            if block_type == "tool_use":
                return BedrockStreamEvent(
                    type="content_block_start",
                    index=index,
                    content_block={
                        "type": "tool_use",
                        "id": content_block.get("id", ""),
                        "name": content_block.get("name", ""),
                    },
                )
            elif block_type == "thinking":
                return BedrockStreamEvent(
                    type="content_block_start",
                    index=index,
                    content_block={"type": "thinking"},
                )
            else:
                return BedrockStreamEvent(
                    type="content_block_start",
                    index=index,
                    content_block={"type": "text"},
                )

        elif event_type == "content_block_delta":
            index = event.get("index", 0)
            delta = event.get("delta", {})
            delta_type = delta.get("type")

            if delta_type == "text_delta":
                return BedrockStreamEvent(
                    type="content_block_delta",
                    index=index,
                    delta={"text": delta.get("text", "")},
                )
            elif delta_type == "input_json_delta":
                return BedrockStreamEvent(
                    type="content_block_delta",
                    index=index,
                    delta={"partial_json": delta.get("partial_json", "")},
                )
            elif delta_type == "thinking_delta":
                return BedrockStreamEvent(
                    type="content_block_delta",
                    index=index,
                    delta={"thinking": delta.get("thinking", "")},
                )

        elif event_type == "content_block_stop":
            return BedrockStreamEvent(
                type="content_block_stop",
                index=event.get("index", 0),
            )

        elif event_type == "message_delta":
            delta = event.get("delta", {})
            usage_data = event.get("usage", {})
            return BedrockStreamEvent(
                type="message_delta",
                delta={"stop_reason": delta.get("stop_reason", "end_turn")},
                usage=BedrockUsage(
                    input_tokens=0,
                    output_tokens=usage_data.get("output_tokens", 0),
                ),
            )

        elif event_type == "message_stop":
            return BedrockStreamEvent(
                type="message_stop",
            )

        # ping / unknown → skip
        return None

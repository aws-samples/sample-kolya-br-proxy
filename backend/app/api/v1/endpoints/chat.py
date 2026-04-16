"""
OpenAI-compatible chat completions endpoint.
"""

import logging
import time
import uuid
from typing import AsyncGenerator

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

import httpx

from app.api.deps import get_current_token
from app.core.config import get_settings
from app.core.database import get_db
from app.models.token import APIToken
from app.models.usage import UsageRecord
from app.schemas.openai import (
    ChatCompletionRequest,
    ErrorDetail,
    ErrorResponse,
)
from app.services.background_tasks import BackgroundTaskManager
from app.services.bedrock import BedrockClient, get_fallback_models
from app.services.gemini_client import (
    GeminiClient,
    is_gemini_model as _is_gemini_model,
    extract_cached_tokens,
    extract_cached_tokens_from_chunk,
)
from app.core.metrics import emit_request_metrics
from app.services.pricing import ModelPricing
from app.services.translator import RequestTranslator, ResponseTranslator

router = APIRouter()
logger = logging.getLogger(__name__)
background_tasks = BackgroundTaskManager()


@router.post("/chat/completions")
async def create_chat_completion(
    request_data: ChatCompletionRequest,
    http_request: Request,
    token: APIToken = Depends(get_current_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a chat completion (OpenAI compatible).

    This endpoint accepts OpenAI-format requests and proxies them to AWS Bedrock.
    Supports Bedrock-specific parameters via:
    - Request body fields with bedrock_* prefix
    - Request headers with X-Bedrock-* prefix
    """
    request_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    start_time = time.time()

    # Extract Bedrock-specific parameters from headers (X-Bedrock-* headers)
    # Headers override request body if both are present
    import json

    # Special handling for guardrail headers (combine into guardrail_config)
    guardrail_id = http_request.headers.get("x-bedrock-guardrail-id")
    guardrail_version = http_request.headers.get("x-bedrock-guardrail-version")
    if guardrail_id:
        guardrail_config = {"guardrailIdentifier": guardrail_id}
        if guardrail_version:
            guardrail_config["guardrailVersion"] = guardrail_version
        request_data.bedrock_guardrail_config = guardrail_config
        logger.info(f"Applied guardrail config from headers: {guardrail_config}")

    # Process other Bedrock headers
    for header_name, header_value in http_request.headers.items():
        header_lower = header_name.lower()
        if header_lower.startswith("x-bedrock-"):
            # Skip guardrail headers (already processed)
            if header_lower in [
                "x-bedrock-guardrail-id",
                "x-bedrock-guardrail-version",
            ]:
                continue

            # Map header name to schema field name
            if header_lower == "x-bedrock-trace":
                param_name = "bedrock_trace"
                setattr(request_data, param_name, header_value)
                logger.info(f"Applied Bedrock trace from header: {header_value}")
            elif header_lower == "x-bedrock-additional-fields":
                # Parse JSON for additional fields
                try:
                    parsed_value = json.loads(header_value)
                    request_data.bedrock_additional_model_request_fields = parsed_value
                    logger.info(
                        f"Applied additional model request fields from header: {parsed_value}"
                    )
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Failed to parse X-Bedrock-Additional-Fields as JSON: {e}"
                    )
            elif header_lower == "x-bedrock-performance-config":
                # Parse JSON for performance config
                try:
                    parsed_value = json.loads(header_value)
                    request_data.bedrock_performance_config = parsed_value
                    logger.info(
                        f"Applied performance config from header: {parsed_value}"
                    )
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Failed to parse X-Bedrock-Performance-Config as JSON: {e}"
                    )
            elif header_lower == "x-bedrock-prompt-caching":
                # Parse JSON for prompt caching
                try:
                    parsed_value = json.loads(header_value)
                    request_data.bedrock_prompt_caching = parsed_value
                    logger.info(f"Applied prompt caching from header: {parsed_value}")
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Failed to parse X-Bedrock-Prompt-Caching as JSON: {e}"
                    )
            elif header_lower == "x-bedrock-prompt-variables":
                try:
                    parsed_value = json.loads(header_value)
                    request_data.bedrock_prompt_variables = parsed_value
                    logger.info(f"Applied prompt variables from header: {parsed_value}")
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Failed to parse X-Bedrock-Prompt-Variables as JSON: {e}"
                    )
            elif header_lower == "x-bedrock-response-field-paths":
                try:
                    parsed_value = json.loads(header_value)
                    request_data.bedrock_additional_model_response_field_paths = (
                        parsed_value
                    )
                    logger.info(
                        f"Applied response field paths from header: {parsed_value}"
                    )
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Failed to parse X-Bedrock-Response-Field-Paths as JSON: {e}"
                    )
            elif header_lower == "x-bedrock-auto-cache":
                request_data.bedrock_auto_cache = header_value.lower() in (
                    "true",
                    "1",
                    "yes",
                )
            elif header_lower == "x-bedrock-request-metadata":
                try:
                    parsed_value = json.loads(header_value)
                    request_data.bedrock_request_metadata = parsed_value
                    logger.info(f"Applied request metadata from header: {parsed_value}")
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Failed to parse X-Bedrock-Request-Metadata as JSON: {e}"
                    )

    # Apply token-level prompt cache settings (lower priority than request-level)
    if token.token_metadata:
        meta = token.token_metadata
        if request_data.bedrock_auto_cache is None and "prompt_cache_enabled" in meta:
            request_data.bedrock_auto_cache = meta["prompt_cache_enabled"]
        if request_data.bedrock_cache_ttl is None and "prompt_cache_ttl" in meta:
            request_data.bedrock_cache_ttl = meta["prompt_cache_ttl"]

    # Log request with full details for debugging
    logger.info(
        f"Chat completion request received: model={request_data.model}, "
        f"messages={len(request_data.messages)}, stream={request_data.stream}, "
        f"request_id={request_id}, token_id={token.id}",
    )
    logger.debug(f"Full request data: {request_data.model_dump()}")

    try:
        # Check token quota before processing request
        from sqlalchemy import select, func
        from app.models.model import Model
        from decimal import Decimal

        # Calculate total usage for this token
        result = await db.execute(
            select(func.sum(UsageRecord.cost_usd)).where(
                UsageRecord.token_id == token.id
            )
        )
        total_used = result.scalar() or Decimal("0.00")

        # Set cached used amount for quota check
        token.calculate_used_usd(total_used)

        # Check if quota is exceeded
        if token.is_quota_exceeded:
            raise HTTPException(
                status_code=429,
                detail=f"Token quota exceeded. Used: ${total_used:.2f}, Quota: ${token.quota_usd:.2f}",
            )

        # Validate model access by querying the models table
        result = await db.execute(
            select(Model).where(
                Model.token_id == token.id,
                Model.is_active,
                ~Model.is_deleted,
            )
        )
        token_models = result.scalars().all()

        allowed_model_names = [model.model_name for model in token_models]

        # If no models are associated with this token, deny all access
        if not allowed_model_names:
            raise HTTPException(
                status_code=403,
                detail="Token does not have access to any models",
            )

        # Check if requested model matches any allowed model (exact match)
        if request_data.model not in allowed_model_names:
            raise HTTPException(
                status_code=403,
                detail=f"Token does not have access to model: {request_data.model}. Allowed models: {allowed_model_names}",
            )

        # Route Gemini models to Google API directly
        if _is_gemini_model(request_data.model):
            return await _handle_gemini_request(
                request_data=request_data,
                request_id=request_id,
                token=token,
                start_time=start_time,
            )

        # Get singleton Bedrock client
        bedrock_client = BedrockClient.get_instance()

        # Translate request
        bedrock_request = RequestTranslator.openai_to_bedrock(request_data)

        # Handle streaming
        if request_data.stream:
            return StreamingResponse(
                stream_chat_completion(
                    request_id=request_id,
                    model=request_data.model,
                    bedrock_request=bedrock_request,
                    bedrock_client=bedrock_client,
                    token=token,
                    db=db,
                    start_time=start_time,
                    http_request=http_request,
                    cache_ttl=request_data.bedrock_cache_ttl
                    or get_settings().PROMPT_CACHE_TTL,
                    allowed_model_names=allowed_model_names,
                ),
                media_type="text/event-stream",
            )

        # Non-streaming response
        bedrock_response = await bedrock_client.invoke(
            request_data.model, bedrock_request
        )

        # Translate response
        openai_response = ResponseTranslator.bedrock_to_openai(
            bedrock_response, request_data.model, request_id
        )

        # Extract cache token counts from bedrock response
        cache_creation_tokens = bedrock_response.usage.cache_creation_input_tokens or 0
        cache_read_tokens = bedrock_response.usage.cache_read_input_tokens or 0

        # Determine effective cache TTL for pricing
        effective_cache_ttl = (
            request_data.bedrock_cache_ttl or get_settings().PROMPT_CACHE_TTL
        )

        # Record usage asynchronously (don't block response)
        background_tasks.create_task(
            record_usage(
                token_id=token.id,
                user_id=token.user_id,
                model=request_data.model,
                request_id=request_id,
                prompt_tokens=openai_response.usage.prompt_tokens,
                completion_tokens=openai_response.usage.completion_tokens,
                cache_creation_input_tokens=cache_creation_tokens,
                cache_read_input_tokens=cache_read_tokens,
                cache_ttl=effective_cache_ttl if cache_creation_tokens else None,
            ),
            task_name=f"record_usage_{request_id}",
        )

        duration = time.time() - start_time
        cache_info = ""
        if cache_creation_tokens:
            cache_info += f", cache_write={cache_creation_tokens}"
        if cache_read_tokens:
            cache_info += f", cache_read={cache_read_tokens}"
        logger.info(
            f"Chat completion successful: request_id={request_id}, "
            f"duration={round(duration, 3)}s, "
            f"prompt={openai_response.usage.prompt_tokens}, "
            f"completion={openai_response.usage.completion_tokens}"
            f"{cache_info}"
        )

        await emit_request_metrics(
            endpoint="/v1/chat/completions",
            model=request_data.model,
            duration_s=round(duration, 3),
            input_tokens=openai_response.usage.prompt_tokens,
            output_tokens=openai_response.usage.completion_tokens,
            status_code=200,
            is_streaming=False,
            cache_write_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
        )

        return openai_response

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(
            "Invalid request",
            extra={
                "request_id": request_id,
                "error": str(e),
                "model": request_data.model,
            },
            exc_info=True,
        )
        raise HTTPException(status_code=400, detail=str(e))
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        error_message = e.response.get("Error", {}).get("Message", str(e))
        logger.error(
            f"Bedrock error: model={request_data.model}, request_id={request_id}, "
            f"code={error_code}, message={error_message}",
        )
        status_map = {
            "ValidationException": 400,
            "AccessDeniedException": 403,
            "ThrottlingException": 429,
            "ModelNotReadyException": 503,
            "ServiceUnavailableException": 503,
        }
        status_code = status_map.get(error_code, 502)
        raise HTTPException(
            status_code=status_code,
            detail=error_message,
        )
    except Exception as e:
        logger.error(
            f"Chat completion failed: model={request_data.model}, request_id={request_id}, error={e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error processing chat completion",
        )


async def _handle_gemini_request(
    request_data: ChatCompletionRequest,
    request_id: str,
    token: APIToken,
    start_time: float,
):
    """
    Forward a chat completion request to Google Gemini native API.

    Converts OpenAI-format payload to Gemini GenerateContentRequest internally;
    all bedrock_* and OpenAI-only fields are ignored by the converter.
    """
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Gemini API key is not configured on this server",
        )

    # Pass the full payload — GeminiClient.invoke / invoke_stream only reads
    # the fields it understands (model, messages, temperature, etc.).
    payload = request_data.model_dump(exclude_none=True)

    if request_data.stream:
        return StreamingResponse(
            stream_gemini_completion(
                payload=payload,
                api_key=settings.GEMINI_API_KEY,
                request_id=request_id,
                model=request_data.model,
                token=token,
                start_time=start_time,
            ),
            media_type="text/event-stream",
        )

    # Non-streaming
    try:
        response_data = await GeminiClient.invoke(payload, settings.GEMINI_API_KEY)
    except httpx.HTTPStatusError as e:
        logger.error(f"Gemini API error: {e}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Gemini API error: {str(e)[:200]}",
        )

    # Extract usage including cached tokens for auto-cache billing
    usage = response_data.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    cached_tokens = extract_cached_tokens(response_data)
    # Gemini reports prompt_tokens as total including cached; adjust to non-cached only
    non_cached_prompt = max(0, prompt_tokens - cached_tokens)

    background_tasks.create_task(
        record_usage(
            token_id=token.id,
            user_id=token.user_id,
            model=request_data.model,
            request_id=request_id,
            prompt_tokens=non_cached_prompt,
            completion_tokens=completion_tokens,
            cache_read_input_tokens=cached_tokens,
        ),
        task_name=f"record_usage_{request_id}",
    )

    duration = time.time() - start_time
    cache_info = f", cached={cached_tokens}" if cached_tokens else ""
    logger.info(
        f"Gemini completion successful: request_id={request_id}, "
        f"duration={round(duration, 3)}s, "
        f"prompt={non_cached_prompt}, completion={completion_tokens}{cache_info}"
    )

    return response_data


async def stream_gemini_completion(
    payload: dict,
    api_key: str,
    request_id: str,
    model: str,
    token: APIToken,
    start_time: float,
) -> AsyncGenerator[str, None]:
    """
    Stream a Gemini completion via the native streamGenerateContent API.

    GeminiClient.invoke_stream yields OpenAI-format SSE chunks; we forward them
    verbatim and extract usage from any chunk that carries a usage object.
    """
    import json as _json

    settings = get_settings()
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cached_tokens = 0
    last_heartbeat = time.time()

    try:
        async for chunk in GeminiClient.invoke_stream(payload, api_key):
            current_time = time.time()

            # Send heartbeat if idle too long
            if current_time - last_heartbeat > settings.STREAM_HEARTBEAT_INTERVAL:
                yield ": heartbeat\n\n"
                last_heartbeat = current_time

            # Forward OpenAI-format SSE chunk produced by invoke_stream
            yield chunk
            last_heartbeat = current_time

            # Extract usage for billing (appears on the final content chunk)
            for line in chunk.splitlines():
                if line.startswith("data: ") and line.strip() != "data: [DONE]":
                    try:
                        data = _json.loads(line[6:])
                        usage = data.get("usage")
                        if usage:
                            total_prompt_tokens = usage.get(
                                "prompt_tokens", total_prompt_tokens
                            )
                            total_completion_tokens = usage.get(
                                "completion_tokens", total_completion_tokens
                            )
                            cached = extract_cached_tokens_from_chunk(data)
                            if cached is not None:
                                total_cached_tokens = cached
                    except Exception:
                        pass

    except httpx.HTTPStatusError as e:
        logger.error(
            f"Gemini stream error: model={model}, request_id={request_id}, "
            f"status={e.response.status_code}",
            exc_info=True,
        )
        error_response = ErrorResponse(
            error=ErrorDetail(
                message=f"Gemini API error: {str(e)[:200]}",
                type="server_error",
                code=str(e.response.status_code),
            )
        )
        yield f"data: {error_response.model_dump_json()}\n\n"
    except Exception as e:
        logger.error(
            f"Gemini streaming failed: model={model}, request_id={request_id}, error={e}",
            exc_info=True,
        )
        error_response = ErrorResponse(
            error=ErrorDetail(
                message=str(e),
                type="server_error",
                code="internal_error",
            )
        )
        yield f"data: {error_response.model_dump_json()}\n\n"

    # Adjust prompt tokens to exclude cached
    non_cached_prompt = max(0, total_prompt_tokens - total_cached_tokens)

    # Record usage
    background_tasks.create_task(
        record_usage(
            token_id=token.id,
            user_id=token.user_id,
            model=model,
            request_id=request_id,
            prompt_tokens=non_cached_prompt,
            completion_tokens=total_completion_tokens,
            cache_read_input_tokens=total_cached_tokens,
        ),
        task_name=f"record_usage_{request_id}",
    )

    duration = time.time() - start_time
    cache_info = f", cached={total_cached_tokens}" if total_cached_tokens else ""
    logger.info(
        f"Gemini streaming successful: request_id={request_id}, "
        f"duration={round(duration, 3)}s, "
        f"prompt={non_cached_prompt}, completion={total_completion_tokens}{cache_info}"
    )


async def stream_chat_completion(
    request_id: str,
    model: str,
    bedrock_request,
    bedrock_client: BedrockClient,
    token: APIToken,
    db: AsyncSession,
    start_time: float,
    http_request: Request = None,
    cache_ttl: str = None,
    allowed_model_names: list[str] | None = None,
) -> AsyncGenerator[str, None]:
    """
    Stream chat completion responses with heartbeat to keep connection alive.

    Args:
        request_id: Unique request ID
        model: Model name
        bedrock_request: Bedrock format request
        bedrock_client: Bedrock client instance
        token: API token
        db: Database session
        start_time: Request start time
        http_request: Original HTTP request (for disconnect detection)
        cache_ttl: Effective cache TTL for pricing calculation
        allowed_model_names: Token's allowed models (for failover)

    Yields:
        SSE formatted response chunks
    """
    settings = get_settings()
    ttft: float | None = None
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_creation_tokens = 0
    total_cache_read_tokens = 0
    last_heartbeat = time.time()
    client_disconnected = False

    # Track tool use state for streaming
    tool_use_blocks = {}  # {index: {"id": ..., "name": ..., "input": ""}}
    thinking_blocks = set()  # indices of thinking content blocks to skip

    # Compute fallback models for stream failover
    fb_models = get_fallback_models(allowed_model_names or [], model)

    try:
        actual_model_emitted = False
        async for event in bedrock_client.invoke_stream(
            model, bedrock_request, fallback_models=fb_models
        ):
            # Emit x-actual-model SSE comment on Level 2 degradation
            if event.actual_model and not actual_model_emitted:
                yield f": x-actual-model {event.actual_model}\n\n"
                actual_model_emitted = True
            # Check client disconnect (throttled to avoid overhead on every chunk)
            current_time = time.time()
            if http_request and current_time - last_heartbeat > 1.0:
                if await http_request.is_disconnected():
                    client_disconnected = True
                    logger.info(
                        "Client disconnected, stopping Bedrock stream",
                        extra={"request_id": request_id},
                    )
                    break

            # Send heartbeat comment if no data for a while (keeps connection alive)
            if current_time - last_heartbeat > settings.STREAM_HEARTBEAT_INTERVAL:
                try:
                    yield ": heartbeat\n\n"
                except (BrokenPipeError, ConnectionResetError) as conn_err:
                    logger.warning(
                        "Client disconnected during heartbeat",
                        extra={"request_id": request_id, "error": str(conn_err)},
                    )
                    return
                last_heartbeat = current_time

            # Handle different event types
            if event.type == "message_start":
                # Anthropic InvokeModel streams input_tokens in message_start
                if event.usage:
                    total_input_tokens = event.usage.input_tokens or 0
                    total_cache_creation_tokens = (
                        event.usage.cache_creation_input_tokens or 0
                    )
                    total_cache_read_tokens = event.usage.cache_read_input_tokens or 0

            elif event.type == "content_block_start":
                # Track content block start
                if event.index is not None:
                    if event.content_block and event.content_block.type == "thinking":
                        # Skip thinking blocks (not compatible with OpenAI format)
                        thinking_blocks.add(event.index)
                        logger.debug(
                            f"Skipping thinking content block at index {event.index}"
                        )
                        continue
                    if event.content_block and event.content_block.type == "tool_use":
                        # Initialize tool use block
                        tool_use_blocks[event.index] = {
                            "id": event.content_block.id or f"call_{event.index}",
                            "name": event.content_block.name or "",
                            "input": "",
                        }
                        # Send tool call start
                        chunk = ResponseTranslator.create_stream_chunk(
                            request_id=request_id,
                            model=model,
                            tool_calls=[
                                {
                                    "index": event.index,
                                    "id": tool_use_blocks[event.index]["id"],
                                    "type": "function",
                                    "function": {
                                        "name": tool_use_blocks[event.index]["name"],
                                        "arguments": "",
                                    },
                                }
                            ],
                        )
                        yield chunk
                        last_heartbeat = current_time

            elif event.type == "content_block_delta":
                # Skip deltas for thinking blocks
                if event.index is not None and event.index in thinking_blocks:
                    continue
                # Measure time to first content token
                if ttft is None:
                    ttft = time.time() - start_time
                # Stream content delta
                if event.delta and "text" in event.delta:
                    chunk = ResponseTranslator.create_stream_chunk(
                        request_id=request_id,
                        model=model,
                        delta_content=event.delta["text"],
                    )
                    yield chunk
                    last_heartbeat = current_time  # Reset heartbeat on data
                elif event.delta and "partial_json" in event.delta:
                    # Tool use input delta
                    if event.index is not None and event.index in tool_use_blocks:
                        partial_json = event.delta["partial_json"]
                        tool_use_blocks[event.index]["input"] += partial_json
                        # Send tool call arguments delta
                        chunk = ResponseTranslator.create_stream_chunk(
                            request_id=request_id,
                            model=model,
                            tool_calls=[
                                {
                                    "index": event.index,
                                    "function": {"arguments": partial_json},
                                }
                            ],
                        )
                        yield chunk
                        last_heartbeat = current_time

            elif event.type == "content_block_stop":
                # Content block finished
                if event.index is not None and event.index in thinking_blocks:
                    thinking_blocks.discard(event.index)
                    continue

            elif event.type == "message_delta":
                # Anthropic InvokeModel sends output_tokens in message_delta
                if event.usage:
                    total_output_tokens = event.usage.output_tokens or 0
                # Map stop_reason
                stop_reason = event.delta.get("stop_reason") if event.delta else None
                if stop_reason == "tool_use":
                    stop_reason = "tool_calls"

            elif event.type == "message_stop":
                # Send final chunk with finish reason
                finish_reason = "tool_calls" if tool_use_blocks else "stop"
                chunk = ResponseTranslator.create_stream_chunk(
                    request_id=request_id,
                    model=model,
                    finish_reason=finish_reason,
                )
                yield chunk

        if not client_disconnected:
            # Send usage chunk before done marker (OpenAI spec)
            yield ResponseTranslator.create_stream_usage_chunk(
                request_id=request_id,
                model=model,
                prompt_tokens=total_input_tokens,
                completion_tokens=total_output_tokens,
                cache_creation_input_tokens=total_cache_creation_tokens,
                cache_read_input_tokens=total_cache_read_tokens,
            )

            # Send done marker
            yield ResponseTranslator.create_stream_done()

        # Record usage for tokens already consumed (even if client disconnected)
        background_tasks.create_task(
            record_usage(
                token_id=token.id,
                user_id=token.user_id,
                model=model,
                request_id=request_id,
                prompt_tokens=total_input_tokens,
                completion_tokens=total_output_tokens,
                cache_creation_input_tokens=total_cache_creation_tokens,
                cache_read_input_tokens=total_cache_read_tokens,
                cache_ttl=cache_ttl if total_cache_creation_tokens else None,
            ),
            task_name=f"record_usage_{request_id}",
        )

        duration = time.time() - start_time
        cache_info = ""
        if total_cache_creation_tokens:
            cache_info += f", cache_write={total_cache_creation_tokens}"
        if total_cache_read_tokens:
            cache_info += f", cache_read={total_cache_read_tokens}"
        status = (
            "aborted (client disconnected)" if client_disconnected else "successful"
        )
        logger.info(
            f"Streaming chat completion {status}: request_id={request_id}, "
            f"duration={round(duration, 3)}s, "
            f"prompt={total_input_tokens}, "
            f"completion={total_output_tokens}"
            f"{cache_info}"
        )

        await emit_request_metrics(
            endpoint="/v1/chat/completions",
            model=model,
            duration_s=round(duration, 3),
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            status_code=200,
            is_streaming=True,
            ttft_s=round(ttft, 3) if ttft is not None else None,
            cache_write_tokens=total_cache_creation_tokens,
            cache_read_tokens=total_cache_read_tokens,
        )

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        error_message = e.response.get("Error", {}).get("Message", str(e))
        logger.error(
            f"Bedrock streaming error: model={model}, request_id={request_id}, "
            f"code={error_code}, message={error_message}",
        )
        error_response = ErrorResponse(
            error=ErrorDetail(
                message=error_message,
                type=error_code,
                code=error_code,
            )
        )
        yield f"data: {error_response.model_dump_json()}\n\n"
    except Exception as e:
        logger.error(
            f"Streaming failed: model={model}, request_id={request_id}, error={e}",
            exc_info=True,
        )
        # Send error in SSE format
        error_response = ErrorResponse(
            error=ErrorDetail(
                message=str(e),
                type="server_error",
                code="internal_error",
            )
        )
        yield f"data: {error_response.model_dump_json()}\n\n"


async def record_usage(
    token_id: uuid.UUID,
    user_id: uuid.UUID,
    model: str,
    request_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    cache_ttl: str = None,
):
    """
    Record usage to database.

    Args:
        token_id: API token ID
        user_id: User ID
        model: Model name
        request_id: Request ID
        prompt_tokens: Number of prompt tokens (excludes cache tokens)
        completion_tokens: Number of completion tokens
        cache_creation_input_tokens: Tokens written to prompt cache
        cache_read_input_tokens: Tokens read from prompt cache
        cache_ttl: Cache TTL for write pricing ("5m" → 1.25x, "1h" → 2.0x)
    """
    # Create new db session for background task
    async for db in get_db():
        try:
            # Calculate cost using actual model pricing from database
            pricing_service = ModelPricing(db=db)
            cost_usd = await pricing_service.calculate_cost(
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cache_creation_input_tokens=cache_creation_input_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
                cache_ttl=cache_ttl,
            )

            # Create usage record
            usage_record = UsageRecord(
                user_id=user_id,
                token_id=token_id,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens
                + completion_tokens
                + cache_creation_input_tokens
                + cache_read_input_tokens,
                cache_creation_input_tokens=cache_creation_input_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
                cost_usd=cost_usd,
                request_id=request_id,
            )

            db.add(usage_record)
            await db.commit()

            logger.info(
                "Usage recorded",
                extra={
                    "request_id": request_id,
                    "user_id": str(user_id),
                    "cost_usd": round(cost_usd, 6),
                },
            )
        except ValueError as e:
            # If pricing not found, log error
            logger.error(
                f"Pricing not available for model {model}: {e}",
                extra={"request_id": request_id, "model": model},
            )
            await db.rollback()
        except Exception as e:
            logger.error(f"Failed to record usage: {e}", exc_info=True)
            await db.rollback()
        finally:
            await db.close()
        break  # Only use first session

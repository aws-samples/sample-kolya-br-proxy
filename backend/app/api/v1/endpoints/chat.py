"""
OpenAI-compatible chat completions endpoint.
"""

import logging
import time
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_token
from app.core.database import get_db
from app.models.token import APIToken
from app.models.usage import UsageRecord
from app.schemas.openai import (
    ChatCompletionRequest,
    ErrorDetail,
    ErrorResponse,
)
from app.services.background_tasks import BackgroundTaskManager
from app.services.bedrock import BedrockClient
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
            elif header_lower == "x-bedrock-request-metadata":
                try:
                    parsed_value = json.loads(header_value)
                    request_data.bedrock_request_metadata = parsed_value
                    logger.info(f"Applied request metadata from header: {parsed_value}")
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Failed to parse X-Bedrock-Request-Metadata as JSON: {e}"
                    )

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

        # Record usage asynchronously (don't block response)
        background_tasks.create_task(
            record_usage(
                token_id=token.id,
                user_id=token.user_id,
                model=request_data.model,
                request_id=request_id,
                prompt_tokens=openai_response.usage.prompt_tokens,
                completion_tokens=openai_response.usage.completion_tokens,
            ),
            task_name=f"record_usage_{request_id}",
        )

        duration = time.time() - start_time
        logger.info(
            "Chat completion successful",
            extra={
                "request_id": request_id,
                "duration_seconds": round(duration, 3),
                "prompt_tokens": openai_response.usage.prompt_tokens,
                "completion_tokens": openai_response.usage.completion_tokens,
            },
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
    except Exception as e:
        logger.error(
            f"Chat completion failed: model={request_data.model}, request_id={request_id}, error={e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error processing chat completion",
        )


async def stream_chat_completion(
    request_id: str,
    model: str,
    bedrock_request,
    bedrock_client: BedrockClient,
    token: APIToken,
    db: AsyncSession,
    start_time: float,
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

    Yields:
        SSE formatted response chunks
    """
    from app.core.config import get_settings

    settings = get_settings()
    total_input_tokens = 0
    total_output_tokens = 0
    last_heartbeat = time.time()

    # Track tool use state for streaming
    tool_use_blocks = {}  # {index: {"id": ..., "name": ..., "input": ""}}
    thinking_blocks = set()  # indices of thinking content blocks to skip

    try:
        async for event in bedrock_client.invoke_stream(model, bedrock_request):
            # Send heartbeat comment if no data for a while (keeps connection alive)
            current_time = time.time()
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

        # Send usage chunk before done marker (OpenAI spec)
        yield ResponseTranslator.create_stream_usage_chunk(
            request_id=request_id,
            model=model,
            prompt_tokens=total_input_tokens,
            completion_tokens=total_output_tokens,
        )

        # Send done marker
        yield ResponseTranslator.create_stream_done()

        # Record usage asynchronously (don't block stream)
        background_tasks.create_task(
            record_usage(
                token_id=token.id,
                user_id=token.user_id,
                model=model,
                request_id=request_id,
                prompt_tokens=total_input_tokens,
                completion_tokens=total_output_tokens,
            ),
            task_name=f"record_usage_{request_id}",
        )

        duration = time.time() - start_time
        logger.info(
            "Streaming chat completion successful",
            extra={
                "request_id": request_id,
                "duration_seconds": round(duration, 3),
                "prompt_tokens": total_input_tokens,
                "completion_tokens": total_output_tokens,
            },
        )

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
):
    """
    Record usage to database.

    Args:
        token_id: API token ID
        user_id: User ID
        model: Model name
        request_id: Request ID
        prompt_tokens: Number of prompt tokens
        completion_tokens: Number of completion tokens
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
            )

            # Create usage record
            usage_record = UsageRecord(
                user_id=user_id,
                token_id=token_id,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
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

"""
Anthropic Messages API compatible endpoint.
"""

import logging
import time
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_token_from_api_key
from app.core.config import get_settings
from app.core.database import get_db
from app.models.token import APIToken
from app.models.usage import UsageRecord
from app.schemas.anthropic import (
    AnthropicMessagesRequest,
)
from app.services.anthropic_translator import (
    AnthropicResponseTranslator,
)
from app.services.background_tasks import BackgroundTaskManager
from app.services.bedrock import BedrockClient
from app.services.pricing import ModelPricing

router = APIRouter()
logger = logging.getLogger(__name__)
background_tasks = BackgroundTaskManager()


@router.post("/messages")
async def create_message(
    request_data: AnthropicMessagesRequest,
    http_request: Request,
    token: APIToken = Depends(get_current_token_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a message (Anthropic Messages API compatible).

    This endpoint accepts Anthropic-format requests and proxies them to AWS Bedrock.
    Authentication is via x-api-key header.
    """
    request_id = f"msg_{uuid.uuid4().hex[:24]}"
    start_time = time.time()

    logger.info(
        f"Anthropic messages request: model={request_data.model}, "
        f"messages={len(request_data.messages)}, stream={request_data.stream}, "
        f"request_id={request_id}, token_id={token.id}",
    )

    try:
        # Check token quota
        from sqlalchemy import select, func
        from app.models.model import Model
        from decimal import Decimal

        result = await db.execute(
            select(func.sum(UsageRecord.cost_usd)).where(
                UsageRecord.token_id == token.id
            )
        )
        total_used = result.scalar() or Decimal("0.00")
        token.calculate_used_usd(total_used)

        if token.is_quota_exceeded:
            raise HTTPException(
                status_code=429,
                detail=f"Token quota exceeded. Used: ${total_used:.2f}, Quota: ${token.quota_usd:.2f}",
            )

        # Validate model access
        result = await db.execute(
            select(Model).where(
                Model.token_id == token.id,
                Model.is_active,
                ~Model.is_deleted,
            )
        )
        token_models = result.scalars().all()
        allowed_model_names = [model.model_name for model in token_models]

        if not allowed_model_names:
            raise HTTPException(
                status_code=403,
                detail="Token does not have access to any models",
            )

        if request_data.model not in allowed_model_names:
            raise HTTPException(
                status_code=403,
                detail=f"Token does not have access to model: {request_data.model}. Allowed models: {allowed_model_names}",
            )

        # Apply token-level prompt cache settings
        auto_cache = None
        cache_ttl = None
        if token.token_metadata:
            meta = token.token_metadata
            if "prompt_cache_enabled" in meta:
                auto_cache = meta["prompt_cache_enabled"]
            if "prompt_cache_ttl" in meta:
                cache_ttl = meta["prompt_cache_ttl"]

        bedrock_client = BedrockClient.get_instance()

        from app.services.anthropic_translator import AnthropicRequestTranslator

        # Build a BedrockRequest for the invoke pipeline
        bedrock_request = AnthropicRequestTranslator.to_bedrock(request_data)
        bedrock_request.auto_cache = auto_cache
        bedrock_request.cache_ttl = cache_ttl

        # Handle streaming
        if request_data.stream:
            return StreamingResponse(
                stream_anthropic_messages(
                    request_id=request_id,
                    model=request_data.model,
                    bedrock_request=bedrock_request,
                    bedrock_client=bedrock_client,
                    token=token,
                    db=db,
                    start_time=start_time,
                    http_request=http_request,
                    cache_ttl=cache_ttl or get_settings().PROMPT_CACHE_TTL,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )

        # Non-streaming response
        bedrock_response = await bedrock_client.invoke(
            request_data.model, bedrock_request
        )

        # Translate response
        anthropic_response = AnthropicResponseTranslator.bedrock_to_anthropic(
            bedrock_response, request_data.model, request_id
        )

        # Extract cache token counts
        cache_creation_tokens = bedrock_response.usage.cache_creation_input_tokens or 0
        cache_read_tokens = bedrock_response.usage.cache_read_input_tokens or 0
        effective_cache_ttl = cache_ttl or get_settings().PROMPT_CACHE_TTL

        # Record usage asynchronously
        background_tasks.create_task(
            record_usage(
                token_id=token.id,
                user_id=token.user_id,
                model=request_data.model,
                request_id=request_id,
                prompt_tokens=anthropic_response.usage.input_tokens,
                completion_tokens=anthropic_response.usage.output_tokens,
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
            f"Anthropic messages successful: request_id={request_id}, "
            f"duration={round(duration, 3)}s, "
            f"input={anthropic_response.usage.input_tokens}, "
            f"output={anthropic_response.usage.output_tokens}"
            f"{cache_info}"
        )

        return anthropic_response

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(
            "Invalid request",
            extra={"request_id": request_id, "error": str(e)},
            exc_info=True,
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(
            f"Anthropic messages failed: model={request_data.model}, request_id={request_id}, error={e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error processing message request",
        )


async def stream_anthropic_messages(
    request_id: str,
    model: str,
    bedrock_request,
    bedrock_client: BedrockClient,
    token: APIToken,
    db: AsyncSession,
    start_time: float,
    http_request: Request = None,
    cache_ttl: str = None,
) -> AsyncGenerator[str, None]:
    """
    Stream Anthropic Messages API responses.

    Converts Bedrock stream events to Anthropic SSE format:
    event: {event_type}
    data: {json}

    """
    settings = get_settings()
    accumulated_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    last_heartbeat = time.time()
    client_disconnected = False

    try:
        async for event in bedrock_client.invoke_stream(model, bedrock_request):
            # Check client disconnect
            current_time = time.time()
            if http_request and current_time - last_heartbeat > 1.0:
                if await http_request.is_disconnected():
                    client_disconnected = True
                    logger.info(
                        "Client disconnected, stopping stream",
                        extra={"request_id": request_id},
                    )
                    break

            # Send heartbeat as SSE comment
            if current_time - last_heartbeat > settings.STREAM_HEARTBEAT_INTERVAL:
                try:
                    yield ": heartbeat\n\n"
                except (BrokenPipeError, ConnectionResetError):
                    return
                last_heartbeat = current_time

            # Convert Bedrock event to Anthropic SSE events
            sse_events = AnthropicResponseTranslator.bedrock_stream_to_anthropic_events(
                event=event,
                model=model,
                request_id=request_id,
                accumulated_usage=accumulated_usage,
            )

            for sse_event in sse_events:
                yield sse_event
                last_heartbeat = current_time

        # Record usage
        total_input = accumulated_usage.get("input_tokens", 0)
        total_output = accumulated_usage.get("output_tokens", 0)
        total_cache_creation = accumulated_usage.get("cache_creation_input_tokens", 0)
        total_cache_read = accumulated_usage.get("cache_read_input_tokens", 0)

        background_tasks.create_task(
            record_usage(
                token_id=token.id,
                user_id=token.user_id,
                model=model,
                request_id=request_id,
                prompt_tokens=total_input,
                completion_tokens=total_output,
                cache_creation_input_tokens=total_cache_creation,
                cache_read_input_tokens=total_cache_read,
                cache_ttl=cache_ttl if total_cache_creation else None,
            ),
            task_name=f"record_usage_{request_id}",
        )

        duration = time.time() - start_time
        cache_info = ""
        if total_cache_creation:
            cache_info += f", cache_write={total_cache_creation}"
        if total_cache_read:
            cache_info += f", cache_read={total_cache_read}"
        status_str = (
            "aborted (client disconnected)" if client_disconnected else "successful"
        )
        logger.info(
            f"Anthropic streaming {status_str}: request_id={request_id}, "
            f"duration={round(duration, 3)}s, "
            f"input={total_input}, output={total_output}"
            f"{cache_info}"
        )

    except Exception as e:
        logger.error(
            f"Anthropic streaming failed: model={model}, request_id={request_id}, error={e}",
            exc_info=True,
        )
        # Send error in Anthropic SSE format
        import json

        error_data = {
            "type": "error",
            "error": {"type": "server_error", "message": str(e)},
        }
        yield f"event: error\ndata: {json.dumps(error_data)}\n\n"


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
    """Record usage to database (same logic as OpenAI endpoint)."""
    from app.core.database import get_db

    async for db in get_db():
        try:
            pricing_service = ModelPricing(db=db)
            cost_usd = await pricing_service.calculate_cost(
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cache_creation_input_tokens=cache_creation_input_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
                cache_ttl=cache_ttl,
            )

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
        break

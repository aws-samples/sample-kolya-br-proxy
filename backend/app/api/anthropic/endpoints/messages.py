"""
Anthropic Messages API compatible endpoint.
"""

import json
import logging
import time
import uuid
from typing import AsyncGenerator

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_token_flexible
from app.core.config import get_settings
from app.core.database import get_db
from app.models.token import APIToken
from app.models.usage import UsageRecord
from app.schemas.anthropic import (
    AnthropicMessage,
    AnthropicMessagesRequest,
)
from app.services.anthropic_translator import (
    AnthropicResponseTranslator,
)
from app.services.background_tasks import BackgroundTaskManager
from app.core.metrics import emit_request_metrics
from app.services.bedrock import BedrockClient, get_fallback_models
from app.services.gemini_client import is_gemini_model as _is_gemini_model
from app.services.mantle_models import is_openai_mantle_model as _is_mantle_model
from app.services.pricing import ModelPricing
from app.services.trace_store import TraceRecord, TraceStore

router = APIRouter()
logger = logging.getLogger(__name__)
background_tasks = BackgroundTaskManager()


def _build_trace_request(
    request_data: AnthropicMessagesRequest, request_id: str, token: "APIToken"
) -> TraceRecord:
    """Build a TraceRecord from the incoming request (response fields filled later)."""

    def _serialize_system(sys):
        if sys is None:
            return None
        if isinstance(sys, str):
            return sys
        return [b.model_dump() if hasattr(b, "model_dump") else b for b in sys]

    def _serialize_messages(msgs):
        out = []
        for m in msgs:
            content = m.content
            if isinstance(content, list):
                content = [
                    b.model_dump() if hasattr(b, "model_dump") else b for b in content
                ]
            out.append({"role": m.role, "content": content})
        return out

    def _serialize_tools(tools):
        if not tools:
            return []
        return [t.model_dump() if hasattr(t, "model_dump") else t for t in tools]

    return TraceRecord(
        request_id=request_id,
        timestamp=time.time(),
        model=request_data.model,
        token_id=str(token.id),
        token_name=token.name or "",
        system=_serialize_system(request_data.system),
        messages=_serialize_messages(request_data.messages),
        tools=_serialize_tools(request_data.tools),
        thinking=request_data.thinking.model_dump() if request_data.thinking else None,
        max_tokens=request_data.max_tokens,
        temperature=request_data.temperature,
        stream=request_data.stream or False,
    )


def _accumulate_usage(accumulated_usage: dict, usage) -> None:
    """Add a BedrockResponse.usage into the running accumulated_usage dict."""
    if not usage:
        return
    accumulated_usage["input_tokens"] += usage.input_tokens or 0
    accumulated_usage["output_tokens"] += usage.output_tokens or 0
    accumulated_usage["cache_creation_input_tokens"] += (
        usage.cache_creation_input_tokens or 0
    )
    accumulated_usage["cache_read_input_tokens"] += usage.cache_read_input_tokens or 0


def _bedrock_response_to_sse(
    response, model: str, request_id: str, accumulated_usage: dict
) -> list[str]:
    """Convert a non-streaming BedrockResponse to Anthropic SSE event strings.

    Used when the web search tool loop consumed a non-streaming response and
    needs to emit it as SSE to the streaming client.
    """
    from app.services.anthropic_translator import AnthropicResponseTranslator

    sse = AnthropicResponseTranslator.create_stream_event
    events = []
    usage = response.usage
    input_tokens = (usage.input_tokens or 0) if usage else 0
    output_tokens = (usage.output_tokens or 0) if usage else 0

    events.append(
        sse(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": request_id,
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": model,
                    "stop_reason": None,
                    "usage": {
                        "input_tokens": input_tokens
                        + accumulated_usage.get("input_tokens", 0),
                        "output_tokens": 0,
                        "cache_creation_input_tokens": accumulated_usage.get(
                            "cache_creation_input_tokens", 0
                        ),
                        "cache_read_input_tokens": accumulated_usage.get(
                            "cache_read_input_tokens", 0
                        ),
                    },
                },
            },
        )
    )

    for idx, block in enumerate(response.content or []):
        if block.type == "text":
            events.append(
                sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": idx,
                        "content_block": {"type": "text", "text": ""},
                    },
                )
            )
            if block.text:
                events.append(
                    sse(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": idx,
                            "delta": {"type": "text_delta", "text": block.text},
                        },
                    )
                )
            events.append(
                sse("content_block_stop", {"type": "content_block_stop", "index": idx})
            )
        elif block.type == "tool_use":
            events.append(
                sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": idx,
                        "content_block": {
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": {},
                        },
                    },
                )
            )
            input_json = json.dumps(block.input or {}, ensure_ascii=False)
            events.append(
                sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": idx,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": input_json,
                        },
                    },
                )
            )
            events.append(
                sse("content_block_stop", {"type": "content_block_stop", "index": idx})
            )
        elif block.type == "thinking":
            events.append(
                sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": idx,
                        "content_block": {"type": "thinking", "thinking": ""},
                    },
                )
            )
            if block.thinking:
                events.append(
                    sse(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": idx,
                            "delta": {
                                "type": "thinking_delta",
                                "thinking": block.thinking,
                            },
                        },
                    )
                )
            if block.signature:
                events.append(
                    sse(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": idx,
                            "delta": {
                                "type": "signature_delta",
                                "signature": block.signature,
                            },
                        },
                    )
                )
            events.append(
                sse("content_block_stop", {"type": "content_block_stop", "index": idx})
            )

    events.append(
        sse(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": response.stop_reason or "end_turn"},
                "usage": {"output_tokens": output_tokens},
            },
        )
    )

    events.append(sse("message_stop", {"type": "message_stop"}))

    return events


@router.post("/messages")
async def create_message(
    request_data: AnthropicMessagesRequest,
    http_request: Request,
    token: APIToken = Depends(get_current_token_flexible),
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
        from sqlalchemy import select
        from app.models.model import Model

        # Check all quota tiers (lifetime, monthly, daily)
        from app.services.quota import enforce_quota

        await enforce_quota(token, db)

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

        def _normalize_model(name: str) -> str:
            import re

            for prefix in (
                "global.anthropic.",
                "us.anthropic.",
                "eu.anthropic.",
                "ap.anthropic.",
                "anthropic.",
            ):
                if name.startswith(prefix):
                    name = name[len(prefix) :]
                    break
            return re.sub(r"-v\d+(?::\d+)?$", "", name)

        normalized_requested = _normalize_model(request_data.model)
        normalized_allowed = {_normalize_model(m) for m in allowed_model_names}

        if normalized_requested not in normalized_allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Token does not have access to model: {request_data.model}. Allowed models: {allowed_model_names}",
            )

        # Resolve to the Bedrock model name stored in DB (in case client sent a short Anthropic name)
        matched = next(
            (
                m
                for m in allowed_model_names
                if _normalize_model(m) == normalized_requested
            ),
            None,
        )
        if matched and matched != request_data.model:
            request_data.model = matched

        # Route Gemini models to Google API
        if _is_gemini_model(request_data.model):
            return await _handle_gemini_via_anthropic(
                request_data=request_data,
                request_id=request_id,
                token=token,
                start_time=start_time,
            )

        # Route OpenAI GPT-5.5/5.4 (mantle) to the Responses API
        if _is_mantle_model(request_data.model):
            return await _handle_mantle_via_anthropic(
                request_data=request_data,
                request_id=request_id,
                token=token,
                start_time=start_time,
            )

        # Apply token-level prompt cache settings
        auto_cache = None
        cache_ttl = None
        web_search_enabled = False
        web_search_provider = None
        if token.token_metadata:
            meta = token.token_metadata
            if "prompt_cache_enabled" in meta:
                auto_cache = meta["prompt_cache_enabled"]
            if "prompt_cache_ttl" in meta:
                cache_ttl = meta["prompt_cache_ttl"]
            if meta.get("web_search_enabled"):
                web_search_enabled = True
                web_search_provider = meta.get("web_search_provider")

        bedrock_client = BedrockClient.get_instance()

        from app.services.anthropic_translator import AnthropicRequestTranslator
        from app.services.builtin_tools import process_builtin_tools

        # Process built-in tools (web_search, computer, etc.)
        filtered_tools, has_web_search, web_search_max_uses = process_builtin_tools(
            request_data.tools,
            web_search_allowed=web_search_enabled,
            web_search_provider=web_search_provider,
        )
        request_data.tools = filtered_tools

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
                    allowed_model_names=allowed_model_names,
                    request_data=request_data,
                    has_web_search=has_web_search,
                    web_search_max_uses=web_search_max_uses,
                    web_search_provider=web_search_provider,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )

        # Non-streaming response with tool execution loop
        from app.services.tool_execution import (
            SERVER_EXECUTED_TOOLS,
            build_continuation_messages,
            execute_server_tools,
            extract_tool_calls,
            response_has_server_tool_use,
            serialize_response_content,
        )

        bedrock_response = await bedrock_client.invoke(
            request_data.model, bedrock_request
        )

        # Tool execution loop for server-side tools (web_search)
        search_count = 0
        while (
            has_web_search
            and response_has_server_tool_use(bedrock_response)
            and search_count < web_search_max_uses
        ):
            tool_calls = extract_tool_calls(bedrock_response)
            server_calls = [c for c in tool_calls if c["name"] in SERVER_EXECUTED_TOOLS]
            search_count += len(server_calls)

            tool_results = await execute_server_tools(
                server_calls, provider=web_search_provider
            )
            assistant_content = serialize_response_content(bedrock_response)

            new_messages = build_continuation_messages(
                request_data.messages, assistant_content, tool_results
            )

            request_data.messages = [
                AnthropicMessage(**m) if isinstance(m, dict) else m
                for m in new_messages
            ]
            bedrock_request = AnthropicRequestTranslator.to_bedrock(request_data)
            bedrock_request.auto_cache = auto_cache
            bedrock_request.cache_ttl = cache_ttl

            logger.info(
                f"Web search loop iteration {search_count}/{web_search_max_uses}, "
                f"request_id={request_id}"
            )

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

        await emit_request_metrics(
            endpoint="/v1/messages",
            model=request_data.model,
            duration_s=round(duration, 3),
            input_tokens=anthropic_response.usage.input_tokens,
            output_tokens=anthropic_response.usage.output_tokens,
            status_code=200,
            is_streaming=False,
            cache_write_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
        )

        # Record trace
        if TraceStore.is_enabled():
            trace_rec = _build_trace_request(request_data, request_id, token)
            trace_rec.duration_s = round(duration, 3)
            trace_rec.stop_reason = anthropic_response.stop_reason or ""
            trace_rec.input_tokens = anthropic_response.usage.input_tokens
            trace_rec.output_tokens = anthropic_response.usage.output_tokens
            trace_rec.cache_creation_input_tokens = cache_creation_tokens
            trace_rec.cache_read_input_tokens = cache_read_tokens
            trace_rec.response_content = [
                b.model_dump() if hasattr(b, "model_dump") else b
                for b in (anthropic_response.content or [])
            ]
            TraceStore.get_instance().add(trace_rec)

        return anthropic_response

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(
            "Invalid request",
            extra={"request_id": request_id, "error": str(e)},
            exc_info=True,
        )
        raise HTTPException(status_code=400, detail="Invalid request")
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        error_message = e.response.get("Error", {}).get("Message", "")
        logger.error(
            f"Bedrock error: model={request_data.model}, request_id={request_id}, "
            f"code={error_code}, message={error_message}",
        )
        status_map = {
            "ValidationException": 400,
            "AccessDeniedException": 403,
            "ThrottlingException": 429,
            "ModelNotReadyException": 529,
            "ServiceUnavailableException": 529,
        }
        safe_messages = {
            "ValidationException": "Invalid request parameters",
            "AccessDeniedException": "Access denied to the requested model",
            "ThrottlingException": "Rate limit exceeded, please retry later",
            "ModelNotReadyException": "Model is temporarily unavailable",
            "ServiceUnavailableException": "Service temporarily unavailable",
        }
        status_code = status_map.get(error_code, 502)
        raise HTTPException(
            status_code=status_code,
            detail=safe_messages.get(error_code, "Upstream service error"),
        )
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
    allowed_model_names: list[str] | None = None,
    request_data: AnthropicMessagesRequest | None = None,
    has_web_search: bool = False,
    web_search_max_uses: int = 5,
    web_search_provider: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    Stream Anthropic Messages API responses.

    Converts Bedrock stream events to Anthropic SSE format:
    event: {event_type}
    data: {json}

    When web_search is enabled, intermediate tool-loop rounds use non-streaming
    invocations. Only the final round (or first if no tool_use) is streamed.
    """
    from app.services.anthropic_translator import AnthropicRequestTranslator
    from app.services.tool_execution import (
        build_continuation_messages,
        execute_server_tools,
        extract_tool_calls,
        response_has_server_tool_use,
        serialize_response_content,
        SERVER_EXECUTED_TOOLS,
    )

    settings = get_settings()
    ttft: float | None = None
    accumulated_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    last_heartbeat = time.time()
    client_disconnected = False
    # Accumulate response content blocks for trace
    trace_content_blocks: list[dict] = []
    trace_current_block: dict | None = None
    trace_chunks: list[str] = []
    trace_stop_reason = ""

    # Compute fallback models for stream failover
    fb_models = get_fallback_models(allowed_model_names or [], model)

    # --- Web search tool loop (non-streaming) ---
    # When web_search is enabled, use non-streaming calls to detect and handle
    # WebSearch tool_use server-side. The final response (text or client-tool)
    # is serialized as SSE events instead of re-invoking in streaming mode.
    if has_web_search and request_data:
        search_count = 0
        while search_count < web_search_max_uses:
            bedrock_response = await bedrock_client.invoke(model, bedrock_request)

            if not response_has_server_tool_use(bedrock_response):
                break

            tool_calls = extract_tool_calls(bedrock_response)
            server_calls = [c for c in tool_calls if c["name"] in SERVER_EXECUTED_TOOLS]
            search_count += len(server_calls)

            _accumulate_usage(accumulated_usage, bedrock_response.usage)

            tool_results = await execute_server_tools(
                server_calls, provider=web_search_provider
            )
            assistant_content = serialize_response_content(bedrock_response)

            new_messages = build_continuation_messages(
                request_data.messages, assistant_content, tool_results
            )
            request_data.messages = [
                AnthropicMessage(**m) if isinstance(m, dict) else m
                for m in new_messages
            ]
            bedrock_request = AnthropicRequestTranslator.to_bedrock(request_data)
            bedrock_request.auto_cache = None
            bedrock_request.cache_ttl = cache_ttl

            logger.info(
                f"Stream web search loop iteration {search_count}/{web_search_max_uses}, "
                f"request_id={request_id}"
            )

        if search_count > 0:
            # Search was executed; stream the final response from updated messages
            # (bedrock_request already updated with tool results)
            pass
        else:
            # Model didn't call server tools on first try. Convert the non-streaming
            # response to SSE events to avoid wasting the call.
            for sse in _bedrock_response_to_sse(
                bedrock_response, model, request_id, accumulated_usage
            ):
                yield sse

            # Fill trace and usage from this response
            _accumulate_usage(accumulated_usage, bedrock_response.usage)
            trace_stop_reason = bedrock_response.stop_reason or ""
            for block in bedrock_response.content or []:
                if block.type == "text":
                    trace_content_blocks.append(
                        {"type": "text", "text": block.text or ""}
                    )
                elif block.type == "tool_use":
                    trace_content_blocks.append(
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
                    trace_content_blocks.append(b)

            # Skip streaming — jump to recording usage/trace
            # (reuse the same post-stream recording logic below)
            total_input = accumulated_usage.get("input_tokens", 0)
            total_output = accumulated_usage.get("output_tokens", 0)
            total_cache_creation = accumulated_usage.get(
                "cache_creation_input_tokens", 0
            )
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
            logger.info(
                f"Anthropic streaming successful: request_id={request_id}, "
                f"duration={round(duration, 3)}s, "
                f"input={total_input}, output={total_output}"
                f"{cache_info}"
            )

            await emit_request_metrics(
                endpoint="/v1/messages",
                model=model,
                duration_s=round(duration, 3),
                input_tokens=total_input,
                output_tokens=total_output,
                status_code=200,
                is_streaming=True,
                ttft_s=round(duration, 3),
                cache_write_tokens=total_cache_creation,
                cache_read_tokens=total_cache_read,
            )

            if TraceStore.is_enabled() and request_data:
                trace_rec = _build_trace_request(request_data, request_id, token)
                trace_rec.duration_s = round(duration, 3)
                trace_rec.stop_reason = trace_stop_reason
                trace_rec.input_tokens = total_input
                trace_rec.output_tokens = total_output
                trace_rec.cache_creation_input_tokens = total_cache_creation
                trace_rec.cache_read_input_tokens = total_cache_read
                trace_rec.response_content = trace_content_blocks
                TraceStore.get_instance().add(trace_rec)

            return

    try:
        actual_model_emitted = False
        async for event in bedrock_client.invoke_stream(
            model, bedrock_request, fallback_models=fb_models
        ):
            # Emit x-actual-model SSE comment on Level 2 degradation
            if event.actual_model and not actual_model_emitted:
                yield f": x-actual-model {event.actual_model}\n\n"
                actual_model_emitted = True
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

            # Measure time to first content token
            if ttft is None and event.type == "content_block_delta":
                ttft = time.time() - start_time

            # Accumulate content for trace
            if event.type == "content_block_start" and event.content_block:
                cb = event.content_block
                trace_current_block = {"type": cb.type}
                trace_chunks = []
                if cb.type == "tool_use":
                    trace_current_block["id"] = cb.id or ""
                    trace_current_block["name"] = cb.name or ""
            elif (
                event.type == "content_block_delta"
                and event.delta
                and trace_current_block
            ):
                delta = event.delta
                chunk = (
                    delta.get("text")
                    or delta.get("thinking")
                    or delta.get("partial_json")
                    or delta.get("signature")
                    or ""
                )
                if chunk:
                    trace_chunks.append(chunk)
            elif event.type == "content_block_stop" and trace_current_block:
                joined = "".join(trace_chunks)
                btype = trace_current_block["type"]
                if btype == "text":
                    trace_current_block["text"] = joined
                elif btype == "thinking":
                    trace_current_block["thinking"] = joined
                elif btype == "tool_use":
                    try:
                        trace_current_block["input"] = json.loads(joined or "{}")
                    except (ValueError, TypeError):
                        trace_current_block["input"] = joined
                elif btype == "signature":
                    trace_current_block["signature"] = joined
                trace_content_blocks.append(trace_current_block)
                trace_current_block = None
            elif event.type == "message_delta" and event.delta:
                trace_stop_reason = event.delta.get("stop_reason", "")

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

        await emit_request_metrics(
            endpoint="/v1/messages",
            model=model,
            duration_s=round(duration, 3),
            input_tokens=total_input,
            output_tokens=total_output,
            status_code=200,
            is_streaming=True,
            ttft_s=round(ttft, 3) if ttft is not None else None,
            cache_write_tokens=total_cache_creation,
            cache_read_tokens=total_cache_read,
        )

        # Record trace
        if TraceStore.is_enabled() and request_data:
            trace_rec = _build_trace_request(request_data, request_id, token)
            trace_rec.duration_s = round(duration, 3)
            trace_rec.stop_reason = trace_stop_reason
            trace_rec.input_tokens = total_input
            trace_rec.output_tokens = total_output
            trace_rec.cache_creation_input_tokens = total_cache_creation
            trace_rec.cache_read_input_tokens = total_cache_read
            trace_rec.response_content = trace_content_blocks
            TraceStore.get_instance().add(trace_rec)

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        error_message = e.response.get("Error", {}).get("Message", "")
        logger.error(
            f"Bedrock streaming error: model={model}, request_id={request_id}, "
            f"code={error_code}, message={error_message}",
        )
        import json as _json

        error_type_map = {
            "ValidationException": "invalid_request_error",
            "AccessDeniedException": "permission_error",
            "ThrottlingException": "rate_limit_error",
            "ModelNotReadyException": "overloaded_error",
            "ServiceUnavailableException": "overloaded_error",
        }
        safe_messages = {
            "ValidationException": "Invalid request parameters",
            "AccessDeniedException": "Access denied to the requested model",
            "ThrottlingException": "Rate limit exceeded, please retry later",
            "ModelNotReadyException": "Model is temporarily unavailable",
            "ServiceUnavailableException": "Service temporarily unavailable",
        }
        error_type = error_type_map.get(error_code, "api_error")
        error_data = {
            "type": "error",
            "error": {
                "type": error_type,
                "message": safe_messages.get(error_code, "Upstream service error"),
            },
        }
        yield f"event: error\ndata: {_json.dumps(error_data)}\n\n"
    except Exception as e:
        logger.error(
            f"Anthropic streaming failed: model={model}, request_id={request_id}, error={e}",
            exc_info=True,
        )
        import json as _json

        error_data = {
            "type": "error",
            "error": {"type": "server_error", "message": "Internal server error"},
        }
        yield f"event: error\ndata: {_json.dumps(error_data)}\n\n"


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

            try:
                from app.services.alert import check_alerts_for_usage

                await check_alerts_for_usage(token_id=token_id, user_id=user_id, db=db)
            except Exception:
                logger.warning("Alert check failed", exc_info=True)

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


# ---------------------------------------------------------------------------
# Gemini routing via Anthropic Messages endpoint
# ---------------------------------------------------------------------------


async def _handle_gemini_via_anthropic(
    request_data: "AnthropicMessagesRequest",
    request_id: str,
    token: APIToken,
    start_time: float,
):
    """
    Forward a Gemini model request received on the Anthropic Messages endpoint.

    Converts Anthropic-format messages to Gemini native format, calls the
    Google API, and converts the response back to Anthropic format.
    """
    import httpx

    from app.services.gemini_client import (
        GeminiClient,
        extract_cached_tokens,
        is_gemini_configured,
    )

    if not is_gemini_configured():
        raise HTTPException(
            status_code=503,
            detail="Gemini API is not configured on this server",
        )

    # Convert Anthropic messages to OpenAI-style messages for the Gemini
    # client which already has OpenAI→Gemini translation.
    openai_messages = []
    if request_data.system:
        system_text = (
            request_data.system
            if isinstance(request_data.system, str)
            else " ".join(b.text for b in request_data.system if hasattr(b, "text"))
        )
        if system_text:
            openai_messages.append({"role": "system", "content": system_text})

    for msg in request_data.messages:
        content = msg.content
        if isinstance(content, list):
            # Extract text from content blocks
            texts = []
            for block in content:
                if hasattr(block, "text"):
                    texts.append(block.text)
                elif isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
            content = "\n".join(texts) if texts else ""
        openai_messages.append({"role": msg.role, "content": content})

    payload = {
        "model": request_data.model,
        "messages": openai_messages,
    }
    if request_data.temperature is not None:
        payload["temperature"] = request_data.temperature
    if request_data.max_tokens:
        payload["max_tokens"] = request_data.max_tokens

    if request_data.stream:
        return StreamingResponse(
            _stream_gemini_as_anthropic(
                payload=payload,
                request_id=request_id,
                model=request_data.model,
                token=token,
                start_time=start_time,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    # Non-streaming
    try:
        response_data = await GeminiClient.invoke(payload)
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Gemini API error: status {e.response.status_code}",
        )

    # Convert OpenAI-format response to Anthropic format
    choices = response_data.get("choices", [])
    usage = response_data.get("usage", {})
    content_text = ""
    if choices:
        msg = choices[0].get("message", {})
        content_text = msg.get("content", "") or ""

    cached_tokens = extract_cached_tokens(response_data)
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    non_cached_prompt = max(0, prompt_tokens - cached_tokens)

    # Record usage
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
    logger.info(
        f"Anthropic→Gemini non-streaming done: request_id={request_id}, "
        f"duration={round(duration, 3)}s, "
        f"prompt={non_cached_prompt}, completion={completion_tokens}"
    )

    return {
        "id": request_id,
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": content_text}],
        "model": request_data.model,
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": non_cached_prompt,
            "output_tokens": completion_tokens,
        },
    }


async def _stream_gemini_as_anthropic(
    payload: dict,
    request_id: str,
    model: str,
    token: APIToken,
    start_time: float,
) -> AsyncGenerator[str, None]:
    """
    Stream Gemini response converted to Anthropic SSE format.

    The Gemini client yields OpenAI-format SSE chunks; we convert each to
    Anthropic streaming events.
    """
    import json as _json
    from app.services.gemini_client import (
        GeminiClient,
        extract_cached_tokens_from_chunk,
    )

    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cached_tokens = 0
    block_started = False

    try:
        # Send message_start event
        yield (
            "event: message_start\n"
            f"data: {_json.dumps({'type': 'message_start', 'message': {'id': request_id, 'type': 'message', 'role': 'assistant', 'content': [], 'model': model, 'usage': {'input_tokens': 0, 'output_tokens': 0}}})}\n\n"
        )

        async for chunk in GeminiClient.invoke_stream(payload):
            for line in chunk.splitlines():
                if not line.startswith("data: ") or line.strip() == "data: [DONE]":
                    continue

                try:
                    data = _json.loads(line[6:])
                except (ValueError, TypeError):
                    continue

                # Extract usage
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

                # Extract text delta
                choices = data.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                text = delta.get("content")
                if not isinstance(text, str) or not text:
                    continue

                # Send content_block_start on first text
                if not block_started:
                    yield (
                        "event: content_block_start\n"
                        f"data: {_json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
                    )
                    block_started = True

                # Send content_block_delta
                yield (
                    "event: content_block_delta\n"
                    f"data: {_json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': text}})}\n\n"
                )

        # Close content block
        if block_started:
            yield (
                "event: content_block_stop\n"
                f"data: {_json.dumps({'type': 'content_block_stop', 'index': 0})}\n\n"
            )

        # Send message_delta with usage
        yield (
            "event: message_delta\n"
            f"data: {_json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}, 'usage': {'output_tokens': total_completion_tokens}})}\n\n"
        )

        # Send message_stop
        yield (
            f"event: message_stop\ndata: {_json.dumps({'type': 'message_stop'})}\n\n"
        )

    except Exception as e:
        logger.error(
            f"Anthropic→Gemini streaming failed: model={model}, "
            f"request_id={request_id}, error={e}",
            exc_info=True,
        )
        yield (
            "event: error\n"
            f"data: {_json.dumps({'type': 'error', 'error': {'type': 'server_error', 'message': 'Internal server error'}})}\n\n"
        )

    # Record usage
    non_cached_prompt = max(0, total_prompt_tokens - total_cached_tokens)
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
    logger.info(
        f"Anthropic→Gemini streaming done: request_id={request_id}, "
        f"duration={round(duration, 3)}s, "
        f"prompt={non_cached_prompt}, completion={total_completion_tokens}"
    )


# ---------------------------------------------------------------------------
# OpenAI GPT-5.5/5.4 (mantle) routing via Anthropic Messages endpoint
# ---------------------------------------------------------------------------


def _anthropic_to_openai_messages(
    request_data: "AnthropicMessagesRequest",
) -> list[dict]:
    """Flatten Anthropic-format messages to OpenAI-style messages.

    Mirrors the conversion used by the Gemini path: system prompt → system
    message, and each message's text content blocks are joined into a single
    string. The MantleClient handles the OpenAI→Responses translation downstream.
    """
    openai_messages: list[dict] = []
    if request_data.system:
        system_text = (
            request_data.system
            if isinstance(request_data.system, str)
            else " ".join(b.text for b in request_data.system if hasattr(b, "text"))
        )
        if system_text:
            openai_messages.append({"role": "system", "content": system_text})

    for msg in request_data.messages:
        content = msg.content
        if isinstance(content, list):
            texts = []
            for block in content:
                if hasattr(block, "text"):
                    texts.append(block.text)
                elif isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
            content = "\n".join(texts) if texts else ""
        openai_messages.append({"role": msg.role, "content": content})

    return openai_messages


async def _handle_mantle_via_anthropic(
    request_data: "AnthropicMessagesRequest",
    request_id: str,
    token: APIToken,
    start_time: float,
):
    """
    Forward a GPT-5.5/5.4 (mantle) request received on the Anthropic endpoint.

    Converts Anthropic-format messages to OpenAI-style messages, calls the
    MantleClient (which translates to the Responses API and signs with SigV4),
    and converts the OpenAI-format response back to Anthropic format.
    """
    import httpx

    from app.services.mantle_client import (
        MantleClient,
        extract_cached_tokens,
    )

    openai_messages = _anthropic_to_openai_messages(request_data)

    payload = {
        "model": request_data.model,
        "messages": openai_messages,
    }
    if request_data.temperature is not None:
        payload["temperature"] = request_data.temperature
    if request_data.max_tokens:
        payload["max_tokens"] = request_data.max_tokens

    if request_data.stream:
        return StreamingResponse(
            _stream_mantle_as_anthropic(
                payload=payload,
                request_id=request_id,
                model=request_data.model,
                token=token,
                start_time=start_time,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    # Non-streaming
    try:
        response_data = await MantleClient.invoke(payload)
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"mantle API error: status {e.response.status_code}",
        )

    choices = response_data.get("choices", [])
    usage = response_data.get("usage", {})
    content_text = ""
    if choices:
        msg = choices[0].get("message", {})
        content_text = msg.get("content", "") or ""

    cached_tokens = extract_cached_tokens(response_data)
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
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
    logger.info(
        f"Anthropic→mantle non-streaming done: request_id={request_id}, "
        f"duration={round(duration, 3)}s, "
        f"prompt={non_cached_prompt}, completion={completion_tokens}"
    )

    return {
        "id": request_id,
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": content_text}],
        "model": request_data.model,
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": non_cached_prompt,
            "output_tokens": completion_tokens,
        },
    }


async def _stream_mantle_as_anthropic(
    payload: dict,
    request_id: str,
    model: str,
    token: APIToken,
    start_time: float,
) -> AsyncGenerator[str, None]:
    """
    Stream a mantle (GPT-5.5/5.4) response converted to Anthropic SSE format.

    MantleClient.invoke_stream yields OpenAI-format SSE chunks; we convert each
    to Anthropic streaming events (mirrors the Gemini streaming bridge).
    """
    import json as _json

    from app.services.mantle_client import (
        MantleClient,
        extract_cached_tokens_from_chunk,
    )

    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cached_tokens = 0
    block_started = False

    try:
        # Send message_start event
        yield (
            "event: message_start\n"
            f"data: {_json.dumps({'type': 'message_start', 'message': {'id': request_id, 'type': 'message', 'role': 'assistant', 'content': [], 'model': model, 'usage': {'input_tokens': 0, 'output_tokens': 0}}})}\n\n"
        )

        async for chunk in MantleClient.invoke_stream(payload):
            for line in chunk.splitlines():
                if not line.startswith("data: ") or line.strip() == "data: [DONE]":
                    continue

                try:
                    data = _json.loads(line[6:])
                except (ValueError, TypeError):
                    continue

                # Extract usage
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

                # Extract text delta
                choices = data.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                text = delta.get("content")
                if not isinstance(text, str) or not text:
                    continue

                # Send content_block_start on first text
                if not block_started:
                    yield (
                        "event: content_block_start\n"
                        f"data: {_json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
                    )
                    block_started = True

                # Send content_block_delta
                yield (
                    "event: content_block_delta\n"
                    f"data: {_json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': text}})}\n\n"
                )

        # Close content block
        if block_started:
            yield (
                "event: content_block_stop\n"
                f"data: {_json.dumps({'type': 'content_block_stop', 'index': 0})}\n\n"
            )

        # Send message_delta with usage
        yield (
            "event: message_delta\n"
            f"data: {_json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}, 'usage': {'output_tokens': total_completion_tokens}})}\n\n"
        )

        # Send message_stop
        yield (
            f"event: message_stop\ndata: {_json.dumps({'type': 'message_stop'})}\n\n"
        )

    except Exception as e:
        logger.error(
            f"Anthropic→mantle streaming failed: model={model}, "
            f"request_id={request_id}, error={e}",
            exc_info=True,
        )
        yield (
            "event: error\n"
            f"data: {_json.dumps({'type': 'error', 'error': {'type': 'server_error', 'message': 'Internal server error'}})}\n\n"
        )

    # Record usage
    non_cached_prompt = max(0, total_prompt_tokens - total_cached_tokens)
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
    logger.info(
        f"Anthropic→mantle streaming done: request_id={request_id}, "
        f"duration={round(duration, 3)}s, "
        f"prompt={non_cached_prompt}, completion={total_completion_tokens}"
    )

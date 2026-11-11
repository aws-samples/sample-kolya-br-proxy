# Pyright cannot model this module's legacy SQLAlchemy Column attributes and
# callback-style background task manager. Remove after their typing migrations.
# pyright: reportArgumentType=false
"""
OpenAI Responses API endpoint (native Bedrock passthrough).

Supported OpenAI models go through either the Mantle or Bedrock Runtime
**OpenAI Responses API**. The OpenAI-compatible ``/v1/chat/completions`` and the
Anthropic ``/v1/messages`` endpoints translate to/from the Responses format,
which necessarily flattens Responses-only features (built-in tools, multimodal
output, etc.).

This endpoint instead forwards a *native* Responses request body verbatim and
returns the native response, so clients that speak the Responses API avoid
lossy protocol conversion. Canonical IDs target Mantle; US/Global profile IDs
target Bedrock Runtime and preserve their routing semantics.

The request body is accepted as an open JSON object (not a strict schema) for
exactly that reason: unknown/new Responses fields pass straight through.
"""

import re
import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Dict

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import get_current_token_streaming
from app.api.v1.endpoints.chat import record_usage
from app.core.config import get_settings
from app.services.stream_usage_estimate import StreamUsageFallback
from app.core.stream_heartbeat import HEARTBEAT, with_heartbeat
from app.core.database import session_scope
from app.models.model import Model
from app.models.token import APIToken
from app.services.background_tasks import BackgroundTaskManager
from app.services import response_ownership
from app.services.cache_scope import scope_responses_cache
from app.services.mantle_client import (
    MantleClient,
    ResponsesRequestValidationError,
    validate_native_responses_cache,
)
from app.services.mantle_models import (
    resolve_responses_model_id,
    select_granted_responses_model,
)

router = APIRouter()
_MODEL_ID = re.compile(r"[!-~]{1,256}")

logger = logging.getLogger(__name__)
background_tasks = BackgroundTaskManager()


def _usage_from_response(usage: Dict[str, Any]) -> Dict[str, int]:
    """Extract billing token counts from a Responses ``usage`` object.

    Returns (non_cached_prompt, completion, cached) — input_tokens reported by
    the Responses API includes cached tokens, so bill only the non-cached part.
    """
    prompt = usage.get("input_tokens", 0) or 0
    completion = usage.get("output_tokens", 0) or 0
    details = usage.get("input_tokens_details") or {}
    cached = details.get("cached_tokens", 0) or 0
    cache_write = details.get("cache_write_tokens", 0) or 0
    return {
        "non_cached_prompt": max(0, prompt - cached - cache_write),
        "completion": completion,
        "cached": cached,
        "cache_write": cache_write,
    }


async def _record_owner(body: dict, response: dict, token: APIToken) -> None:
    """Remember which key owns a stored response, for later continuations."""
    response_id = response.get("id")
    if not isinstance(response_id, str) or not response_ownership.is_stored(
        body, response
    ):
        return
    try:
        await response_ownership.record_owner(response_id, token.id)
    except Exception:
        # Fail closed: without a row the response simply can't be continued.
        logger.error("Failed to record response owner", exc_info=True)


@router.post("/responses")
async def create_response(
    http_request: Request,
    token: APIToken = Depends(get_current_token_streaming),
):
    """
    Create a model response (OpenAI Responses API, native passthrough).

    Only mantle-served models (see mantle_models registry) are accepted — others do
    not have a Responses API backend. The request body is forwarded to mantle
    verbatim and the native response is returned unchanged.
    """
    request_id = f"resp_{uuid.uuid4().hex[:24]}"
    start_time = time.time()

    # Parse the raw JSON body (open schema — forward unknown fields verbatim)
    try:
        body: Dict[str, Any] = await http_request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON request body")
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400, detail="Request body must be a JSON object"
        )

    requested_model = body.get("model")
    if not requested_model or not isinstance(requested_model, str):
        raise HTTPException(status_code=400, detail="Missing 'model' in request body")
    if not _MODEL_ID.fullmatch(requested_model):
        # Same rule as the schema ModelId: the value is logged below.
        raise HTTPException(status_code=400, detail="Invalid 'model' value")

    stream = bool(body.get("stream", False))

    logger.info(
        "Responses request: model=%s, stream=%s",
        requested_model,
        stream,
    )

    # Canonical/bare IDs use Mantle; US/Global system inference profiles use
    # the Bedrock Runtime OpenAI Responses endpoint without being normalized.
    model = resolve_responses_model_id(requested_model)
    if model is None:
        raise HTTPException(
            status_code=400,
            detail=(
                # Don't list the registry: it includes models this key
                # isn't granted. GET /v1/models shows what the key can use.
                "This model is not available on the Responses API. "
                "See GET /v1/models for the models this key can use; "
                "use /v1/chat/completions for other models."
            ),
        )

    # Quota + model access (same checks as the other gateway endpoints).
    # Done in a short-lived session released before streaming: a Responses
    # stream can run for tens of seconds and must not pin a pooled connection.
    from sqlalchemy import select
    from app.services.quota import enforce_quota

    async with session_scope() as db:
        await enforce_quota(token, db)

        result = await db.execute(
            select(Model).where(
                Model.token_id == token.id,
                Model.is_active,
                ~Model.is_deleted,
            )
        )
        allowed_model_names = [m.model_name for m in result.scalars().all()]
    # Connection returned to the pool here — the stream below holds none.
    # Authorize without widening scope: profiles need an exact grant, and a
    # canonical request from a profile-only grant is served by that profile.
    granted = select_granted_responses_model(model, allowed_model_names)
    if granted is None:
        raise HTTPException(
            status_code=403,
            detail=f"Token does not have access to model: {model}. "
            f"Allowed models: {allowed_model_names}",
        )
    model = granted
    # Forward the exact target: canonical for Mantle, exact profile ID for
    # Runtime so cross-Region routing and pricing semantics remain intact.
    body["model"] = model

    # Reject explicit cache usage the exact model cannot honour before any
    # upstream call or stream is opened.
    try:
        validate_native_responses_cache(body)
    except ResponsesRequestValidationError as error:
        raise HTTPException(status_code=400, detail=str(error))

    # Stored responses live in the gateway's shared AWS account, so a
    # continuation is only allowed from the key that created the response.
    # Not-owned and unknown IDs get the same answer.
    previous_id = body.get("previous_response_id")
    if previous_id is not None:
        if not isinstance(previous_id, str) or not await response_ownership.is_owner(
            previous_id, token.id
        ):
            raise HTTPException(
                status_code=404, detail="previous_response_id not found"
            )
    if body.get("conversation") is not None:
        # Conversation objects aren't tracked per key; use previous_response_id.
        raise HTTPException(
            status_code=400,
            detail="'conversation' is not supported; use previous_response_id",
        )

    # Keep this key's cached prefixes out of every other key's reach.
    scope_responses_cache(body, str(token.id))

    if stream:
        return StreamingResponse(
            _stream_responses(
                body=body,
                request_id=request_id,
                model=model,
                token=token,
                start_time=start_time,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    # Non-streaming passthrough
    try:
        response_data = await MantleClient.responses_passthrough(body)
    except httpx.HTTPStatusError as e:
        logger.error(
            "Bedrock Responses error: model=%s, status=%s",
            model,
            e.response.status_code,
        )
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Bedrock Responses API error: status {e.response.status_code}",
        )

    await _record_owner(body, response_data, token)

    usage = _usage_from_response(response_data.get("usage") or {})
    background_tasks.create_task(
        record_usage(
            token_id=token.id,
            user_id=token.user_id,
            model=model,
            request_id=request_id,
            prompt_tokens=usage["non_cached_prompt"],
            completion_tokens=usage["completion"],
            cache_creation_input_tokens=usage["cache_write"],
            cache_read_input_tokens=usage["cached"],
            service_tier=response_data.get("service_tier") or body.get("service_tier"),
        ),
        task_name=f"record_usage_{request_id}",
    )

    duration = time.time() - start_time
    cache_info = ""
    if usage["cache_write"]:
        cache_info += f", cache_write={usage['cache_write']}"
    if usage["cached"]:
        cache_info += f", cached={usage['cached']}"
    logger.info(
        f"Responses successful: duration={round(duration, 3)}s, "
        f"prompt={usage['non_cached_prompt']}, "
        f"completion={usage['completion']}{cache_info}"
    )

    return JSONResponse(content=response_data)


async def _stream_responses(
    body: Dict[str, Any],
    request_id: str,
    model: str,
    token: APIToken,
    start_time: float,
) -> AsyncGenerator[bytes, None]:
    """Forward native Bedrock Responses SSE verbatim, billing from usage events.

    The raw SSE bytes are passed through unchanged; we also buffer line-by-line
    to find the ``response.completed`` / ``response.incomplete`` event and read
    its usage object for billing — without altering the client-facing stream.
    """
    settings = get_settings()
    usage = {
        "non_cached_prompt": 0,
        "completion": 0,
        "cached": 0,
        "cache_write": 0,
    }
    buffer = ""
    last_heartbeat = time.time()
    usage_recorded = False
    served_tier = body.get("service_tier")
    usage_fallback = StreamUsageFallback()

    def _record():
        """Record usage once, on any exit path (incl. client disconnect)."""
        nonlocal usage_recorded
        if usage_recorded:
            return
        # No response.completed seen (client left first): bill what streamed.
        usage["non_cached_prompt"], usage["completion"] = usage_fallback.resolve(
            usage["non_cached_prompt"], usage["completion"], body
        )
        if not any(usage.values()):
            return
        usage_recorded = True
        background_tasks.create_task(
            record_usage(
                token_id=token.id,
                user_id=token.user_id,
                model=model,
                request_id=request_id,
                prompt_tokens=usage["non_cached_prompt"],
                completion_tokens=usage["completion"],
                cache_creation_input_tokens=usage["cache_write"],
                cache_read_input_tokens=usage["cached"],
                service_tier=served_tier,
            ),
            task_name=f"record_usage_{request_id}",
        )

    try:
        async for raw in with_heartbeat(
            MantleClient.responses_passthrough_stream(body),
            settings.STREAM_HEARTBEAT_INTERVAL,
        ):
            if raw is HEARTBEAT:
                yield b": heartbeat\n\n"
                last_heartbeat = time.time()
                continue
            # Parse usage before yielding: if the client disconnects while the
            # final chunk is suspended at yield, the finally block can still bill it.
            last_heartbeat = time.time()

            # Sniff usage from completed/incomplete events without mutating output
            try:
                buffer += raw.decode("utf-8", errors="replace")
            except Exception:
                buffer = ""
                continue
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                etype = event.get("type")
                if etype == "response.created":
                    await _record_owner(body, event.get("response") or {}, token)
                if (
                    isinstance(etype, str)
                    and etype.endswith(".delta")
                    and isinstance(event.get("delta"), str)
                ):
                    usage_fallback.add_output(event["delta"])
                if etype in ("response.completed", "response.incomplete"):
                    usage_fallback.final_usage_seen = True
                    resp_obj = event.get("response") or {}
                    usage = _usage_from_response(resp_obj.get("usage") or {})
                    if resp_obj.get("service_tier"):
                        served_tier = resp_obj["service_tier"]

            # Forward upstream bytes unchanged after local accounting.
            yield raw

            # Heartbeat to keep idle connections alive
            if time.time() - last_heartbeat > settings.STREAM_HEARTBEAT_INTERVAL:
                yield b": heartbeat\n\n"
                last_heartbeat = time.time()

    except httpx.HTTPStatusError as e:
        logger.error(
            "Bedrock Responses stream error: model=%s, status=%s",
            model,
            e.response.status_code,
        )
        err = {
            "type": "error",
            "error": {
                "type": "server_error",
                "message": f"Bedrock Responses API error: status {e.response.status_code}",
            },
        }
        yield f"event: error\ndata: {json.dumps(err)}\n\n".encode("utf-8")
        return
    except Exception as error:
        logger.error(
            "Bedrock Responses streaming failed: model=%s, error_type=%s",
            model,
            type(error).__name__,
        )
        err = {
            "type": "error",
            "error": {"type": "server_error", "message": "Internal server error"},
        }
        yield f"event: error\ndata: {json.dumps(err)}\n\n".encode("utf-8")
        return
    finally:
        # Record usage on every exit path — normal completion, client
        # disconnect, or a mid-stream error after tokens were produced.
        _record()

    duration = time.time() - start_time
    cache_info = ""
    if usage["cache_write"]:
        cache_info += f", cache_write={usage['cache_write']}"
    if usage["cached"]:
        cache_info += f", cached={usage['cached']}"
    logger.info(
        f"Responses streaming successful: duration={round(duration, 3)}s, "
        f"prompt={usage['non_cached_prompt']}, "
        f"completion={usage['completion']}{cache_info}"
    )

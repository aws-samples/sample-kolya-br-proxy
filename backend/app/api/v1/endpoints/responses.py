"""
OpenAI Responses API endpoint (native passthrough for AWS mantle).

Mantle-served OpenAI models (see the mantle_models registry) go through the
**OpenAI Responses API**. The OpenAI-compatible ``/v1/chat/completions`` and the
Anthropic ``/v1/messages`` endpoints translate to/from the Responses format,
which necessarily flattens Responses-only features (built-in tools, multimodal
output, etc.).

This endpoint instead forwards a *native* Responses request body to mantle
verbatim and returns the native response, so clients that speak the Responses
API get mantle's full capability surface with no lossy conversion. It is the
only path that will transparently gain new mantle features (e.g. image
generation) the moment AWS enables them — no code change required.

The request body is accepted as an open JSON object (not a strict schema) for
exactly that reason: unknown/new Responses fields pass straight through.
"""

import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Dict

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_token
from app.api.v1.endpoints.chat import record_usage
from app.core.config import get_settings
from app.core.database import get_db
from app.models.model import Model
from app.models.token import APIToken
from app.services.background_tasks import BackgroundTaskManager
from app.services.mantle_client import MantleClient
from app.services.mantle_models import (
    get_mantle_model_regions,
    is_openai_mantle_model,
)

router = APIRouter()
logger = logging.getLogger(__name__)
background_tasks = BackgroundTaskManager()


def _usage_from_response(usage: Dict[str, Any]) -> Dict[str, int]:
    """Extract billing token counts from a Responses ``usage`` object.

    Returns (non_cached_prompt, completion, cached) — input_tokens reported by
    the Responses API includes cached tokens, so bill only the non-cached part.
    """
    prompt = usage.get("input_tokens", 0) or 0
    completion = usage.get("output_tokens", 0) or 0
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0) or 0
    return {
        "non_cached_prompt": max(0, prompt - cached),
        "completion": completion,
        "cached": cached,
    }


@router.post("/responses")
async def create_response(
    http_request: Request,
    token: APIToken = Depends(get_current_token),
    db: AsyncSession = Depends(get_db),
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

    model = body.get("model")
    if not model or not isinstance(model, str):
        raise HTTPException(status_code=400, detail="Missing 'model' in request body")

    stream = bool(body.get("stream", False))

    logger.info(
        f"Responses request: model={model}, stream={stream}, "
        f"request_id={request_id}, token_id={token.id}",
    )

    # Only mantle models have a Responses backend.
    if not is_openai_mantle_model(model):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Model '{model}' is not available on the Responses API. "
                f"Available models: {sorted(get_mantle_model_regions())}; "
                "use /v1/chat/completions for other models."
            ),
        )

    # Quota + model access (same checks as the other gateway endpoints)
    from sqlalchemy import select
    from app.services.quota import enforce_quota

    await enforce_quota(token, db)

    result = await db.execute(
        select(Model).where(
            Model.token_id == token.id,
            Model.is_active,
            ~Model.is_deleted,
        )
    )
    allowed_model_names = [m.model_name for m in result.scalars().all()]
    if model not in allowed_model_names:
        raise HTTPException(
            status_code=403,
            detail=f"Token does not have access to model: {model}. "
            f"Allowed models: {allowed_model_names}",
        )

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
        logger.error(f"mantle Responses error: {e}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"mantle API error: status {e.response.status_code}",
        )

    usage = _usage_from_response(response_data.get("usage") or {})
    background_tasks.create_task(
        record_usage(
            token_id=token.id,
            user_id=token.user_id,
            model=model,
            request_id=request_id,
            prompt_tokens=usage["non_cached_prompt"],
            completion_tokens=usage["completion"],
            cache_read_input_tokens=usage["cached"],
        ),
        task_name=f"record_usage_{request_id}",
    )

    duration = time.time() - start_time
    cache_info = f", cached={usage['cached']}" if usage["cached"] else ""
    logger.info(
        f"Responses successful: request_id={request_id}, "
        f"duration={round(duration, 3)}s, prompt={usage['non_cached_prompt']}, "
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
    """Forward mantle's native Responses SSE verbatim, billing from usage events.

    The raw SSE bytes are passed through unchanged; we also buffer line-by-line
    to find the ``response.completed`` / ``response.incomplete`` event and read
    its usage object for billing — without altering the client-facing stream.
    """
    settings = get_settings()
    usage = {"non_cached_prompt": 0, "completion": 0, "cached": 0}
    buffer = ""
    last_heartbeat = time.time()
    usage_recorded = False

    def _record():
        """Record usage once, on any exit path (incl. client disconnect)."""
        nonlocal usage_recorded
        if usage_recorded or not (usage["non_cached_prompt"] or usage["completion"]):
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
                cache_read_input_tokens=usage["cached"],
            ),
            task_name=f"record_usage_{request_id}",
        )

    try:
        async for raw in MantleClient.responses_passthrough_stream(body):
            # Forward upstream bytes unchanged
            yield raw
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
                if etype in ("response.completed", "response.incomplete"):
                    resp_obj = event.get("response") or {}
                    usage = _usage_from_response(resp_obj.get("usage") or {})

            # Heartbeat to keep idle connections alive
            if time.time() - last_heartbeat > settings.STREAM_HEARTBEAT_INTERVAL:
                yield b": heartbeat\n\n"
                last_heartbeat = time.time()

    except httpx.HTTPStatusError as e:
        logger.error(
            f"mantle Responses stream error: model={model}, "
            f"request_id={request_id}, status={e.response.status_code}",
            exc_info=True,
        )
        err = {
            "type": "error",
            "error": {
                "type": "server_error",
                "message": f"mantle API error: status {e.response.status_code}",
            },
        }
        yield f"event: error\ndata: {json.dumps(err)}\n\n".encode("utf-8")
        return
    except Exception as e:
        logger.error(
            f"mantle Responses streaming failed: model={model}, "
            f"request_id={request_id}, error={e}",
            exc_info=True,
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
    cache_info = f", cached={usage['cached']}" if usage["cached"] else ""
    logger.info(
        f"Responses streaming successful: request_id={request_id}, "
        f"duration={round(duration, 3)}s, prompt={usage['non_cached_prompt']}, "
        f"completion={usage['completion']}{cache_info}"
    )

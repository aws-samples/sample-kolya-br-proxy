"""
Gemini native API compatible endpoints.

Proxies requests from the Gemini SDK (google-generativeai) to the real
Google Gemini API.  Request and response bodies are passed through
verbatim — only authentication is swapped (proxy token → real API key).
"""

import json
import logging
import time
import uuid
from decimal import Decimal
from typing import AsyncGenerator

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_token_from_gemini_key
from app.core.config import get_settings
from app.core.database import get_db
from app.models.model import Model
from app.models.token import APIToken
from app.models.usage import UsageRecord
from app.services.background_tasks import BackgroundTaskManager
from app.services.pricing import ModelPricing

router = APIRouter()
logger = logging.getLogger(__name__)
background_tasks = BackgroundTaskManager()

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


# ---------------------------------------------------------------------------
# Helper: extract model name from path param
# ---------------------------------------------------------------------------


def _normalize_model(model_path: str) -> str:
    """Extract clean model name from the path parameter.

    The Gemini SDK sends paths like ``gemini-2.5-flash`` or
    ``models/gemini-2.5-flash``.  We always strip the ``models/`` prefix
    so it matches the ``model_name`` stored in the DB.
    """
    return model_path.removeprefix("models/")


# ---------------------------------------------------------------------------
# Helper: validate token access (quota + model permission)
# ---------------------------------------------------------------------------


async def _validate_access(
    token: APIToken,
    model_name: str,
    db: AsyncSession,
) -> None:
    """Check quota and model permission.  Raises HTTPException on failure."""
    # Quota check
    result = await db.execute(
        select(func.sum(UsageRecord.cost_usd)).where(UsageRecord.token_id == token.id)
    )
    total_used = result.scalar() or Decimal("0.00")
    token.calculate_used_usd(total_used)

    if token.is_quota_exceeded:
        raise HTTPException(
            status_code=429,
            detail=f"Token quota exceeded. Used: ${total_used:.2f}, Quota: ${token.quota_usd:.2f}",
        )

    # Model permission check
    result = await db.execute(
        select(Model).where(
            Model.token_id == token.id,
            Model.is_active,
            ~Model.is_deleted,
        )
    )
    token_models = result.scalars().all()
    allowed = [m.model_name for m in token_models]

    if not allowed:
        raise HTTPException(
            status_code=403, detail="Token does not have access to any models"
        )

    if model_name not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Token does not have access to model: {model_name}. Allowed models: {allowed}",
        )


# ---------------------------------------------------------------------------
# Helper: record usage (background)
# ---------------------------------------------------------------------------


async def _record_usage(
    token: APIToken,
    model: str,
    request_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
):
    """Record usage to DB (runs as background task)."""
    from app.core.database import get_db as _get_db

    non_cached_prompt = max(0, prompt_tokens - cached_tokens)

    async for db in _get_db():
        try:
            pricing_service = ModelPricing(db=db)
            cost_usd = await pricing_service.calculate_cost(
                model=model,
                prompt_tokens=non_cached_prompt,
                completion_tokens=completion_tokens,
                cache_read_input_tokens=cached_tokens,
            )

            usage_record = UsageRecord(
                user_id=token.user_id,
                token_id=token.id,
                model=model,
                prompt_tokens=non_cached_prompt,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                cache_read_input_tokens=cached_tokens,
                cost_usd=cost_usd,
                request_id=request_id,
            )
            db.add(usage_record)
            await db.commit()

            logger.info(
                "Gemini usage recorded",
                extra={"request_id": request_id, "cost_usd": round(cost_usd, 6)},
            )
        except ValueError as e:
            logger.error(f"Pricing not available for model {model}: {e}")
            await db.rollback()
        except Exception as e:
            logger.error(f"Failed to record Gemini usage: {e}", exc_info=True)
            await db.rollback()
        finally:
            await db.close()
        break


# ---------------------------------------------------------------------------
# POST /v1beta/models/{model}:generateContent
# ---------------------------------------------------------------------------


@router.api_route(
    "/models/{model_path:path}:generateContent",
    methods=["POST"],
)
async def generate_content(
    model_path: str,
    request: Request,
    token: APIToken = Depends(get_current_token_from_gemini_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Non-streaming Gemini generateContent proxy.

    Authenticates using the proxy token, then forwards the raw request body
    to the real Google Gemini API and returns the response as-is.
    """
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="Gemini API key is not configured")

    model_name = _normalize_model(model_path)
    request_id = f"gemini-{uuid.uuid4().hex[:16]}"
    start_time = time.time()

    logger.info(
        f"Gemini generateContent: model={model_name}, "
        f"request_id={request_id}, token_id={token.id}"
    )

    await _validate_access(token, model_name, db)

    # Read raw body and forward
    raw_body = await request.body()
    url = (
        f"{GEMINI_BASE_URL}/{model_name}:generateContent?key={settings.GEMINI_API_KEY}"
    )

    try:
        async with httpx.AsyncClient(timeout=3600) as client:
            resp = await client.post(
                url,
                headers={"Content-Type": "application/json"},
                content=raw_body,
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Upstream Gemini API timed out")
    except httpx.ConnectError as e:
        raise HTTPException(status_code=502, detail="Cannot reach Gemini API")

    # Forward error responses as-is
    if resp.status_code != 200:
        logger.error(
            f"Gemini API error: status={resp.status_code}, body={resp.text[:500]}"
        )
        return JSONResponse(content=resp.json(), status_code=resp.status_code)

    # Parse response for usage billing
    resp_data = resp.json()
    usage_meta = resp_data.get("usageMetadata") or {}
    prompt_tokens = usage_meta.get("promptTokenCount", 0)
    completion_tokens = usage_meta.get("candidatesTokenCount", 0)
    cached_tokens = usage_meta.get("cachedContentTokenCount", 0)

    background_tasks.create_task(
        _record_usage(
            token=token,
            model=model_name,
            request_id=request_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
        ),
        task_name=f"gemini_usage_{request_id}",
    )

    duration = time.time() - start_time
    cache_info = f", cached={cached_tokens}" if cached_tokens else ""
    logger.info(
        f"Gemini generateContent done: request_id={request_id}, "
        f"duration={round(duration, 3)}s, "
        f"prompt={prompt_tokens}, completion={completion_tokens}{cache_info}"
    )

    return JSONResponse(content=resp_data, status_code=200)


# ---------------------------------------------------------------------------
# POST /v1beta/models/{model}:streamGenerateContent
# ---------------------------------------------------------------------------


@router.api_route(
    "/models/{model_path:path}:streamGenerateContent",
    methods=["POST"],
)
async def stream_generate_content(
    model_path: str,
    request: Request,
    token: APIToken = Depends(get_current_token_from_gemini_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Streaming Gemini streamGenerateContent proxy.

    Authenticates, then streams the upstream SSE response through to the
    client.  Usage is extracted from the final chunk for billing.
    """
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="Gemini API key is not configured")

    model_name = _normalize_model(model_path)
    request_id = f"gemini-{uuid.uuid4().hex[:16]}"
    start_time = time.time()

    logger.info(
        f"Gemini streamGenerateContent: model={model_name}, "
        f"request_id={request_id}, token_id={token.id}"
    )

    await _validate_access(token, model_name, db)

    raw_body = await request.body()
    url = (
        f"{GEMINI_BASE_URL}/{model_name}:streamGenerateContent"
        f"?alt=sse&key={settings.GEMINI_API_KEY}"
    )

    return StreamingResponse(
        _stream_proxy(
            url=url,
            raw_body=raw_body,
            model_name=model_name,
            request_id=request_id,
            token=token,
            start_time=start_time,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


async def _stream_proxy(
    url: str,
    raw_body: bytes,
    model_name: str,
    request_id: str,
    token: APIToken,
    start_time: float,
) -> AsyncGenerator[str, None]:
    """Forward the SSE stream from Google, extracting usage along the way."""
    prompt_tokens = 0
    completion_tokens = 0
    cached_tokens = 0

    try:
        async with httpx.AsyncClient(timeout=3600) as client:
            async with client.stream(
                "POST",
                url,
                headers={"Content-Type": "application/json"},
                content=raw_body,
            ) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    logger.error(
                        f"Gemini stream error: status={resp.status_code}, "
                        f"body={error_body[:500].decode(errors='replace')}"
                    )
                    yield f"data: {error_body.decode(errors='replace')}\n\n"
                    return

                async for line in resp.aiter_lines():
                    # Forward every line as-is (SSE format)
                    yield f"{line}\n"

                    # Extract usage from data lines for billing
                    if line.startswith("data: "):
                        try:
                            chunk_data = json.loads(line[6:])
                            usage_meta = chunk_data.get("usageMetadata") or {}
                            if usage_meta.get("totalTokenCount"):
                                prompt_tokens = usage_meta.get("promptTokenCount", 0)
                                completion_tokens = usage_meta.get(
                                    "candidatesTokenCount", 0
                                )
                                cached_tokens = usage_meta.get(
                                    "cachedContentTokenCount", 0
                                )
                        except (json.JSONDecodeError, TypeError):
                            pass

    except httpx.TimeoutException:
        logger.error(f"Gemini stream timed out: request_id={request_id}")
        yield 'data: {"error": {"message": "Upstream timeout"}}\n\n'
    except Exception as e:
        logger.error(
            f"Gemini streaming failed: model={model_name}, "
            f"request_id={request_id}, error={e}",
            exc_info=True,
        )
        yield 'data: {"error": {"message": "Internal server error"}}\n\n'

    # Record usage
    background_tasks.create_task(
        _record_usage(
            token=token,
            model=model_name,
            request_id=request_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
        ),
        task_name=f"gemini_usage_{request_id}",
    )

    duration = time.time() - start_time
    cache_info = f", cached={cached_tokens}" if cached_tokens else ""
    logger.info(
        f"Gemini streaming done: request_id={request_id}, "
        f"duration={round(duration, 3)}s, "
        f"prompt={prompt_tokens}, completion={completion_tokens}{cache_info}"
    )

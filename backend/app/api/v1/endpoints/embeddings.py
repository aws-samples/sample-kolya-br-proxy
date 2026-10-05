# pyright: reportMissingImports=false
"""OpenAI-compatible ``POST /v1/embeddings`` for text and inline images.

Images arrive inline in the request (data URIs), exactly like images sent to
chat models; the gateway never fetches URLs or stores media.
"""

import uuid

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_token_flexible_streaming
from app.core.config import get_settings
from app.models.token import APIToken
from app.schemas.embeddings import (
    CanonicalEmbeddingInput,
    CanonicalEmbeddingRequest,
    OpenAIEmbeddingRequest,
)
from app.services.embedding_inputs import EmbeddingInputError, parse_openai_input
from app.services.embedding_models import EmbeddingValidationError
from app.services.embedding_usage import record_embedding_usage
from app.services.embeddings import EmbeddingResponseError, EmbeddingService
from app.services.model_access import authorize_embedding_model

router = APIRouter()
embedding_service = EmbeddingService()


def _decoded_size(value: str) -> int:
    """Decoded byte length of a base64 string, without decoding it again."""
    return len(value.rstrip("=")) * 3 // 4


def validate_image_sizes(inputs: list[CanonicalEmbeddingInput]) -> None:
    """Reject any inline image above ``KBR_EMBEDDING_MAX_IMAGE_BYTES`` with 413."""
    limit = get_settings().EMBEDDING_MAX_IMAGE_BYTES
    for position, item in enumerate(inputs):
        if item.type != "image" or not item.image_base64:
            continue
        size = _decoded_size(item.image_base64)
        if size > limit:
            raise HTTPException(
                status_code=413,
                detail={
                    "message": (
                        f"input[{position}]: image is {size} bytes; "
                        f"the limit is {limit} bytes per image"
                    ),
                    "code": "image_too_large",
                    "limit_bytes": limit,
                },
            )


def _upstream_error(exc: ClientError) -> HTTPException:
    code = exc.response.get("Error", {}).get("Code", "Unknown")
    status_by_code = {
        "ValidationException": 400,
        "AccessDeniedException": 403,
        "ResourceNotFoundException": 404,
        "ThrottlingException": 429,
        "ServiceQuotaExceededException": 429,
        "ModelNotReadyException": 503,
        "ServiceUnavailableException": 503,
        "ModelTimeoutException": 504,
    }
    message_by_code = {
        "ValidationException": "Invalid embedding request",
        "AccessDeniedException": "Access denied to the embedding model",
        "ResourceNotFoundException": "Embedding model not found",
        "ThrottlingException": "Embedding rate limit exceeded",
        "ServiceQuotaExceededException": "Embedding service quota exceeded",
        "ModelNotReadyException": "Embedding model is not ready",
        "ServiceUnavailableException": "Embedding service is unavailable",
        "ModelTimeoutException": "Embedding model timed out",
    }
    return HTTPException(
        status_code=status_by_code.get(code, 502),
        detail=message_by_code.get(code, "Embedding upstream request failed"),
    )


@router.post("/embeddings")
async def create_embedding(
    request_data: OpenAIEmbeddingRequest,
    token: APIToken = Depends(get_current_token_flexible_streaming),
):
    """Embed texts and inline images; ``data[i]`` corresponds to ``input[i]``."""
    try:
        inputs = parse_openai_input(request_data.input)
    except EmbeddingInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    validate_image_sizes(inputs)
    model = await authorize_embedding_model(token, request_data.model)
    canonical = CanonicalEmbeddingRequest(
        model=model,
        inputs=inputs,
        dimensions=request_data.dimensions,
        purpose=request_data.purpose,
    )
    request_id = f"emb-{uuid.uuid4().hex[:24]}"

    try:
        result = await embedding_service.embed(canonical)
    except EmbeddingValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmbeddingResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ClientError as exc:
        raise _upstream_error(exc) from exc

    await record_embedding_usage(
        token=token,
        model=model,
        request_id=request_id,
        request=canonical,
        result=result,
    )
    return {
        "object": "list",
        "model": model,
        "data": [
            {
                "object": "embedding",
                "index": vector.index,
                "embedding": vector.embedding,
            }
            for vector in result.vectors
        ],
        "usage": {
            "prompt_tokens": result.input_tokens,
            "total_tokens": result.input_tokens,
        },
    }

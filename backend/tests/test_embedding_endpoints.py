# pyright: reportMissingImports=false, reportAttributeAccessIssue=false, reportArgumentType=false
"""Public contract of ``POST /v1/embeddings`` for text and inline images."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import embeddings
from app.schemas.embeddings import (
    CanonicalEmbeddingResult,
    EmbeddingVector,
    OpenAIEmbeddingRequest,
)
from app.services.embedding_models import NOVA_MODEL_ID

JPEG = "data:image/jpeg;base64,/9j/4AAQ"


def _token():
    return SimpleNamespace(id=uuid4(), user_id=uuid4(), name="test")


async def _call(body, *, result=None, limit=20 * 1024 * 1024):
    embed = AsyncMock(return_value=result)
    authorize = AsyncMock(return_value=NOVA_MODEL_ID)
    record = AsyncMock()
    settings = SimpleNamespace(EMBEDDING_MAX_IMAGE_BYTES=limit)
    with (
        patch.object(embeddings, "authorize_embedding_model", authorize),
        patch.object(embeddings.embedding_service, "embed", embed),
        patch.object(embeddings, "record_embedding_usage", record),
        patch.object(embeddings, "get_settings", return_value=settings),
    ):
        response = await embeddings.create_embedding(
            OpenAIEmbeddingRequest(**body), token=_token()
        )
    return response, embed, record


@pytest.mark.asyncio
async def test_text_and_keyframe_images_return_openai_shape_in_order():
    result = CanonicalEmbeddingResult(
        vectors=[
            EmbeddingVector(index=0, embedding=[0.1, 0.2]),
            EmbeddingVector(index=1, embedding=[0.3, 0.4]),
        ],
        input_tokens=5,
    )
    response, embed, record = await _call(
        {
            "model": NOVA_MODEL_ID,
            "dimensions": 1024,
            "input": ["a runner", {"type": "image_url", "image_url": {"url": JPEG}}],
        },
        result=result,
    )

    assert response == {
        "object": "list",
        "model": NOVA_MODEL_ID,
        "data": [
            {"object": "embedding", "index": 0, "embedding": [0.1, 0.2]},
            {"object": "embedding", "index": 1, "embedding": [0.3, 0.4]},
        ],
        "usage": {"prompt_tokens": 5, "total_tokens": 5},
    }
    sent = embed.await_args_list[0].args[0]
    assert [i.type for i in sent.inputs] == ["text", "image"]
    assert sent.inputs[1].image_format == "jpeg"
    assert sent.dimensions == 1024
    record.assert_awaited_once()


@pytest.mark.asyncio
async def test_bad_image_is_rejected_before_bedrock_or_billing():
    with pytest.raises(HTTPException) as exc_info:
        await _call(
            {"model": NOVA_MODEL_ID, "input": ["ok", "data:image/png;base64,***"]}
        )
    assert exc_info.value.status_code == 400
    assert "input[1]" in exc_info.value.detail


@pytest.mark.asyncio
async def test_oversized_image_returns_413_with_position():
    with pytest.raises(HTTPException) as exc_info:
        await _call({"model": NOVA_MODEL_ID, "input": [JPEG]}, limit=3)
    assert exc_info.value.status_code == 413
    assert exc_info.value.detail["code"] == "image_too_large"
    assert exc_info.value.detail["message"].startswith("input[0]")


def test_token_id_arrays_are_rejected_by_schema():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OpenAIEmbeddingRequest(model=NOVA_MODEL_ID, input=[[1, 2, 3]])

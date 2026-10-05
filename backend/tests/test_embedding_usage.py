# pyright: reportMissingImports=false, reportAttributeAccessIssue=false
"""Usage records for embeddings carry per-modality units and exact cost."""

from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.models.token import APIToken
from app.schemas.embeddings import (
    CanonicalEmbeddingInput,
    CanonicalEmbeddingRequest,
    CanonicalEmbeddingResult,
    EmbeddingVector,
)
from app.services import embedding_usage
from app.services.embedding_models import NOVA_MODEL_ID


class _FakeDb:
    def __init__(self):
        self.added = []
        self.add = self.added.append
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.close = AsyncMock()


async def _record(db, prices, request, result):
    async def fake_get_db():
        yield db

    with (
        patch.object(embedding_usage, "get_db", fake_get_db),
        patch.object(
            embedding_usage,
            "get_settings",
            return_value=SimpleNamespace(EMBEDDING_REGION="us-east-1"),
        ),
        patch.object(
            embedding_usage,
            "get_embedding_prices",
            AsyncMock(return_value=(prices, "us-east-1" if prices else None)),
        ),
        patch("app.services.alert.check_alerts_for_usage", AsyncMock()),
    ):
        await embedding_usage.record_embedding_usage(
            token=cast(APIToken, SimpleNamespace(id=uuid4(), user_id=uuid4())),
            model=NOVA_MODEL_ID,
            request_id="emb-1",
            request=request,
            result=result,
        )
    assert len(db.added) == 1
    return db.added[0]


@pytest.mark.asyncio
async def test_keyframe_images_record_units_and_exact_cost():
    image = CanonicalEmbeddingInput(
        type="image", image_base64="aW1n", image_format="jpeg"
    )
    request = CanonicalEmbeddingRequest(
        model=NOVA_MODEL_ID, inputs=[image, image, image]
    )
    result = CanonicalEmbeddingResult(
        vectors=[EmbeddingVector(index=i, embedding=[1.0]) for i in range(3)]
    )

    usage = await _record(
        _FakeDb(), {"standard_image": Decimal("0.00006")}, request, result
    )

    # 3 x $0.00006 — would have rounded to $0.0002 at four decimals.
    assert usage.cost_usd == Decimal("0.0001800000")
    assert usage.note is None
    assert usage.request_metadata["billable_units"] == {"standard_image": "3"}
    assert usage.request_metadata["input_types"] == ["image", "image", "image"]
    assert usage.request_metadata["pricing_region"] == "us-east-1"
    assert "image_base64" not in str(usage.request_metadata)


@pytest.mark.asyncio
async def test_tiny_cost_is_not_rounded_away_and_missing_prices_are_noted():
    request = CanonicalEmbeddingRequest(
        model=NOVA_MODEL_ID,
        inputs=[CanonicalEmbeddingInput(type="text", text="hello")],
    )
    result = CanonicalEmbeddingResult(
        vectors=[EmbeddingVector(embedding=[1])], input_tokens=10
    )

    priced = await _record(
        _FakeDb(), {"text_token": Decimal("0.000000135")}, request, result
    )
    # 10 tokens x $0.000000135 = $0.00000135 — kept, not rounded to 0.0000.
    assert priced.cost_usd == Decimal("0.0000013500")
    assert "cost_usd_exact" not in priced.request_metadata

    unpriced = await _record(_FakeDb(), {}, request, result)
    assert unpriced.note == "embedding_pricing_missing"
    assert unpriced.request_metadata["missing_price_units"] == ["text_token"]

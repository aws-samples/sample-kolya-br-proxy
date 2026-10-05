# pyright: reportMissingImports=false
"""Per-modality metering and cost for text and image embeddings."""

from decimal import Decimal

from app.schemas.embeddings import (
    CanonicalEmbeddingInput,
    CanonicalEmbeddingRequest,
    CanonicalEmbeddingResult,
    EmbeddingVector,
)
from app.services.embedding_billing import meter_embedding, price_embedding
from app.services.embedding_models import MARENGO_MODEL_ID, NOVA_MODEL_ID

NOVA_PRICES = {
    "text_token": Decimal("0.000000135"),
    "standard_image": Decimal("0.00006"),
}
MARENGO_PRICES = {"text_request": Decimal("0.00007"), "image": Decimal("0.0001")}
TEXT = CanonicalEmbeddingInput(type="text", text="a")
IMAGE = CanonicalEmbeddingInput(type="image", image_base64="aW1n", image_format="png")


def _meter(model, inputs, tokens=0):
    request = CanonicalEmbeddingRequest(model=model, inputs=inputs)
    vectors = [EmbeddingVector(index=i, embedding=[1.0]) for i in range(len(inputs))]
    return meter_embedding(
        request, CanonicalEmbeddingResult(vectors=vectors, input_tokens=tokens)
    )


def test_nova_bills_text_tokens_and_standard_images():
    metering = _meter(NOVA_MODEL_ID, [TEXT, IMAGE, IMAGE], tokens=1000)

    assert metering.units == {"text_token": Decimal(1000), "standard_image": Decimal(2)}
    # 1000 x 0.000000135 + 2 x 0.00006
    assert price_embedding(metering, NOVA_PRICES).total_usd == Decimal("0.000255")


def test_nova_text_without_token_count_is_flagged_not_guessed():
    metering = _meter(NOVA_MODEL_ID, [TEXT])
    assert metering.units == {}
    assert metering.unknown_units == ["text_token"]


def test_nova_images_only_need_no_token_count():
    metering = _meter(NOVA_MODEL_ID, [IMAGE])
    assert metering.units == {"standard_image": Decimal(1)}
    assert metering.unknown_units == []


def test_marengo_bills_text_requests_and_images():
    metering = _meter(MARENGO_MODEL_ID, [TEXT, TEXT, IMAGE])

    assert metering.units == {"image": Decimal(1), "text_request": Decimal(2)}
    assert price_embedding(metering, MARENGO_PRICES).total_usd == Decimal("0.00024")


def test_missing_unit_price_is_reported_and_excluded():
    cost = price_embedding(_meter(MARENGO_MODEL_ID, [TEXT]), {})
    assert cost.total_usd == Decimal(0)
    assert cost.missing_price_units == ["text_request"]

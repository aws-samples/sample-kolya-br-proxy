# pyright: reportMissingImports=false
"""Golden InvokeModel contracts for the two supported embedding models."""

import pytest

from app.schemas.embeddings import CanonicalEmbeddingInput
from app.services.embedding_models import (
    MARENGO_MODEL_ID,
    NOVA_MODEL_ID,
    EmbeddingValidationError,
    get_embedding_adapter,
)

TEXT = CanonicalEmbeddingInput(type="text", text="hello world")
IMAGE = CanonicalEmbeddingInput(type="image", image_base64="aW1n", image_format="jpeg")


def test_marengo_text_and_image_bodies():
    adapter = get_embedding_adapter(MARENGO_MODEL_ID)

    assert adapter.build_body(TEXT, None, None) == {
        "inputType": "text",
        "text": {"inputText": "hello world"},
    }
    assert adapter.build_body(IMAGE, 512, None) == {
        "inputType": "image",
        "image": {"mediaSource": {"base64String": "aW1n"}},
    }


def test_marengo_rejects_non_512_dimensions():
    with pytest.raises(EmbeddingValidationError, match="512"):
        get_embedding_adapter(MARENGO_MODEL_ID).build_body(TEXT, 1024, None)


def test_marengo_parses_single_vector():
    result = get_embedding_adapter(MARENGO_MODEL_ID).parse_response(
        {"data": [{"embedding": [0.25, -0.5]}]}
    )
    assert [v.embedding for v in result.vectors] == [[0.25, -0.5]]


def test_nova_text_body():
    body = get_embedding_adapter(NOVA_MODEL_ID).build_body(
        TEXT, 1024, "GENERIC_RETRIEVAL"
    )

    assert body == {
        "schemaVersion": "nova-multimodal-embed-v1",
        "taskType": "SINGLE_EMBEDDING",
        "singleEmbeddingParams": {
            "embeddingPurpose": "GENERIC_RETRIEVAL",
            "embeddingDimension": 1024,
            "text": {"truncationMode": "END", "value": "hello world"},
        },
    }


def test_nova_image_body_defaults_purpose_and_dimension():
    body = get_embedding_adapter(NOVA_MODEL_ID).build_body(IMAGE, None, None)

    assert body["singleEmbeddingParams"] == {
        "embeddingPurpose": "GENERIC_INDEX",
        "embeddingDimension": 3072,
        "image": {
            "format": "jpeg",
            "source": {"bytes": "aW1n"},
            "detailLevel": "STANDARD_IMAGE",
        },
    }


@pytest.mark.parametrize(
    ("dimensions", "purpose", "match"),
    [(512, None, "256, 384, 1024, or 3072"), (None, "VIDEO_RETRIEVAL", "purpose")],
)
def test_nova_rejects_unsupported_options(dimensions, purpose, match):
    with pytest.raises(EmbeddingValidationError, match=match):
        get_embedding_adapter(NOVA_MODEL_ID).build_body(TEXT, dimensions, purpose)


def test_only_two_embedding_models_are_registered():
    with pytest.raises(EmbeddingValidationError, match="not supported"):
        get_embedding_adapter("amazon.titan-embed-text-v2:0")


@pytest.mark.parametrize("count", ["not-a-number", None, 1.5, True])
def test_nova_malformed_token_count_keeps_vectors(count):
    result = get_embedding_adapter(NOVA_MODEL_ID).parse_response(
        {"embeddings": [{"embedding": [0.5]}], "inputTextTokenCount": count}
    )
    assert result.vectors[0].embedding == [0.5]
    assert result.input_tokens == 0


def test_nova_integer_token_count_is_reported():
    result = get_embedding_adapter(NOVA_MODEL_ID).parse_response(
        {"embeddings": [{"embedding": [0.5]}], "inputTextTokenCount": 7}
    )
    assert result.input_tokens == 7

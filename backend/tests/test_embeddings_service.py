# pyright: reportMissingImports=false
"""Behavior tests for the Bedrock InvokeModel embedding seam."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.schemas.embeddings import CanonicalEmbeddingInput, CanonicalEmbeddingRequest
from app.services.embedding_models import NOVA_MODEL_ID
from app.services.embeddings import EmbeddingResponseError, EmbeddingService


class _Body:
    def __init__(self, payload):
        self.payload = payload

    async def read(self):
        return json.dumps(self.payload).encode()


class _ClientContext:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, *_args):
        return False


def _response(payload, header_tokens=None):
    headers = {}
    if header_tokens is not None:
        headers["x-amzn-bedrock-input-token-count"] = str(header_tokens)
    return {"body": _Body(payload), "ResponseMetadata": {"HTTPHeaders": headers}}


def _service(*responses):
    client = SimpleNamespace(
        invoke_model=AsyncMock(
            side_effect=[r if "body" in r else _response(r) for r in responses]
        )
    )
    calls = []

    def make_client(service_name, **kwargs):
        calls.append((service_name, kwargs.get("region_name")))
        return _ClientContext(client)

    runtime = SimpleNamespace(
        session=SimpleNamespace(client=make_client),
        config=object(),
        _rate_limiter=SimpleNamespace(acquire=AsyncMock()),
        _semaphore=asyncio.Semaphore(2),
        # The chat resolver must not be consulted for embeddings.
        resolve_model=lambda model: (model, "us-west-2"),
    )
    return EmbeddingService(runtime=runtime), client, calls


@pytest.mark.asyncio
async def test_embed_mixes_text_and_image_in_input_order():
    service, client, calls = _service(
        {"embeddings": [{"embedding": [0.1]}], "inputTextTokenCount": 4},
        {"embeddings": [{"embedding": [0.2]}]},
    )

    result = await service.embed(
        CanonicalEmbeddingRequest(
            model=NOVA_MODEL_ID,
            inputs=[
                CanonicalEmbeddingInput(type="text", text="first"),
                CanonicalEmbeddingInput(
                    type="image", image_base64="aW1n", image_format="png"
                ),
            ],
            dimensions=1024,
        )
    )

    assert [(v.index, v.embedding) for v in result.vectors] == [(0, [0.1]), (1, [0.2])]
    assert result.input_tokens == 4
    bodies = [json.loads(c.kwargs["body"]) for c in client.invoke_model.await_args_list]
    assert bodies[0]["singleEmbeddingParams"]["text"]["value"] == "first"
    assert bodies[1]["singleEmbeddingParams"]["image"]["source"] == {"bytes": "aW1n"}
    # Routed to KBR_EMBEDDING_REGION (default us-east-1), not the chat resolver.
    assert calls == [("bedrock-runtime", "us-east-1"), ("bedrock-runtime", "us-east-1")]


@pytest.mark.asyncio
async def test_more_than_one_vector_per_input_is_rejected():
    service, _client, _calls = _service(
        {"embeddings": [{"embedding": [0.1]}, {"embedding": [0.2]}]}
    )

    with pytest.raises(EmbeddingResponseError, match="one embedding per input"):
        await service.embed(
            CanonicalEmbeddingRequest(
                model=NOVA_MODEL_ID,
                inputs=[CanonicalEmbeddingInput(type="text", text="x")],
            )
        )


@pytest.mark.asyncio
async def test_nova_text_tokens_come_from_response_header():
    # Live Nova responses carry the count only in this header, not the body.
    service, _client, _calls = _service(
        _response({"embeddings": [{"embedding": [0.1]}]}, header_tokens=7),
        _response({"embeddings": [{"embedding": [0.2]}]}, header_tokens="n/a"),
    )

    result = await service.embed(
        CanonicalEmbeddingRequest(
            model=NOVA_MODEL_ID,
            inputs=[
                CanonicalEmbeddingInput(type="text", text="a runner on a track"),
                CanonicalEmbeddingInput(type="text", text="malformed header"),
            ],
        )
    )

    assert result.input_tokens == 7


@pytest.mark.asyncio
async def test_embedding_region_is_configurable(monkeypatch):
    from app.services import embeddings as embeddings_module

    monkeypatch.setattr(
        embeddings_module,
        "get_settings",
        lambda: SimpleNamespace(EMBEDDING_REGION="eu-west-1"),
    )
    service, _client, calls = _service({"embeddings": [{"embedding": [0.1]}]})

    await service.embed(
        CanonicalEmbeddingRequest(
            model=NOVA_MODEL_ID,
            inputs=[CanonicalEmbeddingInput(type="text", text="x")],
        )
    )

    assert calls == [("bedrock-runtime", "eu-west-1")]

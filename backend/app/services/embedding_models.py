# pyright: reportMissingImports=false
"""Exact Bedrock InvokeModel payloads for the gateway's two embedding models.

Both models are multimodal: text and images map into one shared vector space,
so a text query can retrieve images and vice versa.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.schemas.embeddings import (
    CanonicalEmbeddingInput,
    CanonicalEmbeddingResult,
    EmbeddingVector,
)

MARENGO_MODEL_ID = "twelvelabs.marengo-embed-3-0-v1:0"
NOVA_MODEL_ID = "amazon.nova-2-multimodal-embeddings-v1:0"
SUPPORTED_EMBEDDING_MODELS = frozenset({MARENGO_MODEL_ID, NOVA_MODEL_ID})


class EmbeddingValidationError(ValueError):
    """The requested model or embedding payload is unsupported."""


class EmbeddingModelAdapter(ABC):
    model_id: str

    @abstractmethod
    def build_body(
        self,
        item: CanonicalEmbeddingInput,
        dimensions: int | None,
        purpose: str | None,
    ) -> dict[str, Any]:
        """Build one InvokeModel body."""

    @abstractmethod
    def parse_response(self, payload: Any) -> CanonicalEmbeddingResult:
        """Normalize one InvokeModel response."""


def _embedding(entry: Any, model: str) -> list[float]:
    if not isinstance(entry, dict) or not isinstance(entry.get("embedding"), list):
        raise EmbeddingValidationError(f"{model} response did not contain an embedding")
    return entry["embedding"]


class MarengoEmbeddingAdapter(EmbeddingModelAdapter):
    model_id = MARENGO_MODEL_ID

    def build_body(
        self,
        item: CanonicalEmbeddingInput,
        dimensions: int | None,
        purpose: str | None,
    ) -> dict[str, Any]:
        if dimensions not in (None, 512):
            raise EmbeddingValidationError(
                "Marengo Embed 3.0 only supports 512 dimensions"
            )
        if item.type == "text":
            return {"inputType": "text", "text": {"inputText": item.text}}
        return {
            "inputType": "image",
            "image": {"mediaSource": {"base64String": item.image_base64}},
        }

    def parse_response(self, payload: Any) -> CanonicalEmbeddingResult:
        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        entries = data if isinstance(data, list) else [data]
        vectors = [
            EmbeddingVector(index=index, embedding=_embedding(entry, "Marengo"))
            for index, entry in enumerate(entries)
        ]
        return CanonicalEmbeddingResult(vectors=vectors)


class NovaMultimodalEmbeddingAdapter(EmbeddingModelAdapter):
    model_id = NOVA_MODEL_ID
    dimensions = frozenset({256, 384, 1024, 3072})
    purposes = frozenset(
        {
            "GENERIC_INDEX",
            "GENERIC_RETRIEVAL",
            "TEXT_RETRIEVAL",
            "IMAGE_RETRIEVAL",
            "DOCUMENT_RETRIEVAL",
            "CLASSIFICATION",
            "CLUSTERING",
        }
    )

    def build_body(
        self,
        item: CanonicalEmbeddingInput,
        dimensions: int | None,
        purpose: str | None,
    ) -> dict[str, Any]:
        dimension = dimensions or 3072
        if dimension not in self.dimensions:
            raise EmbeddingValidationError(
                "Nova dimensions must be 256, 384, 1024, or 3072"
            )
        embedding_purpose = purpose or "GENERIC_INDEX"
        if embedding_purpose not in self.purposes:
            allowed = ", ".join(sorted(self.purposes))
            raise EmbeddingValidationError(f"Nova purpose must be one of: {allowed}")

        params: dict[str, Any] = {
            "embeddingPurpose": embedding_purpose,
            "embeddingDimension": dimension,
        }
        if item.type == "text":
            params["text"] = {"truncationMode": "END", "value": item.text}
        else:
            params["image"] = {
                "format": item.image_format,
                "source": {"bytes": item.image_base64},
                "detailLevel": "STANDARD_IMAGE",
            }
        return {
            "schemaVersion": "nova-multimodal-embed-v1",
            "taskType": "SINGLE_EMBEDDING",
            "singleEmbeddingParams": params,
        }

    def parse_response(self, payload: Any) -> CanonicalEmbeddingResult:
        entries = payload.get("embeddings") if isinstance(payload, dict) else None
        if not isinstance(entries, list) or not entries:
            raise EmbeddingValidationError("Nova response did not contain embeddings")
        vectors = [
            EmbeddingVector(index=index, embedding=_embedding(entry, "Nova"))
            for index, entry in enumerate(entries)
        ]
        raw_tokens = payload.get("inputTextTokenCount", payload.get("inputTokenCount"))
        # Usage counts are advisory: a malformed count must not discard vectors.
        input_tokens = (
            raw_tokens
            if isinstance(raw_tokens, int) and not isinstance(raw_tokens, bool)
            else 0
        )
        return CanonicalEmbeddingResult(vectors=vectors, input_tokens=input_tokens)


_ADAPTERS: dict[str, EmbeddingModelAdapter] = {
    MARENGO_MODEL_ID: MarengoEmbeddingAdapter(),
    NOVA_MODEL_ID: NovaMultimodalEmbeddingAdapter(),
}


def get_embedding_adapter(model_id: str) -> EmbeddingModelAdapter:
    """Return an adapter only for explicitly supported embedding models."""
    adapter = _ADAPTERS.get(model_id)
    if adapter is None:
        supported = ", ".join(sorted(SUPPORTED_EMBEDDING_MODELS))
        raise EmbeddingValidationError(
            f"embedding model '{model_id}' is not supported; supported models: {supported}"
        )
    return adapter

# pyright: reportMissingImports=false
"""Bedrock Runtime ``InvokeModel`` orchestration for embeddings.

Embeddings are invoked with the bare model ID in ``KBR_EMBEDDING_REGION``
(default us-east-1). The chat-model region resolver is not used: these models
are absent from regions such as us-west-2, where it would route them and
Bedrock answers "The provided model identifier is invalid".
"""

from __future__ import annotations

import json
from typing import Any

from app.core.config import get_settings
from app.schemas.embeddings import (
    CanonicalEmbeddingRequest,
    CanonicalEmbeddingResult,
    EmbeddingVector,
)
from app.services.bedrock import BedrockClient
from app.services.embedding_models import get_embedding_adapter


def _header_token_count(value: Any) -> int:
    """Parse the advisory token-count header; malformed or missing counts are 0."""
    try:
        count = int(str(value))
    except (TypeError, ValueError):
        return 0
    return max(count, 0)


class EmbeddingResponseError(ValueError):
    """Bedrock returned an unreadable embedding payload."""


class EmbeddingService:
    """Execute normalized embedding requests through Bedrock Runtime."""

    def __init__(self, runtime: Any | None = None):
        self.runtime: Any = runtime or BedrockClient.get_instance()

    async def _invoke_model(
        self, model_id: str, region: str, body: dict[str, Any]
    ) -> tuple[dict[str, Any], int]:
        """Return the decoded body and the header input-token count (0 if absent).

        Nova reports text tokens only in ``x-amzn-bedrock-input-token-count``,
        not in the response body.
        """
        await self.runtime._rate_limiter.acquire()
        async with self.runtime._semaphore:
            async with self.runtime.session.client(
                "bedrock-runtime",
                region_name=region,
                config=self.runtime.config,
            ) as client:
                response = await client.invoke_model(
                    modelId=model_id,
                    body=json.dumps(body),
                    accept="application/json",
                    contentType="application/json",
                )
                raw = await response["body"].read()
        headers = response.get("ResponseMetadata", {}).get("HTTPHeaders", {})
        tokens = _header_token_count(headers.get("x-amzn-bedrock-input-token-count"))
        try:
            return json.loads(raw), tokens
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
            raise EmbeddingResponseError(
                "Bedrock returned an invalid embedding response"
            ) from exc

    async def embed(
        self, request: CanonicalEmbeddingRequest
    ) -> CanonicalEmbeddingResult:
        """Embed each input with one InvokeModel call, preserving input order."""
        adapter = get_embedding_adapter(request.model)
        model_id, region = request.model, get_settings().EMBEDDING_REGION
        vectors: list[EmbeddingVector] = []
        total_input_tokens = 0

        for input_index, item in enumerate(request.inputs):
            body = adapter.build_body(item, request.dimensions, request.purpose)
            payload, header_tokens = await self._invoke_model(model_id, region, body)
            parsed = adapter.parse_response(payload)
            if len(parsed.vectors) != 1:
                raise EmbeddingResponseError(
                    f"expected one embedding per input, got {len(parsed.vectors)}"
                )
            total_input_tokens += parsed.input_tokens or header_tokens
            vectors.append(
                EmbeddingVector(
                    index=input_index, embedding=parsed.vectors[0].embedding
                )
            )

        return CanonicalEmbeddingResult(
            vectors=vectors, input_tokens=total_input_tokens
        )

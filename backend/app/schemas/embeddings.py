"""Schemas for OpenAI-compatible text and image embeddings."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

EmbeddingInputType = Literal["text", "image"]
ImageFormat = Literal["png", "jpeg", "gif", "webp"]


class CanonicalEmbeddingInput(BaseModel):
    """One model-neutral embedding input: a text, or one inline image."""

    type: EmbeddingInputType
    text: str | None = None
    image_base64: str | None = None
    image_format: ImageFormat | None = None

    @model_validator(mode="after")
    def validate_input(self):
        if self.type == "text" and not self.text:
            raise ValueError("text input requires text")
        if self.type == "image" and (not self.image_base64 or not self.image_format):
            raise ValueError("image input requires image_base64 and image_format")
        return self


class CanonicalEmbeddingRequest(BaseModel):
    model: str
    inputs: list[CanonicalEmbeddingInput] = Field(min_length=1, max_length=96)
    dimensions: int | None = None
    purpose: str | None = None


class EmbeddingVector(BaseModel):
    embedding: list[float]
    index: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalEmbeddingResult(BaseModel):
    vectors: list[EmbeddingVector]
    input_tokens: int = 0


class OpenAIEmbeddingRequest(BaseModel):
    """``POST /v1/embeddings`` body.

    ``input`` is a string or a list of items. Each item is text, or an image
    sent inline as a ``data:image/...;base64,`` URI — as a plain string, as
    ``{"type": "image_url", "image_url": {"url": ...}}`` (the chat format), or
    as ``{"image": ...}``. Parsing lives in ``app.services.embedding_inputs``.
    """

    model: str
    input: str | list[str | dict[str, Any]]
    dimensions: int | None = None
    encoding_format: Literal["float"] = "float"
    user: str | None = None
    purpose: str | None = None

    @model_validator(mode="after")
    def validate_input(self):
        values = [self.input] if isinstance(self.input, str) else self.input
        if not values:
            raise ValueError("input must contain at least one item")
        if len(values) > 96:
            raise ValueError("input supports at most 96 items")
        return self

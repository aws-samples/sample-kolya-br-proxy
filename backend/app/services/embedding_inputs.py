# pyright: reportMissingImports=false
"""Turn OpenAI ``/v1/embeddings`` ``input`` items into canonical inputs.

Each item becomes exactly one embedding, in order:

* ``"some text"`` → text
* ``"data:image/png;base64,..."`` → image (never embedded as text)
* ``{"type": "text", "text": ...}`` or ``{"text": ...}`` → text
* ``{"type": "image_url", "image_url": {"url": <data URI>}}`` (chat format),
  ``{"type": "image_url", "image_url": <data URI>}``, or ``{"image": <data URI>}``
  → image

Images must be inline data URIs. Remote URLs are rejected: the gateway never
fetches caller-supplied URLs.
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any

from app.schemas.embeddings import CanonicalEmbeddingInput, ImageFormat

_DATA_URI_RE = re.compile(r"^data:image/([A-Za-z0-9.+-]+);base64,(.*)$", re.DOTALL)
_FORMATS: dict[str, ImageFormat] = {
    "png": "png",
    "jpeg": "jpeg",
    "jpg": "jpeg",
    "gif": "gif",
    "webp": "webp",
}


class EmbeddingInputError(ValueError):
    """An ``input`` item is malformed; the message names its position."""


def _image(uri: Any, position: int) -> CanonicalEmbeddingInput:
    if not isinstance(uri, str):
        raise EmbeddingInputError(f"input[{position}]: image must be a data URI string")
    if uri.startswith(("http://", "https://")):
        raise EmbeddingInputError(
            f"input[{position}]: image URLs are not fetched; send the image inline as "
            "data:image/<png|jpeg|gif|webp>;base64,..."
        )
    match = _DATA_URI_RE.match(uri.strip())
    if not match:
        raise EmbeddingInputError(
            f"input[{position}]: image must be data:image/<png|jpeg|gif|webp>;base64,..."
        )
    image_format = _FORMATS.get(match.group(1).lower())
    if image_format is None:
        raise EmbeddingInputError(
            f"input[{position}]: unsupported image type image/{match.group(1)}; "
            "use png, jpeg, gif, or webp"
        )
    payload = "".join(match.group(2).split())
    try:
        base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EmbeddingInputError(
            f"input[{position}]: image data is not valid base64"
        ) from exc
    if not payload:
        raise EmbeddingInputError(f"input[{position}]: image data is empty")
    return CanonicalEmbeddingInput(
        type="image", image_base64=payload, image_format=image_format
    )


def _text(value: Any, position: int) -> CanonicalEmbeddingInput:
    if not isinstance(value, str) or not value:
        raise EmbeddingInputError(f"input[{position}]: text must be a non-empty string")
    return CanonicalEmbeddingInput(type="text", text=value)


def parse_input_item(item: Any, position: int) -> CanonicalEmbeddingInput:
    if isinstance(item, str):
        if item.startswith("data:"):
            return _image(item, position)
        return _text(item, position)
    if isinstance(item, dict):
        kind = item.get("type")
        if kind == "image_url" or (kind is None and "image_url" in item):
            target = item.get("image_url")
            url = target.get("url") if isinstance(target, dict) else target
            return _image(url, position)
        if kind == "image" or (kind is None and "image" in item):
            return _image(item.get("image"), position)
        if kind == "text" or (kind is None and "text" in item):
            return _text(item.get("text"), position)
    raise EmbeddingInputError(
        f"input[{position}]: expected text, a data:image URI, "
        '{"type": "text", "text": ...}, or {"type": "image_url", "image_url": {"url": ...}}'
    )


def parse_openai_input(value: str | list[Any]) -> list[CanonicalEmbeddingInput]:
    items = [value] if isinstance(value, str) else value
    return [parse_input_item(item, position) for position, item in enumerate(items)]

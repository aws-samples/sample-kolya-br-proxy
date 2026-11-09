"""Fallback token counts for streams that end before the usage event.

Upstreams report output tokens (and, for Converse and Responses, input
tokens too) only in the stream's final event. A client that reads the
content and disconnects just before that event used to be billed nothing
for it, even though the upstream charged us. When the final usage never
arrives, billing falls back to these estimates: about 4 characters per
token, counting only text the model received or produced (inline image
and document bytes are skipped, so the estimate does not inflate on base64).
"""

from typing import Any

CHARS_PER_TOKEN = 4

# Keys whose string values are binary payloads, not model-visible text.
_BINARY_KEYS = frozenset(
    {"data", "bytes", "image_url", "url", "source", "signature", "media_type"}
)


def tokens_from_chars(chars: int) -> int:
    if chars <= 0:
        return 0
    return (chars + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def _text_chars(value: Any, depth: int = 0) -> int:
    if depth > 50:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(
            _text_chars(v, depth + 1) for k, v in value.items() if k not in _BINARY_KEYS
        )
    if isinstance(value, (list, tuple)):
        return sum(_text_chars(v, depth + 1) for v in value)
    return 0


def estimate_input_tokens(request: Any) -> int:
    """Rough prompt size of a request model or dict (messages, system, tools)."""
    if request is None:
        return 0
    if hasattr(request, "model_dump"):
        request = request.model_dump(exclude_none=True)
    if not isinstance(request, dict):
        return 0
    relevant = {
        k: request[k]
        for k in ("messages", "system", "tools", "input", "instructions")
        if k in request
    }
    return tokens_from_chars(_text_chars(relevant))


class StreamUsageFallback:
    """Counts streamed output so an aborted stream can still be billed."""

    def __init__(self) -> None:
        self.output_chars = 0
        self.final_usage_seen = False

    def add_output(self, text: str | None) -> None:
        if text:
            self.output_chars += len(text)

    def resolve(
        self, input_tokens: int, output_tokens: int, request: Any
    ) -> tuple[int, int]:
        """Return (input, output) to bill, filling gaps on an aborted stream."""
        if self.final_usage_seen:
            return input_tokens, output_tokens
        output_tokens = max(output_tokens, tokens_from_chars(self.output_chars))
        if not input_tokens and (self.output_chars or output_tokens):
            input_tokens = estimate_input_tokens(request)
        return input_tokens, output_tokens

"""
In-memory ring buffer trace store for request/response inspection.

Stores the last N full API traces (request body, response, usage) for
debugging and inspection via the /admin/traces endpoint.

Controlled by TRACE_ENABLED env var (default: False; enable with
KBR_TRACE_ENABLED=true). Reads are scoped per token in the admin endpoint
because records contain full prompt and response text.

Memory is bounded twice: each string field is truncated to
MAX_FIELD_CHARS, binary payloads (base64 images/documents) are replaced by
a size marker, and the buffer evicts oldest records once the total
estimated size passes MAX_TOTAL_CHARS.
"""

import json
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from app.core.config import get_settings


@dataclass
class TraceRecord:
    """A single request/response trace."""

    request_id: str
    timestamp: float
    model: str
    token_id: str
    token_name: str = ""

    # Request
    system: Any = None
    messages: list = field(default_factory=list)
    tools: list = field(default_factory=list)
    thinking: Any = None
    max_tokens: int = 0
    temperature: Optional[float] = None
    stream: bool = False

    # Response
    response_content: list = field(default_factory=list)
    stop_reason: str = ""
    duration_s: float = 0.0

    # Usage
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    # Error (if any)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


MAX_FIELD_CHARS = 16 * 1024
MAX_TOTAL_CHARS = 32 * 1024 * 1024
_BINARY_KEYS = frozenset({"data", "bytes"})


def _shrink(value: Any, depth: int = 0) -> Any:
    """Copy of value with long strings truncated and binary blobs elided."""
    if depth > 50:
        return "[truncated: too deep]"
    if isinstance(value, str):
        if len(value) > MAX_FIELD_CHARS:
            return (
                value[:MAX_FIELD_CHARS]
                + f"... [truncated {len(value) - MAX_FIELD_CHARS} chars]"
            )
        return value
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in _BINARY_KEYS and isinstance(v, (str, bytes)):
                out[k] = f"[{len(v)} bytes omitted]"
            else:
                out[k] = _shrink(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_shrink(v, depth + 1) for v in value]
    if isinstance(value, bytes):
        return f"[{len(value)} bytes omitted]"
    return value


def _approx_size(record: "TraceRecord") -> int:
    try:
        return len(json.dumps(record.to_dict(), default=str))
    except (TypeError, ValueError):
        return MAX_FIELD_CHARS


class TraceStore:
    """Thread-safe in-memory ring buffer for trace records."""

    _instance: Optional["TraceStore"] = None

    def __init__(self, max_size: int = 200, max_total_chars: int = MAX_TOTAL_CHARS):
        self._buffer: deque[TraceRecord] = deque()
        self._sizes: deque[int] = deque()
        self._total = 0
        self._max_size = max_size
        self._max_total = max_total_chars

    @classmethod
    def get_instance(cls) -> "TraceStore":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def is_enabled(cls) -> bool:
        settings = get_settings()
        return settings.TRACE_ENABLED

    def add(self, record: TraceRecord) -> None:
        for name in ("system", "messages", "tools", "thinking", "response_content"):
            setattr(record, name, _shrink(getattr(record, name)))
        size = _approx_size(record)
        self._buffer.append(record)
        self._sizes.append(size)
        self._total += size
        while self._buffer and (
            len(self._buffer) > self._max_size or self._total > self._max_total
        ):
            self._buffer.popleft()
            self._total -= self._sizes.popleft()

    def list_all(self) -> list[dict]:
        return [r.to_dict() for r in reversed(self._buffer)]

    def get(self, request_id: str) -> Optional[dict]:
        for r in self._buffer:
            if r.request_id == request_id:
                return r.to_dict()
        return None

    def clear(self) -> None:
        self._buffer.clear()
        self._sizes.clear()
        self._total = 0

    @property
    def size(self) -> int:
        return len(self._buffer)

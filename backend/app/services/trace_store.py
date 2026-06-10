"""
In-memory ring buffer trace store for request/response inspection.

Stores the last N full API traces (request body, response, usage) for
debugging and inspection via the /admin/traces endpoint.

Controlled by TRACE_ENABLED env var (default: True).
Production disables via KBR_TRACE_ENABLED=false in ConfigMap.
"""

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


class TraceStore:
    """Thread-safe in-memory ring buffer for trace records."""

    _instance: Optional["TraceStore"] = None

    def __init__(self, max_size: int = 200):
        self._buffer: deque[TraceRecord] = deque(maxlen=max_size)

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
        self._buffer.append(record)

    def list_all(self) -> list[dict]:
        return [r.to_dict() for r in reversed(self._buffer)]

    def get(self, request_id: str) -> Optional[dict]:
        for r in self._buffer:
            if r.request_id == request_id:
                return r.to_dict()
        return None

    def clear(self) -> None:
        self._buffer.clear()

    @property
    def size(self) -> int:
        return len(self._buffer)

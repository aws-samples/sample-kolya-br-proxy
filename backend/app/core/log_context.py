"""
Request-scoped logging context using contextvars.

Sets token_name / token_id on every log record automatically so logs
can be filtered per API key without changing individual logger calls.
"""

import contextvars
import logging

_token_name: contextvars.ContextVar[str] = contextvars.ContextVar(
    "token_name", default="-"
)
_token_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "token_id", default="-"
)


def set_log_context(*, token_name: str = "", token_id: str = "") -> None:
    """Set request-scoped logging fields (call after auth succeeds)."""
    if token_name:
        _token_name.set(token_name)
    if token_id:
        _token_id.set(token_id)


def clear_log_context() -> None:
    """Reset context (called automatically per-request by middleware)."""
    _token_name.set("-")
    _token_id.set("-")


class RequestContextFilter(logging.Filter):
    """Inject contextvars into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.token_name = _token_name.get("-")
        record.token_id = _token_id.get("-")
        return True

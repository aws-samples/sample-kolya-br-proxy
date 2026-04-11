"""
Request-scoped logging context using contextvars.

Sets token_name / token_id / trace_id / span_id on every log record
automatically so logs can be filtered per API key and correlated with
X-Ray traces without changing individual logger calls.
"""

import contextvars
import logging

_token_name: contextvars.ContextVar[str] = contextvars.ContextVar(
    "token_name", default="-"
)
_token_id: contextvars.ContextVar[str] = contextvars.ContextVar("token_id", default="-")


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
    """Inject contextvars and OpenTelemetry trace context into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.token_name = _token_name.get("-")
        record.token_id = _token_id.get("-")

        # Inject trace context for log-trace correlation (zero-cost no-op when OTEL disabled)
        try:
            from opentelemetry import trace

            span = trace.get_current_span()
            ctx = span.get_span_context()
            if ctx and ctx.is_valid:
                record.trace_id = format(ctx.trace_id, "032x")
                record.span_id = format(ctx.span_id, "016x")
            else:
                record.trace_id = "-"
                record.span_id = "-"
        except ImportError:
            record.trace_id = "-"
            record.span_id = "-"

        return True

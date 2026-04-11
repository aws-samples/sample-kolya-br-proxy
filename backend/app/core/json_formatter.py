"""
Structured JSON logging formatter and unified logging configuration.

When LOG_FORMAT="json", outputs one JSON object per line — all ``extra={}``
fields from existing logger calls are included automatically.  CloudWatch
Logs Insights can query these fields natively.

When LOG_FORMAT="text", the original human-readable format is preserved.
"""

import json
import logging
import sys
import traceback
from datetime import datetime, timezone

# Standard LogRecord attributes to exclude from the ``extra`` section.
_BUILTIN_ATTRS = frozenset(
    {
        "args",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
        # Injected by RequestContextFilter — promoted to top-level keys
        "token_name",
        "token_id",
        "trace_id",
        "span_id",
    }
)

_TEXT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - [%(token_name)s] %(message)s"


class StructuredJsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        record.message = record.getMessage()

        obj: dict = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
            "token_name": getattr(record, "token_name", "-"),
            "token_id": getattr(record, "token_id", "-"),
            "trace_id": getattr(record, "trace_id", "-"),
            "span_id": getattr(record, "span_id", "-"),
        }

        for key, value in record.__dict__.items():
            if key not in _BUILTIN_ATTRS and not key.startswith("_"):
                obj[key] = value

        if record.exc_info and record.exc_info[0] is not None:
            obj["exception"] = "".join(traceback.format_exception(*record.exc_info))

        return json.dumps(obj, ensure_ascii=False, default=str)


class _HealthCheckFilter(logging.Filter):
    """Filter out health check access logs to reduce noise."""

    def filter(self, record: logging.LogRecord) -> bool:
        return '"GET /health/' not in record.getMessage()


def configure_logging() -> None:
    """One-time logging setup — call from ``main.py`` before anything else.

    Reads ``LOG_LEVEL`` and ``LOG_FORMAT`` from settings to decide the
    output format and verbosity.  Attaches the ``RequestContextFilter``
    (token_name / token_id / trace_id) to the root logger.
    """
    from app.core.config import get_settings
    from app.core.log_context import RequestContextFilter

    settings = get_settings()
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # Clear any handlers set by prior basicConfig / library imports
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if settings.LOG_FORMAT == "json":
        handler.setFormatter(StructuredJsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_TEXT_FORMAT))

    root.addHandler(handler)

    root.addFilter(RequestContextFilter())
    logging.getLogger("uvicorn.access").addFilter(_HealthCheckFilter())

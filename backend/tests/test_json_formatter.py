"""
Tests for structured JSON logging formatter and configure_logging().
"""

import json
import logging


from app.core.json_formatter import StructuredJsonFormatter, _HealthCheckFilter


class TestStructuredJsonFormatter:
    """Tests for StructuredJsonFormatter."""

    def setup_method(self):
        self.formatter = StructuredJsonFormatter()

    def _make_record(self, msg: str, **extra) -> logging.LogRecord:
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )
        # Simulate RequestContextFilter defaults
        record.token_name = "-"
        record.token_id = "-"
        record.trace_id = "-"
        record.span_id = "-"
        for k, v in extra.items():
            setattr(record, k, v)
        return record

    def test_output_is_valid_json(self):
        record = self._make_record("hello world")
        output = self.formatter.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "hello world"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"

    def test_single_line(self):
        record = self._make_record("no newlines")
        output = self.formatter.format(record)
        assert "\n" not in output

    def test_top_level_context_fields(self):
        record = self._make_record(
            "with context",
            token_name="alice-key",
            token_id="tok_123",
            trace_id="abc123",
            span_id="def456",
        )
        parsed = json.loads(self.formatter.format(record))
        assert parsed["token_name"] == "alice-key"
        assert parsed["token_id"] == "tok_123"
        assert parsed["trace_id"] == "abc123"
        assert parsed["span_id"] == "def456"

    def test_extra_fields_included(self):
        record = self._make_record("bedrock call")
        record.model = "claude-sonnet"
        record.duration = 1.234
        record.input_tokens = 500
        parsed = json.loads(self.formatter.format(record))
        assert parsed["model"] == "claude-sonnet"
        assert parsed["duration"] == 1.234
        assert parsed["input_tokens"] == 500

    def test_builtin_attrs_excluded(self):
        record = self._make_record("test")
        parsed = json.loads(self.formatter.format(record))
        # Standard LogRecord attributes should not appear
        assert "args" not in parsed
        assert "pathname" not in parsed
        assert "lineno" not in parsed
        assert "funcName" not in parsed

    def test_timestamp_present_and_utc(self):
        record = self._make_record("ts check")
        parsed = json.loads(self.formatter.format(record))
        assert "timestamp" in parsed
        assert "T" in parsed["timestamp"]  # ISO format

    def test_exception_included(self):
        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()
        record = self._make_record("failed")
        record.exc_info = exc_info
        parsed = json.loads(self.formatter.format(record))
        assert "exception" in parsed
        assert "ValueError: test error" in parsed["exception"]

    def test_non_serializable_extra_converted_to_str(self):
        record = self._make_record("odd value")
        record.weird_obj = object()
        parsed = json.loads(self.formatter.format(record))
        assert "weird_obj" in parsed
        assert isinstance(parsed["weird_obj"], str)


class TestHealthCheckFilter:
    """Tests for _HealthCheckFilter."""

    def test_allows_normal_logs(self):
        f = _HealthCheckFilter()
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg='"POST /v1/chat/completions HTTP/1.1" 200',
            args=(),
            exc_info=None,
        )
        assert f.filter(record) is True

    def test_filters_health_check_logs(self):
        f = _HealthCheckFilter()
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg='"GET /health/ HTTP/1.1" 200',
            args=(),
            exc_info=None,
        )
        assert f.filter(record) is False

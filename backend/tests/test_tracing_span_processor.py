"""The OPTIONS-filtering span processor must satisfy the SDK's full hook set."""

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app.core.tracing import _FilteringSpanProcessor


def _tracer():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(_FilteringSpanProcessor(SimpleSpanProcessor(exporter)))
    return provider.get_tracer("test"), exporter


def test_ending_a_span_does_not_raise_and_exports():
    tracer, exporter = _tracer()
    with tracer.start_as_current_span("req", attributes={"http.method": "POST"}):
        pass
    assert [s.name for s in exporter.get_finished_spans()] == ["req"]


def test_options_spans_are_dropped():
    tracer, exporter = _tracer()
    with tracer.start_as_current_span("cors", attributes={"http.method": "OPTIONS"}):
        pass
    assert exporter.get_finished_spans() == ()

"""
OpenTelemetry tracing setup for AWS X-Ray integration.

All imports are lazy — when ``OTEL_EXPORTER`` is empty (default), this
module does nothing and adds zero startup cost.
"""

import logging
import os

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def configure_tracing() -> None:
    """Initialise the OpenTelemetry TracerProvider.

    Reads ``OTEL_EXPORTER`` from settings:
    - ``""`` (empty) → tracing disabled, no imports
    - ``"xray"`` → OTLP HTTP exporter to localhost:4318 (ADOT collector)
    - ``"otlp"`` → OTLP HTTP exporter using ``OTEL_EXPORTER_OTLP_ENDPOINT`` env
    """
    settings = get_settings()
    if not settings.OTEL_EXPORTER:
        return

    from opentelemetry import trace
    from opentelemetry.propagate import set_global_textmap
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.propagators.aws import AwsXRayPropagator
    from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator

    resource = Resource.create(
        {
            "service.name": "kolya-br-proxy",
            "service.version": "1.0.0",
            "deployment.environment": os.getenv("KBR_ENV", "non-prod"),
        }
    )

    provider = TracerProvider(
        resource=resource,
        id_generator=AwsXRayIdGenerator(),
    )

    if settings.OTEL_EXPORTER == "xray":
        # CloudWatch agent DaemonSet exposes OTLP HTTP on port 4316.
        # NODE_IP is set via Kubernetes fieldRef status.hostIP.
        node_ip = os.getenv("NODE_IP", "localhost")
        endpoint = settings.OTEL_ENDPOINT or f"http://{node_ip}:4316/v1/traces"
        exporter = OTLPSpanExporter(
            endpoint=endpoint,
        )
    elif settings.OTEL_EXPORTER == "otlp":
        exporter = OTLPSpanExporter()  # reads OTEL_EXPORTER_OTLP_ENDPOINT
    else:
        logger.warning("Unknown OTEL_EXPORTER value: %s", settings.OTEL_EXPORTER)
        return

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    set_global_textmap(AwsXRayPropagator())

    logger.info("OpenTelemetry tracing enabled (exporter=%s)", settings.OTEL_EXPORTER)


def instrument_app(app) -> None:
    """Auto-instrument FastAPI routes (no-op if tracing is disabled)."""
    settings = get_settings()
    if not settings.OTEL_EXPORTER:
        return

    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="health")
    logger.info("FastAPI auto-instrumentation enabled (excluded: /health*)")

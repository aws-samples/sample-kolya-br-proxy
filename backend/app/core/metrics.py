"""
CloudWatch Embedded Metrics Format (EMF) helpers.

EMF emits metrics as specially structured JSON log lines.  CloudWatch
automatically extracts them as custom metrics — no agent or sidecar needed.

All functions are no-ops when ``ENABLE_METRICS`` is ``False``.
"""

import logging

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_configured = False


def configure_metrics() -> None:
    """One-time EMF SDK configuration.  Call from lifespan startup."""
    global _configured
    settings = get_settings()
    if not settings.ENABLE_METRICS:
        return

    from aws_embedded_metrics.config import get_config

    config = get_config()
    config.service_name = "kolya-br-proxy"
    config.service_type = "AWS::EKS::Pod"
    config.log_group = "/kbp/backend/metrics"
    config.namespace = "KolyaBRProxy"
    _configured = True
    logger.info("CloudWatch EMF metrics enabled")


async def emit_request_metrics(
    *,
    endpoint: str,
    model: str,
    duration_s: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    status_code: int = 200,
    is_streaming: bool = False,
    ttft_s: float | None = None,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> None:
    """Emit per-request metrics after a completion finishes."""
    if not _configured:
        return

    from aws_embedded_metrics import MetricsLogger
    from aws_embedded_metrics.unit import Unit

    async with MetricsLogger() as ml:
        ml.set_dimensions(
            {"Endpoint": endpoint, "Model": model, "Streaming": str(is_streaming)}
        )
        ml.put_metric("RequestDuration", duration_s, Unit.SECONDS)
        ml.put_metric("RequestCount", 1, Unit.COUNT)
        ml.put_metric("TokensInput", input_tokens, Unit.COUNT)
        ml.put_metric("TokensOutput", output_tokens, Unit.COUNT)
        if cache_write_tokens:
            ml.put_metric("CacheWriteTokens", cache_write_tokens, Unit.COUNT)
        if cache_read_tokens:
            ml.put_metric("CacheReadTokens", cache_read_tokens, Unit.COUNT)
        if ttft_s is not None:
            ml.put_metric("TimeToFirstToken", ttft_s, Unit.SECONDS)
        ml.set_property("StatusCode", status_code)


async def emit_bedrock_call_metrics(
    *,
    model: str,
    region: str,
    duration_s: float,
    api: str,
    attempt: int = 1,
    success: bool = True,
) -> None:
    """Emit per-Bedrock-invocation metrics."""
    if not _configured:
        return

    from aws_embedded_metrics import MetricsLogger
    from aws_embedded_metrics.unit import Unit

    async with MetricsLogger() as ml:
        ml.set_dimensions({"Model": model, "Region": region, "API": api})
        ml.put_metric("BedrockCallDuration", duration_s, Unit.SECONDS)
        ml.set_property("Attempt", attempt)
        ml.set_property("Success", success)


async def emit_failover_metrics(
    *,
    primary_model: str,
    failover_target: str,
    level: str,
    duration_s: float,
    success: bool,
) -> None:
    """Emit stream failover metrics."""
    if not _configured:
        return

    from aws_embedded_metrics import MetricsLogger
    from aws_embedded_metrics.unit import Unit

    async with MetricsLogger() as ml:
        ml.set_dimensions({"Level": level, "PrimaryModel": primary_model})
        ml.put_metric("FailoverTriggered", 1, Unit.COUNT)
        ml.put_metric("StreamFailoverDuration", duration_s, Unit.SECONDS)
        ml.set_property("FailoverTarget", failover_target)
        ml.set_property("Success", success)


async def emit_http_metrics(
    *,
    method: str,
    path: str,
    status_code: int,
    duration_s: float,
) -> None:
    """Emit high-level HTTP request metrics (from observability middleware)."""
    if not _configured:
        return

    from aws_embedded_metrics import MetricsLogger
    from aws_embedded_metrics.unit import Unit

    async with MetricsLogger() as ml:
        ml.set_dimensions({"Method": method, "Path": path})
        ml.put_metric("HttpRequestDuration", duration_s, Unit.SECONDS)
        ml.put_metric("HttpRequestCount", 1, Unit.COUNT)
        ml.set_property("StatusCode", status_code)

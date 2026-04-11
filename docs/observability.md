# Observability

This document covers the structured logging, CloudWatch EMF metrics, and AWS X-Ray tracing capabilities of the system.

## Table of Contents

- [Overview](#overview)
- [Configuration](#configuration)
- [Structured Logging](#structured-logging)
- [CloudWatch EMF Metrics](#cloudwatch-emf-metrics)
- [AWS X-Ray Tracing](#aws-x-ray-tracing)
- [Log-Trace Correlation](#log-trace-correlation)
- [Deployment Configuration](#deployment-configuration)
- [Troubleshooting](#troubleshooting)

---

## Overview

All observability features are **disabled by default** and controlled via environment variables. Local development has zero overhead; production enables features progressively.

```
Local dev:   no env vars needed → text logs, no metrics, no tracing
Staging:     KBR_LOG_FORMAT=json, KBR_LOG_LEVEL=DEBUG
Production:  KBR_LOG_FORMAT=json, KBR_ENABLE_METRICS=true, KBR_OTEL_EXPORTER=xray
```

### Architecture

```mermaid
graph TD
    App[FastAPI App] --> Logs[Structured Logs<br/>JSON / text]
    App --> EMF[EMF Metrics]
    App --> OTel[OTel Spans]

    Logs --> CWL[CloudWatch<br/>Logs Insights]
    EMF --> CWM[CloudWatch<br/>Metrics]
    OTel --> |OTLP HTTP :4316| CWAgent[CloudWatch Agent<br/>DaemonSet]
    CWAgent --> XRay[AWS X-Ray<br/>Console]

    style App fill:#4a90d9,color:#fff
    style CWL fill:#ff9900,color:#fff
    style CWM fill:#ff9900,color:#fff
    style XRay fill:#ff9900,color:#fff
    style CWAgent fill:#527fff,color:#fff
```

---

## Configuration

All settings use the `KBR_` prefix and are defined in `backend/app/core/config.py`:

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `KBR_LOG_LEVEL` | `INFO` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `KBR_LOG_FORMAT` | `text` | Output format: `text` (human-readable) or `json` (CloudWatch) |
| `KBR_ENABLE_METRICS` | `false` | Enable CloudWatch Embedded Metrics Format emission |
| `KBR_OTEL_EXPORTER` | `""` (empty) | OpenTelemetry exporter: `""` (disabled), `xray`, `otlp` |
| `KBR_OTEL_ENDPOINT` | `""` (empty) | OTLP HTTP endpoint override (xray mode). Empty = auto-detect `http://$NODE_IP:4316/v1/traces` |

**Changing any setting requires a service restart** (pod rolling update in Kubernetes).

### Configuration Files

| File | Purpose |
|------|---------|
| `backend/app/core/config.py` | Settings definitions with validation |
| `backend/app/core/json_formatter.py` | JSON formatter + `configure_logging()` |
| `backend/app/core/metrics.py` | EMF metric emission functions |
| `backend/app/core/tracing.py` | OpenTelemetry initialization |
| `backend/app/core/log_context.py` | Per-request context injection (token_name, trace_id) |
| `backend/app/middleware/observability.py` | ASGI middleware for HTTP-level metrics |

---

## Structured Logging

### Text Format (default)

```
2026-04-11 12:00:00 - app.services.bedrock - INFO - [alice-key] Bedrock invocation successful...
```

### JSON Format (`KBR_LOG_FORMAT=json`)

```json
{
  "timestamp": "2026-04-11T12:00:00.123456+00:00",
  "level": "INFO",
  "logger": "app.services.bedrock",
  "message": "Bedrock invocation successful",
  "token_name": "alice-key",
  "token_id": "42",
  "trace_id": "1-abc-def0123456789",
  "span_id": "abcdef0123456789",
  "model": "us.anthropic.claude-sonnet-4-20250514-v1:0",
  "duration": 1.234,
  "input_tokens": 500,
  "output_tokens": 200
}
```

Key features:
- **Auto-collected extra fields**: All `logger.info("msg", extra={...})` fields are included automatically — no code changes needed
- **Per-API-key context**: `token_name` and `token_id` injected via `contextvars` on every log record
- **Trace correlation**: `trace_id` and `span_id` from OpenTelemetry (when tracing is enabled)
- **Health check filtering**: `/health/*` access logs are suppressed to reduce noise

### CloudWatch Logs Insights Queries

```sql
-- Find all logs for a specific API key
fields @timestamp, level, message, model, duration
| filter token_name = "alice-key"
| sort @timestamp desc

-- Slow requests (> 5 seconds)
fields @timestamp, token_name, model, duration
| filter duration > 5
| sort duration desc

-- Error logs with stack traces
fields @timestamp, logger, message, exception
| filter level = "ERROR"
| sort @timestamp desc

-- Correlate logs with a specific X-Ray trace
fields @timestamp, level, message
| filter trace_id = "1-abc-def0123456789"
| sort @timestamp asc
```

---

## CloudWatch EMF Metrics

CloudWatch Embedded Metrics Format emits metrics as structured JSON log lines. CloudWatch automatically extracts them as custom metrics — no agent or sidecar needed.

### Metrics Catalog

All metrics use the namespace `KolyaBRProxy`.

#### Request Metrics (per API call)

| Metric | Unit | Dimensions | Description |
|--------|------|------------|-------------|
| `RequestDuration` | Seconds | Endpoint, Model, Streaming | End-to-end request duration (includes proxy overhead + Bedrock call) |
| `RequestCount` | Count | Endpoint, Model, Streaming | Number of requests |
| `TokensInput` | Count | Endpoint, Model, Streaming | Input token count |
| `TokensOutput` | Count | Endpoint, Model, Streaming | Output token count |
| `CacheWriteTokens` | Count | Endpoint, Model, Streaming | Prompt cache write tokens (only emitted when > 0) |
| `CacheReadTokens` | Count | Endpoint, Model, Streaming | Prompt cache read tokens (only emitted when > 0) |
| `TimeToFirstToken` | Seconds | Endpoint, Model, Streaming | Time from request start to first content delta (streaming only) |

#### Bedrock Call Metrics (per AWS API call)

| Metric | Unit | Dimensions | Description |
|--------|------|------------|-------------|
| `BedrockCallDuration` | Seconds | Model, Region, API | Duration of the Bedrock API call itself |

**Key relationship**: `RequestDuration` contains `BedrockCallDuration`. The difference is proxy overhead (auth, translation, SSE framing).

```mermaid
gantt
    title Request Duration Breakdown
    dateFormat X
    axisFormat %s

    section RequestDuration
    Auth + Translation       :a1, 0, 50
    BedrockCallDuration      :crit, a2, 50, 900
    SSE Framing + Response   :a3, 950, 50
```

#### Stream Failover Metrics

| Metric | Unit | Dimensions | Description |
|--------|------|------------|-------------|
| `FailoverTriggered` | Count | Level, PrimaryModel | Failover event counter |
| `StreamFailoverDuration` | Seconds | Level, PrimaryModel | Time from first failure to successful fallback (or final failure) |

Failover levels:
- **L1**: Same model, different region (transparent to client)
- **L2**: Different model (client notified via `x-actual-model` SSE comment)

#### HTTP Metrics (from middleware)

| Metric | Unit | Dimensions | Description |
|--------|------|------------|-------------|
| `HttpRequestDuration` | Seconds | Method, Path | HTTP request duration for all endpoints |
| `HttpRequestCount` | Count | Method, Path | HTTP request count |

### Emission Points

| Location | Metrics Emitted |
|----------|----------------|
| `chat.py` (non-streaming) | RequestDuration, TokensInput/Output, CacheTokens |
| `chat.py` (streaming) | RequestDuration, TokensInput/Output, CacheTokens, TTFT |
| `messages.py` (non-streaming) | RequestDuration, TokensInput/Output, CacheTokens |
| `messages.py` (streaming) | RequestDuration, TokensInput/Output, CacheTokens, TTFT |
| `bedrock.py` (_invoke_inner) | BedrockCallDuration |
| `bedrock.py` (_invoke_stream_inner) | BedrockCallDuration |
| `bedrock.py` (invoke_stream failover) | FailoverTriggered, StreamFailoverDuration |
| `observability.py` (middleware) | HttpRequestDuration, HttpRequestCount |

### TTFT (Time To First Token)

Measured at the first `content_block_delta` event in streaming generators:

```python
if ttft is None:
    ttft = time.time() - start_time
```

This captures the time from request receipt to the first actual content token reaching the client (excludes `message_start` and `content_block_start` events).

---

## AWS X-Ray Tracing

### Exporter Options

| `KBR_OTEL_EXPORTER` | Target | Use Case |
|---------------------|--------|----------|
| `""` (empty) | Disabled | Local development |
| `xray` | `http://$NODE_IP:4316` (CloudWatch Agent DaemonSet) | Production with CloudWatch Observability addon |
| `otlp` | `OTEL_EXPORTER_OTLP_ENDPOINT` env | Custom OTLP endpoint (e.g., Jaeger) |

> **Why port 4316 instead of standard 4318?** The CloudWatch Agent DaemonSet's OTLP HTTP receiver listens on port 4316. `NODE_IP` is injected via Kubernetes `fieldRef: status.hostIP` because `localhost` inside a container's network namespace refers to the pod itself, not the host where the DaemonSet runs.

### Health Check Exclusion

`/health/*` paths are excluded from tracing (via `FastAPIInstrumentor(excluded_urls="health")`) to avoid flooding X-Ray with high-frequency health probe traces.

### Auto-Instrumentation Disabled

The backend pod uses the annotation `instrumentation.opentelemetry.io/inject-python: "false"` to disable the CloudWatch Observability addon's Python auto-injection. Reason: the addon's auto-injection modifies the Python startup command, breaking the `app` module path and causing `ModuleNotFoundError`. The backend initializes OpenTelemetry manually in code (`tracing.py`) instead.

### What Gets Traced

1. **Auto-instrumented** (via `FastAPIInstrumentor`):
   - All FastAPI routes (except `/health/*`) — one root span per HTTP request
   - Includes HTTP method, path, status code, duration

2. **Manual spans** in `bedrock.py`:
   - `bedrock.invoke` — non-streaming Bedrock API call (`_invoke_inner`)
   - `bedrock.invoke_stream` — streaming Bedrock API call (`_invoke_stream_inner` and `_try_stream_with_content_timeout`)

Span attributes:

| Attribute | Description |
|-----------|-------------|
| `bedrock.model` | User-facing model name (non-failover paths only) |
| `bedrock.model_id` | Resolved Bedrock model ID |
| `bedrock.region` | Target AWS region |
| `bedrock.api` | API used: `invoke_model`, `converse`, `invoke_model_stream`, `converse_stream` |
| `bedrock.attempt` | Retry attempt number (non-failover paths only) |
| `bedrock.failover` | `true` when using the failover timeout path (failover paths only) |
| `bedrock.input_tokens` | Input token count (set after response, non-streaming only) |
| `bedrock.output_tokens` | Output token count (set after response, non-streaming only) |
| `bedrock.duration_s` | Call duration in seconds |

### Understanding X-Ray Trace Structure

In the X-Ray console trace detail view, you'll see these spans:

| Span Name | Source | Meaning |
|-----------|--------|---------|
| `POST /v1/messages` etc. | FastAPIInstrumentor | Root span covering the entire HTTP request lifecycle |
| `http receive` | ASGI layer | Server receiving the request body. In streaming requests this span lasts until the entire response is generated (ASGI receive loop waits for client disconnect), so it dominates the total time |
| `http send` | ASGI layer | Server sending data to the client. Each SSE chunk produces one `http send` (typically 0ms) |
| `bedrock.invoke` | Manual span | Non-streaming Bedrock API call duration |
| `bedrock.invoke_stream` | Manual span | Streaming Bedrock API call duration |

#### Request Flow

```
Client (browser/SDK)         KBP Server (ASGI)                     Bedrock
    │                            │                                    │
    │── POST /v1/messages ──────▶│                                    │
    │                            │  [http receive] request headers    │
    │                            │  [http receive] request body       │
    │                            │                                    │
    │                            │  Auth + format conversion          │
    │                            │                                    │
    │◀── 200 OK ─────────────────│  [http send] response headers     │
    │    content-type:           │   (200, text/event-stream)        │
    │    text/event-stream       │                                    │
    │                            │                                    │
    │                            │──── invoke_stream ────────────────▶│
    │                            │       [bedrock.invoke_stream]      │
    │                            │                                    │
    │                            │  [http receive] wait for client disconnect (parallel)
    │                            │                                    │
    │                            │◀── SSE chunk 1 ──────────────────│
    │◀── [http send] ───────────│                                    │
    │                            │◀── SSE chunk 2 ──────────────────│
    │◀── [http send] ───────────│                                    │
    │                            │◀── SSE chunk N ──────────────────│
    │◀── [http send] ───────────│                                    │
    │                            │                                    │
    │                            │◀── [stream end] ─────────────────│
    │◀── [http send: DONE] ─────│                                    │
    │                            │  [http receive] stream done       │
```

Key points:
- **`http receive` × 2 before streaming**: First receives request headers, second receives request body
- **`http send` before `bedrock.invoke_stream`**: Sends the HTTP 200 response headers + SSE content-type. This happens **before** any content is generated — it's the SSE protocol's "start streaming" signal
- **`http receive` after `bedrock.invoke_stream` starts**: ASGI receive loop waiting for client disconnect, runs **in parallel** with the streaming output
- **`http send` × N (0ms each)**: One per SSE event chunk pushed to client

#### Trace Example: Streaming Request (normal path)

```
[POST /v1/messages]  ──────────────────────────── 3.5s
  ├─ http receive                                 0ms  (request headers)
  ├─ http receive                                 0ms  (request body)
  ├─ http send                                    0ms  (response headers: 200 + SSE)
  ├─ bedrock.invoke_stream         ─────────── 3.3s
  │    bedrock.model_id: anthropic.claude-sonnet-4-20250514-v1:0
  │    bedrock.region:   us-west-2
  │    bedrock.api:      invoke_model_stream
  ├─ http receive  ─────────────────────────── 3.4s  (disconnect wait, parallel)
  └─ http send × N                               0ms  (per SSE chunk)
```

#### Trace Example: Failover Timeout Switch

```
[POST /v1/messages]  ──────────────────────────── 8.2s
  ├─ bedrock.invoke_stream (FAILED)  ──── 5.0s  ⚠️
  │    bedrock.failover: true
  │    exception: FirstContentTimeoutError
  │
  ├─ bedrock.invoke_stream           ──── 3.1s  ✅
  │    bedrock.failover: true
  │
  ├─ http send × N
  └─ http receive
```

### FAQ: Why Does One Request Produce Multiple Traces?

You may see two traces appearing at the same timestamp in X-Ray, looking like duplicates. In reality, the **client sent multiple HTTP requests**.

Typical scenario: Claude Code (CLI) sends multiple concurrent API requests in a single user interaction:

```
User asks a question in Claude Code
      │
      ├─── POST /v1/messages (Opus)     → Main conversation (slower, 4-5s)
      │
      └─── POST /v1/messages (Haiku)    → Auxiliary task like title generation (faster, 1s)
```

This appears as two independent traces in X-Ray:

| Trace | Model | Duration | Characteristics |
|-------|-------|----------|----------------|
| Trace A | `claude-opus-4-6` | 4.6s | Many `http receive` spans (heavy input/thinking) |
| Trace B | `claude-haiku-4-5` | 1.0s | Many `http send` spans (fast output) |

**How to identify**:
- Check the `bedrock.model_id` attribute — different models indicate concurrent client requests
- Check timestamps — same second but different durations
- Check User-Agent — same UA confirms same client

This is client behavior, not a KBP bug. No action needed.

### Local Testing with Jaeger

```bash
# Start Jaeger all-in-one (OTLP HTTP on 4318, UI on 16686)
docker run -d --name jaeger \
  -p 4318:4318 \
  -p 16686:16686 \
  jaegertracing/all-in-one:latest

# Start the app with OTLP exporter
KBR_OTEL_EXPORTER=otlp \
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
python -m uvicorn main:app
```

Then open `http://localhost:16686` to view traces.

---

## Log-Trace Correlation

When tracing is enabled, every log record automatically includes `trace_id` and `span_id` from the current OpenTelemetry span context. This is injected by `RequestContextFilter` in `log_context.py`.

### Correlation Workflow

1. Request arrives → FastAPI auto-instrumentation creates a root span
2. Every log within that request context includes the same `trace_id`
3. In CloudWatch, use Logs Insights to filter by `trace_id`
4. Click through to X-Ray console for the full trace waterfall

```mermaid
sequenceDiagram
    participant Client
    participant FastAPI
    participant Bedrock

    Client->>FastAPI: POST /v1/chat/completions
    Note right of FastAPI: Root span created<br/>trace_id = 1-abc...

    FastAPI->>FastAPI: Auth OK
    Note right of FastAPI: log: INFO Auth OK<br/>trace_id = 1-abc...

    FastAPI->>Bedrock: bedrock.invoke span
    Bedrock-->>FastAPI: Response (1.2s)
    Note right of FastAPI: log: INFO Bedrock OK<br/>trace_id = 1-abc...

    FastAPI-->>Client: 200 OK
    Note right of FastAPI: log: INFO 200 returned<br/>trace_id = 1-abc...

    Note over FastAPI: CloudWatch Logs Insights:<br/>filter trace_id = "1-abc..."<br/>→ shows all 3 logs

    Note over Bedrock: X-Ray Console:<br/>trace waterfall with<br/>FastAPI + bedrock.invoke spans
```

---

## Deployment Configuration

### Kubernetes ConfigMap

```yaml
# k8s/application/backend-configmap.yaml
KBR_LOG_FORMAT: "json"
KBR_LOG_LEVEL: "INFO"
KBR_ENABLE_METRICS: "true"
KBR_OTEL_EXPORTER: "xray"
```

### CloudWatch Observability Addon

Deployed via EKS addon `amazon-cloudwatch-observability`, which provides:
- **Fluent Bit**: Container log collection → CloudWatch Logs
- **CloudWatch Agent**: Container Insights metrics + OTLP HTTP receiver (port 4316) → X-Ray
- **Python auto-injection** (disabled): Turned off via annotation `inject-python: "false"`

```hcl
# iac/modules/eks-karpenter/eks.tf
amazon-cloudwatch-observability = {
  pod_identity_association = [{
    role_arn        = aws_iam_role.cloudwatch_agent[0].arn
    service_account = "cloudwatch-agent"
  }]
}
```

### Backend Pod Key Configuration

```yaml
# k8s/application/backend-deployment.yaml.template
metadata:
  annotations:
    # Disable addon's Python auto-injection to avoid breaking module paths
    instrumentation.opentelemetry.io/inject-python: "false"
env:
  # CloudWatch Agent DaemonSet runs on the host;
  # localhost inside a container can't reach it, so we need the host IP
  - name: NODE_IP
    valueFrom:
      fieldRef:
        fieldPath: status.hostIP
```

### Required IAM Permissions

The CloudWatch Agent's ServiceAccount is associated with an IAM role via Pod Identity:
- `CloudWatchAgentServerPolicy` — logs, metrics, Container Insights
- `AWSXrayWriteOnlyAccess` — X-Ray trace export

The backend pod itself does **not** need additional X-Ray permissions since traces are relayed through the CloudWatch Agent DaemonSet.

### Health Check Endpoint

`GET /health/metrics` returns current observability configuration:

```json
{
  "service": "kolya-br-proxy",
  "timestamp": "2026-04-11T12:00:00",
  "version": "1.0.0",
  "observability": {
    "log_level": "INFO",
    "log_format": "json",
    "metrics_enabled": true,
    "tracing_exporter": "xray"
  }
}
```

---

## Troubleshooting

### Metrics not appearing in CloudWatch

1. Verify `KBR_ENABLE_METRICS=true` is set
2. Check `GET /health/metrics` — `metrics_enabled` should be `true`
3. Ensure the EMF log group `/kbp/backend/metrics` exists or auto-creates
4. Check pod IAM role has `cloudwatch:PutMetricData` permission

### Traces not appearing in X-Ray

1. Verify `KBR_OTEL_EXPORTER=xray` is set
2. CloudWatch Agent DaemonSet must be running: `kubectl get ds -n amazon-cloudwatch`
3. Verify `NODE_IP` env var is injected: `kubectl exec <pod> -- env | grep NODE_IP`
4. Check pod can reach `http://$NODE_IP:4316`
5. Verify CloudWatch Agent IAM role has `AWSXrayWriteOnlyAccess` policy
6. Check CloudWatch Agent logs: `kubectl logs -n amazon-cloudwatch -l app.kubernetes.io/name=cloudwatch-agent`
7. `/health/*` paths won't appear in traces (excluded by design)

### JSON logs not showing extra fields

- Extra fields must be passed via `logger.info("msg", extra={"key": value})`
- Non-serializable values are automatically converted to strings
- Fields in `_BUILTIN_ATTRS` (Python LogRecord internals) are excluded by design

### Log level not taking effect

- `KBR_LOG_LEVEL` requires a restart — it's read once at startup by `configure_logging()`
- Valid values: `DEBUG`, `INFO`, `WARNING`, `ERROR` (case-insensitive)
- Third-party libraries (uvicorn, sqlalchemy) respect the root logger level

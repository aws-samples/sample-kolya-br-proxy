# API Reference

Kolya BR Proxy exposes three API groups:

| Group | Prefix | Auth | Purpose |
|-------|--------|------|---------|
| Gateway API | `/v1` | Bearer API Token | OpenAI-compatible chat completions |
| Admin API | `/admin` | Bearer JWT | User management, tokens, usage, audit |
| Health API | `/health` | None | Load balancer probes |

Base URL examples:
- Local: `http://localhost:8000`
- Production: `https://api.kbp.kolya.fun`

---

## 1. Gateway API (OpenAI-compatible)

All Gateway endpoints require an API token in the `Authorization` header:

```
Authorization: Bearer kbr_<your_token>
```

### POST /v1/chat/completions

Create a chat completion. Accepts OpenAI-format requests and proxies them to AWS Bedrock. Supports both Anthropic models (Claude) via InvokeModel API and non-Anthropic models (Amazon Nova, DeepSeek, Mistral, Llama, etc.) via Converse API.

**Request body** (`ChatCompletionRequest`):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | string | *required* | Bedrock model ID (e.g. `global.anthropic.claude-sonnet-4-5-20250929-v1:0`, `us.amazon.nova-pro-v1:0`, `deepseek.r1-v1:0`) |
| `messages` | array | *required* | Array of `ChatMessage` objects |
| `stream` | boolean | `false` | Enable SSE streaming |
| `temperature` | float | `1.0` | Sampling temperature (0.0 - 2.0) |
| `top_p` | float | `1.0` | Nucleus sampling (0.0 - 1.0) |
| `max_tokens` | integer | null | Maximum tokens to generate |
| `stop` | string \| array | null | Stop sequence(s) |
| `n` | integer | `1` | Number of choices |
| `presence_penalty` | float | `0.0` | Presence penalty (-2.0 to 2.0) |
| `frequency_penalty` | float | `0.0` | Frequency penalty (-2.0 to 2.0) |
| `user` | string | null | End-user identifier |
| `tools` | array | null | Tool/function definitions |
| `tool_choice` | string \| object | null | Tool selection strategy |

**Bedrock extension fields** (set via body or `X-Bedrock-*` headers):

| Field | Header | Description |
|-------|--------|-------------|
| `bedrock_guardrail_config` | `X-Bedrock-Guardrail-Id` + `X-Bedrock-Guardrail-Version` | Guardrail configuration |
| `bedrock_additional_model_request_fields` | `X-Bedrock-Additional-Fields` (JSON) | Extra model request fields |
| `bedrock_trace` | `X-Bedrock-Trace` | Trace mode (`ENABLED` / `DISABLED`) |
| `bedrock_performance_config` | `X-Bedrock-Performance-Config` (JSON) | Performance tuning |
| `bedrock_prompt_caching` | `X-Bedrock-Prompt-Caching` (JSON) | Prompt caching config |

**Thinking and effort** (via `bedrock_additional_model_request_fields`):

The gateway supports Anthropic's extended thinking and effort parameters. Pass them through `bedrock_additional_model_request_fields`:

```json
{
  "bedrock_additional_model_request_fields": {
    "thinking": {"type": "enabled", "budget_tokens": 5000},
    "effort": "medium"
  }
}
```

The `effort` parameter (`low` / `medium` / `high`) controls how much thinking effort the model uses. The gateway automatically wraps it into `output_config.effort` and injects the required `anthropic_beta` flag. When `thinking.budget_tokens` is set, `max_tokens` is automatically adjusted to satisfy the `max_tokens > budget_tokens` constraint.

> Headers override body fields when both are present.

**ChatMessage schema**:

| Field | Type | Description |
|-------|------|-------------|
| `role` | string | `system`, `user`, `assistant`, or `tool` |
| `content` | string \| array | Text string or array of `ContentPart` (multimodal) |
| `name` | string | Optional participant name |
| `tool_calls` | array | Tool calls (assistant messages) |
| `tool_call_id` | string | Tool call reference (tool messages) |

**ContentPart** (for multimodal):

```json
{ "type": "text", "text": "describe this image" }
{ "type": "image_url", "image_url": { "url": "data:image/png;base64,..." } }
```

#### Non-streaming example

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer kbr_your_token_here" \
  -d '{
    "model": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ],
    "temperature": 0.7,
    "max_tokens": 2048
  }'
```

**Response** (`ChatCompletionResponse`):

```json
{
  "id": "chatcmpl-abc123...",
  "object": "chat.completion",
  "created": 1700000000,
  "model": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello! How can I help you?"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 8,
    "total_tokens": 18
  }
}
```

#### Streaming example

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer kbr_your_token_here" \
  -d '{
    "model": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

**Streaming response** (SSE `text/event-stream`):

```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1700000000,"model":"...","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1700000000,"model":"...","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

Heartbeat comments (`: heartbeat`) are sent every 15 seconds to keep the connection alive.

#### Tool use (function calling)

The gateway supports OpenAI-compatible tool use. Tool call deltas stream incrementally in the same format as OpenAI. The `finish_reason` is `tool_calls` when the model invokes a tool.

#### Error responses

```json
{
  "error": {
    "message": "Token quota exceeded. Used: $5.00, Quota: $5.00",
    "type": "server_error",
    "code": "internal_error",
    "param": null
  }
}
```

| Status | Meaning |
|--------|---------|
| 400 | Invalid request (bad model name, malformed body) |
| 401 | Missing or invalid API token |
| 403 | Token lacks access to requested model |
| 429 | Token quota exceeded |
| 500 | Internal server error |

#### OpenAI SDK usage

```python
from openai import OpenAI

client = OpenAI(
    api_key="kbr_your_token_here",  # pragma: allowlist secret
    base_url="http://localhost:8000/v1",
)

stream = client.chat.completions.create(
    model="global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    messages=[{"role": "user", "content": "Hello!"}],
    stream=True,
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

### GET /v1/models

List models the current token has access to. Returns OpenAI-compatible model list.

**Response**:

```json
{
  "object": "list",
  "data": [
    {
      "id": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
      "object": "model",
      "created": 1700000000,
      "owned_by": "anthropic"
    }
  ]
}
```

---

## 2. Admin API

All Admin endpoints (except OAuth login URLs) require a JWT access token:

```
Authorization: Bearer <jwt_access_token>
```

### 2.1 Authentication

#### GET /admin/auth/microsoft/login

Get Microsoft OAuth authorization URL.

| Parameter | In | Type | Description |
|-----------|-----|------|-------------|
| `redirect_uri` | query | string | Redirect URI after authorization |

**Response**:

```json
{
  "authorization_url": "https://login.microsoftonline.com/.../authorize?...",
  "state": "random_csrf_state"
}
```

#### POST /admin/auth/microsoft/callback

Handle Microsoft OAuth callback. Creates or links user account.

| Parameter | In | Type | Description |
|-----------|-----|------|-------------|
| `code` | query | string | Authorization code from Microsoft |
| `redirect_uri` | query | string | Redirect URI used in authorization |
| `state` | query | string | State parameter for CSRF protection |

**Response** (`LoginResponse`):

```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "is_active": true,
    "is_admin": false,
    "email_verified": true,
    "current_balance": "5.00"
  }
}
```

#### GET /admin/auth/cognito/login

Get AWS Cognito OAuth authorization URL.

| Parameter | In | Type | Description |
|-----------|-----|------|-------------|
| `redirect_uri` | query | string | Redirect URI after authorization |

**Response**: Same structure as Microsoft login.

#### POST /admin/auth/cognito/callback

Handle AWS Cognito OAuth callback. Creates or links user account.

| Parameter | In | Type | Description |
|-----------|-----|------|-------------|
| `code` | query | string | Authorization code from Cognito |
| `redirect_uri` | query | string | Redirect URI used in authorization |
| `state` | query | string | State parameter for CSRF protection |

**Response**: Same `LoginResponse` structure as Microsoft callback.

#### POST /admin/auth/refresh

Refresh access token using refresh token (with automatic rotation).

**Request body**:

```json
{ "refresh_token": "eyJ..." }
```

**Response**: `LoginResponse` with new `access_token` and `refresh_token`.

> Old refresh token is invalidated after rotation. Token reuse triggers theft detection.

#### POST /admin/auth/revoke

Revoke a specific refresh token.

**Request body**:

```json
{ "refresh_token": "eyJ..." }
```

**Response**: `{ "message": "Refresh token revoked successfully" }`

#### POST /admin/auth/revoke-all

Revoke all refresh tokens for the current user (logout from all devices). Requires JWT.

**Response**: `{ "message": "Revoked N refresh tokens successfully" }`

#### GET /admin/auth/me

Get current user information.

**Response**: `UserResponse` object (see Microsoft callback response).

#### PUT /admin/auth/me

Update current user profile.

**Request body**:

```json
{ "first_name": "Jane", "last_name": "Smith" }
```

**Response**: Updated `UserResponse`.

### 2.2 Token Management

#### POST /admin/tokens

Create a new API token.

**Request body**:

```json
{
  "name": "My API Key",
  "expires_at": "2026-12-31T23:59:59",
  "quota_usd": 100.00,
  "allowed_ips": ["192.168.1.0/24"]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Token display name |
| `expires_at` | datetime | no | Expiration timestamp |
| `quota_usd` | decimal | no | Usage quota in USD |
| `allowed_ips` | array | no | IP allowlist (CIDR) |

**Response** (201): `TokenWithKeyResponse` -- includes the plain token value. This is the only time the plain token is returned.

```json
{
  "id": "uuid",
  "name": "My API Key",
  "token": "kbr_abc123...",
  "expires_at": "2026-12-31T23:59:59",
  "quota_usd": "100.00",
  "used_usd": "0.00",
  "remaining_quota": "100.00",
  "allowed_ips": ["192.168.1.0/24"],
  "is_active": true,
  "is_expired": false,
  "is_quota_exceeded": false,
  "created_at": "2026-01-01T00:00:00",
  "last_used_at": null
}
```

#### GET /admin/tokens

List all tokens for the current user.

| Parameter | In | Type | Default | Description |
|-----------|-----|------|---------|-------------|
| `include_inactive` | query | boolean | `false` | Include inactive/revoked tokens |

**Response**: Array of `TokenResponse`.

#### GET /admin/tokens/{token_id}

Get token details by UUID.

#### PUT /admin/tokens/{token_id}

Update token settings.

**Request body** (all fields optional):

```json
{
  "name": "Renamed Key",
  "expires_at": "2027-06-30T00:00:00",
  "quota_usd": 200.00,
  "allowed_ips": ["10.0.0.0/8"],
  "is_active": true
}
```

#### DELETE /admin/tokens/{token_id}

Permanently delete a token. Returns 204 No Content.

#### POST /admin/tokens/{token_id}/revoke

Deactivate a token (can be reactivated via PUT).

**Response**: Updated `TokenResponse` with `is_active: false`.

#### GET /admin/tokens/{token_id}/plain

Retrieve the decrypted plain token value.

**Response**: `{ "token": "kbr_..." }`

### 2.3 Model Management

#### GET /admin/models/aws-available

List available Bedrock models from AWS. Results are cached for 12 hours.

**Response**:

```json
{
  "models": [
    {
      "model_id": "anthropic.claude-sonnet-4-5-20250929-v1:0",
      "model_name": "Claude 4.5 Sonnet",
      "friendly_name": "claude-sonnet-4-5",
      "provider": "bedrock",
      "streaming_supported": true
    }
  ]
}
```

#### GET /admin/models

List enabled models from the database.

| Parameter | In | Type | Description |
|-----------|-----|------|-------------|
| `token_id` | query | string | Optional -- filter by token UUID |

**Response**:

```json
{
  "models": [
    {
      "id": "uuid",
      "model_name": "claude-sonnet-4-5",
      "model_id": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
      "friendly_name": "claude-sonnet-4-5",
      "provider": "bedrock",
      "streaming_supported": true,
      "is_active": true
    }
  ]
}
```

#### POST /admin/models

Add a model to a token's allowed list.

**Request body**:

```json
{
  "token_id": "uuid",
  "model_name": "claude-sonnet-4-5"
}
```

**Response**: `{ "message": "Model claude-sonnet-4-5 added successfully", "id": "uuid" }`

#### DELETE /admin/models/{model_id}

Soft-delete a model configuration.

**Response**: `{ "message": "Model claude-sonnet-4-5 deleted successfully" }`

### 2.4 Usage Statistics

#### GET /admin/usage/stats

Get aggregated usage statistics for the current user.

| Parameter | In | Type | Description |
|-----------|-----|------|-------------|
| `start_date` | query | datetime | Optional custom range start |
| `end_date` | query | datetime | Optional custom range end |

**Response**:

```json
{
  "current_month_cost": "12.34",
  "current_month_requests": 150,
  "current_month_tokens": 50000,
  "last_30_days_cost": "45.67",
  "last_30_days_requests": 500,
  "total_cost": "123.45",
  "total_requests": 2000
}
```

#### GET /admin/usage/by-token

Usage statistics grouped by API token.

| Parameter | In | Type | Description |
|-----------|-----|------|-------------|
| `token_id` | query | string | Optional filter |
| `start_date` | query | datetime | Optional start |
| `end_date` | query | datetime | Optional end |

**Response**: Array of `UsageByTokenResponse`.

#### GET /admin/usage/by-model

Usage statistics grouped by model.

| Parameter | In | Type | Description |
|-----------|-----|------|-------------|
| `model` | query | string | Optional model filter |
| `start_date` | query | datetime | Optional start |
| `end_date` | query | datetime | Optional end |

**Response**: Array of `UsageByModelResponse`.

#### GET /admin/usage/aggregated-stats

Time-series usage data.

| Parameter | In | Type | Required | Description |
|-----------|-----|------|----------|-------------|
| `start_date` | query | datetime | yes | Range start |
| `end_date` | query | datetime | yes | Range end |
| `granularity` | query | string | no | `hourly`, `daily` (default), `weekly`, `monthly` |
| `token_id` | query | string | no | Filter by token |

**Response**:

```json
{
  "granularity": "daily",
  "start_date": "2026-01-01T00:00:00",
  "end_date": "2026-01-31T23:59:59",
  "data": [
    {
      "time_bucket": "2026-01-15",
      "call_count": 42,
      "total_prompt_tokens": 10000,
      "total_completion_tokens": 5000,
      "total_tokens": 15000,
      "total_cost": "3.21"
    }
  ]
}
```

#### GET /admin/usage/token-summary

Per-token usage summary for a time period.

| Parameter | In | Type | Required | Description |
|-----------|-----|------|----------|-------------|
| `start_date` | query | datetime | yes | Range start |
| `end_date` | query | datetime | yes | Range end |

**Response**: Array of `TokenUsageSummary`:

```json
[
  {
    "token_id": "uuid",
    "token_name": "My Key",
    "call_count": 100,
    "total_tokens": 25000,
    "total_cost": "8.50"
  }
]
```

#### GET /admin/usage/tokens-timeseries

Multi-token time-series data for chart overlays.

| Parameter | In | Type | Required | Description |
|-----------|-----|------|----------|-------------|
| `start_date` | query | datetime | yes | Range start |
| `end_date` | query | datetime | yes | Range end |
| `token_ids` | query | string | yes | Comma-separated token UUIDs |
| `granularity` | query | string | no | `hourly`, `daily`, `weekly`, `monthly` |
| `metric` | query | string | no | `calls` (default), `tokens`, `cost` |

**Response**:

```json
{
  "granularity": "daily",
  "metric": "calls",
  "series": [
    {
      "token_id": "uuid",
      "token_name": "Key A",
      "data": [
        { "time_bucket": "2026-01-15", "value": 42 }
      ]
    }
  ]
}
```

### 2.5 Audit Logs

#### GET /admin/audit-logs

List audit logs with pagination and filters.

| Parameter | In | Type | Default | Description |
|-----------|-----|------|---------|-------------|
| `page` | query | integer | `1` | Page number (1-based) |
| `page_size` | query | integer | `50` | Items per page (max 200) |
| `user_id` | query | uuid | null | Filter by user |
| `action` | query | string | null | Filter by action type |
| `success` | query | boolean | null | Filter by outcome |
| `start_date` | query | datetime | null | From date |
| `end_date` | query | datetime | null | To date |

**Response**:

```json
{
  "items": [
    {
      "id": "uuid",
      "user_id": "uuid",
      "action": "login_success",
      "success": true,
      "details": null,
      "error_message": null,
      "ip_address": "1.2.3.4",
      "user_agent": "Mozilla/5.0...",
      "resource_type": null,
      "resource_id": null,
      "created_at": "2026-01-15T10:30:00"
    }
  ],
  "total": 150,
  "page": 1,
  "page_size": 50,
  "total_pages": 3
}
```

#### GET /admin/audit-logs/summary

Audit activity summary with counts by action type.

| Parameter | In | Type | Description |
|-----------|-----|------|-------------|
| `start_date` | query | datetime | Optional from date |
| `end_date` | query | datetime | Optional to date |

**Response**:

```json
{
  "total": 500,
  "success_count": 480,
  "failure_count": 20,
  "action_counts": {
    "login_success": 200,
    "token_refresh_success": 150,
    "login_failed": 20,
    "logout_all_devices": 5
  }
}
```

---

## 3. Health API

No authentication required.

#### GET /health/

Basic health check for load balancer.

```json
{ "status": "healthy", "timestamp": "2026-01-15T10:00:00", "service": "kolya-br-proxy" }
```

#### GET /health/ready

Readiness probe. Verifies database connectivity. Returns 503 if unhealthy.

```json
{
  "status": "ready",
  "timestamp": "2026-01-15T10:00:00",
  "service": "kolya-br-proxy",
  "components": {
    "database": { "status": "healthy", "message": "Connected" }
  }
}
```

#### GET /health/live

Liveness probe for Kubernetes.

```json
{ "status": "alive", "timestamp": "2026-01-15T10:00:00", "service": "kolya-br-proxy" }
```

#### GET /health/metrics

Basic metrics endpoint.

```json
{
  "service": "kolya-br-proxy",
  "timestamp": "2026-01-15T10:00:00",
  "version": "1.0.0",
  "debug_mode": false,
  "metrics": {
    "health_checks_total": "counter",
    "requests_total": "counter",
    "request_duration_seconds": "histogram"
  }
}
```

# API 参考

Kolya BR Proxy 提供三组 API：

| 分组 | 前缀 | 认证方式 | 用途 |
|------|------|----------|------|
| Gateway API | `/v1` | Bearer API Token | OpenAI 兼容的聊天补全 |
| Admin API | `/admin` | Bearer JWT | 用户管理、令牌、用量、审计 |
| Health API | `/health` | 无 | 负载均衡器探针 |

Base URL 示例：
- 本地开发：`http://localhost:8000`
- 生产环境：`https://api.kbp.kolya.fun`

---

## 1. Gateway API（OpenAI 兼容）

所有 Gateway 端点需要在 `Authorization` 请求头中携带 API Token：

```
Authorization: Bearer kbr_<your_token>
```

### POST /v1/chat/completions

创建聊天补全。接受 OpenAI 格式的请求，转发至 AWS Bedrock。支持 Anthropic 模型（Claude，通过 InvokeModel API）和非 Anthropic 模型（Amazon Nova、DeepSeek、Mistral、Llama 等，通过 Converse API）。

**请求体** (`ChatCompletionRequest`)：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `model` | string | *必填* | Bedrock 模型 ID（如 `global.anthropic.claude-sonnet-4-5-20250929-v1:0`、`us.amazon.nova-pro-v1:0`、`deepseek.r1-v1:0`） |
| `messages` | array | *必填* | `ChatMessage` 对象数组 |
| `stream` | boolean | `false` | 启用 SSE 流式输出 |
| `temperature` | float | `1.0` | 采样温度（0.0 - 2.0） |
| `top_p` | float | `1.0` | 核采样（0.0 - 1.0） |
| `max_tokens` | integer | null | 最大生成 token 数 |
| `stop` | string \| array | null | 停止序列 |
| `n` | integer | `1` | 生成选项数 |
| `presence_penalty` | float | `0.0` | 存在惩罚（-2.0 到 2.0） |
| `frequency_penalty` | float | `0.0` | 频率惩罚（-2.0 到 2.0） |
| `user` | string | null | 终端用户标识 |
| `tools` | array | null | 工具/函数定义 |
| `tool_choice` | string \| object | null | 工具选择策略 |

**Bedrock 扩展字段**（可通过请求体或 `X-Bedrock-*` 请求头设置）：

| 字段 | 请求头 | 说明 |
|------|--------|------|
| `bedrock_guardrail_config` | `X-Bedrock-Guardrail-Id` + `X-Bedrock-Guardrail-Version` | 护栏配置 |
| `bedrock_additional_model_request_fields` | `X-Bedrock-Additional-Fields` (JSON) | 额外模型请求字段 |
| `bedrock_trace` | `X-Bedrock-Trace` | 追踪模式（`ENABLED` / `DISABLED`） |
| `bedrock_performance_config` | `X-Bedrock-Performance-Config` (JSON) | 性能调优 |
| `bedrock_prompt_caching` | `X-Bedrock-Prompt-Caching` (JSON) | 提示缓存配置 |

**Thinking 和 effort 参数**（通过 `bedrock_additional_model_request_fields`）：

网关支持 Anthropic 的扩展思考和 effort 参数。通过 `bedrock_additional_model_request_fields` 传递：

```json
{
  "bedrock_additional_model_request_fields": {
    "thinking": {"type": "enabled", "budget_tokens": 5000},
    "effort": "medium"
  }
}
```

`effort` 参数（`low` / `medium` / `high`）控制模型的思考深度。网关会自动将其包装到 `output_config.effort` 中，并注入所需的 `anthropic_beta` 标志。当设置了 `thinking.budget_tokens` 时，`max_tokens` 会自动调整以满足 `max_tokens > budget_tokens` 的约束。

> 同时设置请求头和请求体时，请求头优先。

**ChatMessage 结构**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `role` | string | `system`、`user`、`assistant` 或 `tool` |
| `content` | string \| array | 文本字符串或 `ContentPart` 数组（多模态） |
| `name` | string | 可选的参与者名称 |
| `tool_calls` | array | 工具调用（assistant 消息） |
| `tool_call_id` | string | 工具调用引用（tool 消息） |

**ContentPart**（多模态）：

```json
{ "type": "text", "text": "描述这张图片" }
{ "type": "image_url", "image_url": { "url": "data:image/png;base64,..." } }
```

#### 非流式示例

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

**响应** (`ChatCompletionResponse`)：

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

#### 流式示例

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

**流式响应**（SSE `text/event-stream`）：

```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1700000000,"model":"...","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1700000000,"model":"...","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

每 15 秒发送心跳注释（`: heartbeat`）以保持连接。

#### 工具调用（函数调用）

网关支持 OpenAI 兼容的工具调用。工具调用增量以与 OpenAI 相同的格式流式传输。模型调用工具时 `finish_reason` 为 `tool_calls`。

#### 错误响应

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

| 状态码 | 含义 |
|--------|------|
| 400 | 请求无效（错误的模型名称、格式错误的请求体） |
| 401 | 缺少或无效的 API Token |
| 403 | Token 无权访问请求的模型 |
| 429 | Token 配额已用尽 |
| 500 | 服务器内部错误 |

#### OpenAI SDK 调用方式

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

列出当前 Token 有权访问的模型。返回 OpenAI 兼容的模型列表。

**响应**：

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

除 OAuth 登录 URL 外，所有 Admin 端点需要 JWT 访问令牌：

```
Authorization: Bearer <jwt_access_token>
```

### 2.1 认证

#### GET /admin/auth/microsoft/login

获取 Microsoft OAuth 授权 URL。

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `redirect_uri` | query | string | 授权后的重定向 URI |

**响应**：

```json
{
  "authorization_url": "https://login.microsoftonline.com/.../authorize?...",
  "state": "random_csrf_state"
}
```

#### POST /admin/auth/microsoft/callback

处理 Microsoft OAuth 回调。创建或关联用户账户。

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `code` | query | string | Microsoft 返回的授权码 |
| `redirect_uri` | query | string | 授权时使用的重定向 URI |
| `state` | query | string | CSRF 防护的 state 参数 |

**响应** (`LoginResponse`)：

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

获取 AWS Cognito OAuth 授权 URL。

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `redirect_uri` | query | string | 授权后的重定向 URI |

**响应**：与 Microsoft 登录结构相同。

#### POST /admin/auth/cognito/callback

处理 AWS Cognito OAuth 回调。创建或关联用户账户。

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `code` | query | string | Cognito 返回的授权码 |
| `redirect_uri` | query | string | 授权时使用的重定向 URI |
| `state` | query | string | CSRF 防护的 state 参数 |

**响应**：与 Microsoft 回调的 `LoginResponse` 结构相同。

#### POST /admin/auth/refresh

使用刷新令牌获取新的访问令牌（自动轮换）。

**请求体**：

```json
{ "refresh_token": "eyJ..." }
```

**响应**：`LoginResponse`，包含新的 `access_token` 和 `refresh_token`。

> 轮换后旧的刷新令牌将失效。重复使用已轮换的令牌会触发盗用检测。

#### POST /admin/auth/revoke

撤销指定的刷新令牌。

**请求体**：

```json
{ "refresh_token": "eyJ..." }
```

**响应**：`{ "message": "Refresh token revoked successfully" }`

#### POST /admin/auth/revoke-all

撤销当前用户的所有刷新令牌（从所有设备登出）。需要 JWT。

**响应**：`{ "message": "Revoked N refresh tokens successfully" }`

#### GET /admin/auth/me

获取当前用户信息。

**响应**：`UserResponse` 对象（见 Microsoft 回调响应）。

#### PUT /admin/auth/me

更新当前用户资料。

**请求体**：

```json
{ "first_name": "Jane", "last_name": "Smith" }
```

**响应**：更新后的 `UserResponse`。

### 2.2 令牌管理

#### POST /admin/tokens

创建新的 API Token。

**请求体**：

```json
{
  "name": "My API Key",
  "expires_at": "2026-12-31T23:59:59",
  "quota_usd": 100.00,
  "allowed_ips": ["192.168.1.0/24"]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | Token 显示名称 |
| `expires_at` | datetime | 否 | 过期时间 |
| `quota_usd` | decimal | 否 | 使用配额（美元） |
| `allowed_ips` | array | 否 | IP 白名单（CIDR） |

**响应** (201)：`TokenWithKeyResponse` -- 包含明文 Token 值。这是唯一一次返回明文 Token。

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

列出当前用户的所有 Token。

| 参数 | 位置 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `include_inactive` | query | boolean | `false` | 包含已停用/撤销的 Token |

**响应**：`TokenResponse` 数组。

#### GET /admin/tokens/{token_id}

按 UUID 获取 Token 详情。

#### PUT /admin/tokens/{token_id}

更新 Token 设置。

**请求体**（所有字段可选）：

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

永久删除 Token。返回 204 No Content。

#### POST /admin/tokens/{token_id}/revoke

停用 Token（可通过 PUT 重新激活）。

**响应**：更新后的 `TokenResponse`，`is_active: false`。

#### GET /admin/tokens/{token_id}/plain

获取解密后的明文 Token 值。

**响应**：`{ "token": "kbr_..." }`

### 2.3 模型管理

#### GET /admin/models/aws-available

列出 AWS Bedrock 可用模型。结果缓存 12 小时。

**响应**：

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

列出数据库中已启用的模型。

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `token_id` | query | string | 可选 -- 按 Token UUID 过滤 |

**响应**：

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

为 Token 添加允许使用的模型。

**请求体**：

```json
{
  "token_id": "uuid",
  "model_name": "claude-sonnet-4-5"
}
```

**响应**：`{ "message": "Model claude-sonnet-4-5 added successfully", "id": "uuid" }`

#### DELETE /admin/models/{model_id}

软删除模型配置。

**响应**：`{ "message": "Model claude-sonnet-4-5 deleted successfully" }`

### 2.4 用量统计

#### GET /admin/usage/stats

获取当前用户的汇总用量统计。

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `start_date` | query | datetime | 可选的自定义范围起始 |
| `end_date` | query | datetime | 可选的自定义范围结束 |

**响应**：

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

按 API Token 分组的用量统计。

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `token_id` | query | string | 可选过滤 |
| `start_date` | query | datetime | 可选起始 |
| `end_date` | query | datetime | 可选结束 |

**响应**：`UsageByTokenResponse` 数组。

#### GET /admin/usage/by-model

按模型分组的用量统计。

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `model` | query | string | 可选模型过滤 |
| `start_date` | query | datetime | 可选起始 |
| `end_date` | query | datetime | 可选结束 |

**响应**：`UsageByModelResponse` 数组。

#### GET /admin/usage/aggregated-stats

时间序列用量数据。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| `start_date` | query | datetime | 是 | 范围起始 |
| `end_date` | query | datetime | 是 | 范围结束 |
| `granularity` | query | string | 否 | `hourly`、`daily`（默认）、`weekly`、`monthly` |
| `token_id` | query | string | 否 | 按 Token 过滤 |

**响应**：

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

指定时间段内按 Token 汇总的用量。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| `start_date` | query | datetime | 是 | 范围起始 |
| `end_date` | query | datetime | 是 | 范围结束 |

**响应**：`TokenUsageSummary` 数组：

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

多 Token 时间序列数据，用于图表叠加显示。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| `start_date` | query | datetime | 是 | 范围起始 |
| `end_date` | query | datetime | 是 | 范围结束 |
| `token_ids` | query | string | 是 | 逗号分隔的 Token UUID |
| `granularity` | query | string | 否 | `hourly`、`daily`、`weekly`、`monthly` |
| `metric` | query | string | 否 | `calls`（默认）、`tokens`、`cost` |

**响应**：

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

### 2.5 审计日志

#### GET /admin/audit-logs

分页列出审计日志，支持过滤。

| 参数 | 位置 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `page` | query | integer | `1` | 页码（从 1 开始） |
| `page_size` | query | integer | `50` | 每页条数（最大 200） |
| `user_id` | query | uuid | null | 按用户过滤 |
| `action` | query | string | null | 按操作类型过滤 |
| `success` | query | boolean | null | 按结果过滤 |
| `start_date` | query | datetime | null | 起始日期 |
| `end_date` | query | datetime | null | 结束日期 |

**响应**：

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

按操作类型统计审计活动摘要。

| 参数 | 位置 | 类型 | 说明 |
|------|------|------|------|
| `start_date` | query | datetime | 可选起始日期 |
| `end_date` | query | datetime | 可选结束日期 |

**响应**：

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

无需认证。

#### GET /health/

基础健康检查，供负载均衡器使用。

```json
{ "status": "healthy", "timestamp": "2026-01-15T10:00:00", "service": "kolya-br-proxy" }
```

#### GET /health/ready

就绪探针。验证数据库连通性。不健康时返回 503。

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

Kubernetes 存活探针。

```json
{ "status": "alive", "timestamp": "2026-01-15T10:00:00", "service": "kolya-br-proxy" }
```

#### GET /health/metrics

基础指标端点。

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

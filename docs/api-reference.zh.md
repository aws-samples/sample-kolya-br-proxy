# API 参考

BR Enterprise Proxy 提供四组 API：

| 分组 | 前缀 | 认证方式 | 用途 |
|------|------|----------|------|
| Gateway API (OpenAI) | `/v1` | `Authorization: Bearer` | OpenAI 兼容的聊天补全 |
| Gateway API (Anthropic) | `/v1` | `x-api-key` 请求头 | Anthropic Messages API 兼容 |
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

`thinking.type` 支持 `"enabled"`、`"disabled"` 或 `"adaptive"` 三种模式。`effort` 参数（`low` / `medium` / `high`）控制模型的思考深度。网关会自动将其包装到 `output_config.effort` 中，并注入所需的 `anthropic_beta` 标志。当设置了 `thinking.budget_tokens` 时，`max_tokens` 会自动调整以满足 `max_tokens > budget_tokens` 的约束。

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

---

## 1b. Gateway API（Anthropic Messages API 兼容）

所有 Anthropic 兼容端点需要在 `x-api-key` 请求头中携带 API Key：

```
x-api-key: kbr_<your_token>
```

> 同一个 `kbr_` API Key 可同时用于 OpenAI 和 Anthropic 端点。代理根据端点路径和认证头格式自动路由。

### POST /v1/messages

创建消息。接受 Anthropic Messages API 格式的请求，转发至 AWS Bedrock。支持扩展思考（thinking）、工具调用、提示缓存等所有 Anthropic 原生功能。

**请求体** (`AnthropicMessagesRequest`)：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `model` | string | *必填* | Bedrock 模型 ID **或** Anthropic 短格式名称（如 `global.anthropic.claude-sonnet-4-5-20250929-v1:0` 或 `claude-sonnet-4-5-20250929`）。代理会自动归一化两种格式进行权限校验，并以 Bedrock ID 路由请求。 |
| `messages` | array | *必填* | 消息对象数组（role: `user` 或 `assistant`） |
| `max_tokens` | integer | *必填* | 最大生成 token 数 |
| `system` | string \| array | null | 系统提示（字符串或含可选 `cache_control` 的内容块数组） |
| `temperature` | float | null | 采样温度（0.0 - 1.0） |
| `top_p` | float | null | 核采样（0.0 - 1.0） |
| `top_k` | integer | null | Top-K 采样 |
| `stop_sequences` | array | null | 停止序列 |
| `stream` | boolean | `false` | 启用 SSE 流式输出 |
| `tools` | array | null | 工具定义（Anthropic 格式） |
| `tool_choice` | object | null | 工具选择策略 |
| `metadata` | object | null | 请求元数据 |
| `thinking` | object | null | 扩展思考配置。支持 `type: "enabled"`、`"disabled"` 或 `"adaptive"`。示例：`{"type": "enabled", "budget_tokens": N}` |

**消息内容块类型**：

```json
{"type": "text", "text": "Hello!"}
{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}}
{"type": "tool_use", "id": "toolu_...", "name": "get_weather", "input": {"city": "London"}}
{"type": "tool_result", "tool_use_id": "toolu_...", "content": "晴，22°C"}
```

#### 非流式示例

```bash
curl -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: kbr_your_token_here" \
  -d '{
    "model": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "max_tokens": 1024,
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

**响应** (`AnthropicMessagesResponse`)：

```json
{
  "id": "msg_abc123...",
  "type": "message",
  "role": "assistant",
  "content": [
    {"type": "text", "text": "Hello! How can I help you?"}
  ],
  "model": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
  "stop_reason": "end_turn",
  "stop_sequence": null,
  "usage": {
    "input_tokens": 10,
    "output_tokens": 8
  }
}
```

#### 流式示例

```bash
curl -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: kbr_your_token_here" \
  -d '{
    "model": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

**流式响应**（SSE `text/event-stream`，Anthropic 格式）：

```
event: message_start
data: {"type":"message_start","message":{"id":"msg_...","type":"message","role":"assistant","content":[],"model":"...","stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":10,"output_tokens":0}}}

event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}

event: content_block_stop
data: {"type":"content_block_stop","index":0}

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"output_tokens":8}}

event: message_stop
data: {"type":"message_stop"}
```

#### 扩展思考示例

```bash
curl -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: kbr_your_token_here" \
  -d '{
    "model": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "max_tokens": 8192,
    "thinking": {"type": "enabled", "budget_tokens": 4096},
    "messages": [{"role": "user", "content": "请逐步解题：15 * 27 + 33"}]
  }'
```

**Thinking Block 处理**：

当使用 `thinking.type: "adaptive"` 时，对话历史中可能包含 `thinking` 或 `redacted_thinking` 类型的内容块（signature-only thinking blocks）。代理会自动剥离这些块后再发送到 Bedrock，因为 Bedrock 的 Converse API 不支持 adaptive 模式的 thinking blocks。这确保了与 Claude Code 等客户端的兼容性。

#### 错误响应（Anthropic 格式）

```json
{
  "type": "error",
  "error": {
    "type": "authentication_error",
    "message": "Invalid or expired API key"
  }
}
```

| 状态码 | 错误类型 | 含义 |
|--------|----------|------|
| 400 | `invalid_request_error` | 请求无效（错误的模型名称、格式错误的请求体） |
| 401 | `authentication_error` | 缺少或无效的 API Key |
| 403 | `permission_error` | Token 无权访问请求的模型 |
| 429 | `rate_limit_error` | Token 配额已用尽 |
| 500 | `api_error` | 服务器内部错误 |

#### Anthropic SDK 调用方式

```python
import anthropic

client = anthropic.Anthropic(
    api_key="kbr_your_token_here",  # pragma: allowlist secret
    base_url="http://localhost:8000/v1",
)

message = client.messages.create(
    model="global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello!"}],
)
print(message.content[0].text)

# 流式输出
with client.messages.stream(
    model="global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello!"}],
) as stream:
    for text in stream.text_stream:
        print(text, end="", flush=True)
```

#### 配合 Claude Code CLI 使用

本代理完全兼容 Claude Code CLI。所有 Token 默认使用 `sk-ant-api03` 前缀，生成与官方 Anthropic API 格式一致的密钥。

**环境变量配置**：

```bash
export ANTHROPIC_BASE_URL="https://your-api-domain"
export ANTHROPIC_API_KEY="sk-ant-api03_xxxxxxx"  # pragma: allowlist secret
export CLAUDE_MODEL="us.anthropic.claude-sonnet-4-5-20250514-v1:0"
```

**~/.claude/settings.json 配置示例**：

```json
{
  "model": "us.anthropic.claude-sonnet-4-5-20250514-v1:0",
  "smallModel": "your-haiku-model-id",
  "largeModel": "your-opus-model-id"
}
```

配置完成后，Claude Code CLI 会自动使用本代理访问 Bedrock 模型，提供与官方 API 一致的使用体验。

---

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

### 权限控制（RBAC）

Admin API 使用基于角色的访问控制，包含两个角色：

| 角色 | 权限 |
|------|------|
| `super_admin` | 完全访问所有端点和资源 |
| `admin` | 受 `permissions` 对象控制的有限访问 |

Admin 用户有一个 `permissions` JSON 对象，控制其可管理的资源：

| 权限 | 取值 | 控制范围 |
|------|------|----------|
| `manage_api_keys` | `true`/`"all"`、`[id, ...]`、`false` | API Token 增删改查 |
| `manage_teams` | `true`/`"all"`、`[id, ...]`、`false` | 团队增删改查 |
| `manage_models` | `true`/`"all"`、`[id, ...]`、`false` | 模型配置 |
| `view_usage` | `true`/`false` | 用量统计 |
| `view_monitor` | `true`/`false` | 请求监控 |

- `true` 或 `"all"`：对该类型所有资源有完全访问权限
- UUID 数组：仅可访问指定资源
- `false` 或缺失：无权限（403）

各端点所需权限：

| 端点分组 | 所需权限 |
|----------|----------|
| `/admin/tokens/*` | `manage_api_keys` |
| `/admin/teams/*` | `manage_teams` |
| `/admin/models/*` | `manage_models` |
| `/admin/usage/*` | `view_usage` |
| `/admin/monitor/*` | `view_monitor` |
| `/admin/users/*` | 仅 `super_admin` 角色 |
| `/admin/audit-logs` | 仅 `super_admin` 角色 |
| `/admin/audit-logs/activity` | 所有管理员 |

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
    "is_admin": true,
    "role": "admin",
    "permissions": {
      "manage_api_keys": "all", // pragma: allowlist secret
      "manage_teams": ["uuid1", "uuid2"],
      "manage_models": true,
      "view_usage": true,
      "view_monitor": true
    },
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

创建新的 API Token。所有 Token 默认使用 `sk-ant-api03` 前缀，与 Claude Code / Anthropic SDK 兼容。

**请求体**：

```json
{
  "name": "My API Key",
  "description": "用于生产环境的主要 Token",
  "expires_at": "2026-12-31T23:59:59",
  "quota_usd": 100.00,
  "monthly_quota_usd": 50.00,
  "monthly_reset_policy": "reset",
  "allowed_ips": ["192.168.1.0/24"],
  "token_metadata": {"env": "production", "team": "backend"}
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | Token 显示名称 |
| `description` | string | 否 | Token 描述信息 |
| `expires_at` | datetime | 否 | 过期时间 |
| `quota_usd` | decimal | 否 | 总使用配额（美元） |
| `monthly_quota_usd` | decimal | 否 | 每月使用配额（美元） |
| `monthly_reset_policy` | string | 否 | 月度配额重置策略：`"reset"`（重置）或 `"rollover"`（累积） |
| `allowed_ips` | array | 否 | IP 白名单（CIDR） |
| `token_metadata` | object | 否 | 自定义元数据（键值对） |

**响应** (201)：`TokenWithKeyResponse` -- 包含明文 Token 值。这是唯一一次返回明文 Token。

```json
{
  "id": "uuid",
  "name": "My API Key",
  "description": "用于生产环境的主要 Token",
  "token": "sk-ant-api03_abc123...",
  "key_prefix": "sk-ant-api03",
  "expires_at": "2026-12-31T23:59:59",
  "quota_usd": "100.00",
  "monthly_quota_usd": "50.00",
  "monthly_reset_policy": "reset",
  "used_usd": "0.00",
  "monthly_used_usd": "0.00",
  "daily_used_usd": "0.00",
  "remaining_quota": "100.00",
  "allowed_ips": ["192.168.1.0/24"],
  "is_active": true,
  "is_expired": false,
  "is_quota_exceeded": false,
  "created_at": "2026-01-01T00:00:00",
  "last_used_at": null,
  "token_metadata": {"env": "production", "team": "backend"},
  "team_id": null,
  "team_name": null,
  "allocated_usd": null,
  "allowed_models": []
}
```

#### GET /admin/tokens

列出当前用户的所有 Token。

| 参数 | 位置 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `include_inactive` | query | boolean | `false` | 包含已停用/撤销的 Token |

**响应**：`TokenResponse` 数组。

`TokenResponse` 字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | Token UUID |
| `name` | string | 显示名称 |
| `description` | string \| null | 描述信息 |
| `key_prefix` | string | 固定为 `"sk-ant-api03"` |
| `expires_at` | datetime \| null | 过期时间 |
| `quota_usd` | string \| null | 总配额（美元） |
| `monthly_quota_usd` | string \| null | 月度配额（美元） |
| `daily_limit_usd` | string \| null | 日限额（美元） |
| `monthly_reset_policy` | string \| null | 月度重置策略 |
| `used_usd` | string | 已使用总额 |
| `monthly_used_usd` | string \| null | 当月已用额 |
| `daily_used_usd` | string \| null | 当日已用额 |
| `remaining_quota` | string \| null | 剩余配额 |
| `allowed_ips` | array | IP 白名单 |
| `is_active` | boolean | 是否启用 |
| `is_expired` | boolean | 是否已过期 |
| `is_quota_exceeded` | boolean | 配额是否已用尽 |
| `created_at` | datetime | 创建时间 |
| `last_used_at` | datetime \| null | 最后使用时间 |
| `token_metadata` | object \| null | 自定义元数据 |
| `team_id` | string \| null | 所属团队 ID |
| `team_name` | string \| null | 所属团队名称 |
| `allocated_usd` | string \| null | 团队内分配额度 |
| `allowed_models` | array | 允许使用的模型列表 |

#### GET /admin/tokens/{token_id}

按 UUID 获取 Token 详情。

#### PUT /admin/tokens/{token_id}

更新 Token 设置。

**请求体**（所有字段可选）：

```json
{
  "name": "Renamed Key",
  "description": "更新后的描述",
  "expires_at": "2027-06-30T00:00:00",
  "quota_usd": 200.00,
  "monthly_quota_usd": 80.00,
  "monthly_reset_policy": "rollover",
  "allowed_ips": ["10.0.0.0/8"],
  "is_active": true,
  "token_metadata": {"env": "staging"}
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | Token 显示名称 |
| `description` | string | Token 描述信息 |
| `expires_at` | datetime | 过期时间 |
| `quota_usd` | decimal | 总使用配额（美元） |
| `monthly_quota_usd` | decimal | 每月使用配额（美元） |
| `monthly_reset_policy` | string | 月度配额重置策略：`"reset"` 或 `"rollover"` |
| `allowed_ips` | array | IP 白名单（CIDR） |
| `is_active` | boolean | 是否启用 |
| `token_metadata` | object | 自定义元数据（键值对） |

#### DELETE /admin/tokens/{token_id}

永久删除 Token。返回 204 No Content。

#### POST /admin/tokens/{token_id}/revoke

停用 Token（可通过 PUT 重新激活）。

**响应**：更新后的 `TokenResponse`，`is_active: false`。

#### GET /admin/tokens/{token_id}/plain

获取解密后的明文 Token 值。

**响应**：`{ "token": "sk-ant-api03_..." }`

### 2.3 模型管理

#### GET /admin/models/aws-available

列出代理在当前部署区域实际可调用的模型。响应基于 **inference profile 缓存**（`_ProfileCache`）构建，该缓存在启动时填充，并在每天 UTC 03:00 通过 AWS API 刷新。

列表包括：
- **Inference profiles** — 部署区域可用的推理配置（如 `us.anthropic.claude-sonnet-4-6`、`global.anthropic.claude-sonnet-4-5-20250929-v1:0`）
- **Foundation models** — 仅在 fallback 区域可用的基础模型（如 `zai.glm-5`、`deepseek.v3.2`）— 标记为 `is_fallback: true`
- **Gemini 模型**（如果配置了 `GEMINI_API_KEY`）— 动态追加

仅显示从部署区域实际可调用的模型。例如，如果部署在 `us-west-1`，而 `global.anthropic.claude-sonnet-4-20250514-v1:0` 在该区域不可用，则不会出现在列表中。

结果在内存中缓存 12 小时。

**响应**：

```json
{
  "models": [
    {
      "model_id": "us.anthropic.claude-sonnet-4-6",
      "model_name": "anthropic.claude-sonnet-4-6",
      "friendly_name": "anthropic.claude-sonnet-4-6",
      "provider": "bedrock-converse",
      "is_cross_region": true,
      "cross_region_type": "us",
      "streaming_supported": true,
      "is_fallback": false
    },
    {
      "model_id": "zai.glm-5",
      "model_name": "zai.glm-5",
      "friendly_name": "zai.glm-5",
      "provider": "bedrock-converse",
      "is_cross_region": false,
      "cross_region_type": null,
      "streaming_supported": true,
      "is_fallback": true
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

#### GET /admin/audit-logs/activity

所有管理员可见的活动动态。仅展示管理操作（Token/团队/模型/管理员的增删改），显示最近 N 天的记录。非 super_admin 用户无法看到 super_admin 的操作。

| 参数 | 位置 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `page` | query | integer | `1` | 页码（从 1 开始） |
| `page_size` | query | integer | `50` | 每页条数（最大 100） |
| `days` | query | integer | `7` | 回溯天数（1-30 天） |

**响应**：

```json
{
  "items": [
    {
      "id": "uuid",
      "user_id": "uuid",
      "user_email": "admin@example.com",
      "action": "token_created",
      "resource_type": "token",
      "resource_id": "uuid",
      "details": "{\"name\": \"New Token\"}",
      "created_at": "2026-01-15T10:30:00"
    }
  ],
  "total": 25,
  "page": 1,
  "page_size": 50,
  "total_pages": 1
}
```

### 2.6 管理员用户管理

仅 super_admin 可用。管理管理员用户账户。

#### GET /admin/users

列出所有活跃的管理员用户（super_admin 和 admin 角色）。

**响应**：`AdminUserResponse` 数组：

```json
[
  {
    "id": "uuid",
    "email": "admin@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "role": "admin",
    "permissions": {
      "manage_api_keys": "all", // pragma: allowlist secret
      "manage_teams": "all",
      "manage_models": "all",
      "view_usage": true,
      "view_monitor": true
    },
    "is_active": true,
    "created_at": "2026-01-01T00:00:00",
    "last_login_at": "2026-01-15T10:30:00"
  }
]
```

#### POST /admin/users

邀请新管理员。在 Cognito 中创建用户（设置临时密码），同时创建本地用户记录。

**请求体**：

```json
{
  "email": "newadmin@example.com",
  "username": "newadmin",
  "temp_password": "TempPass123!", // pragma: allowlist secret
  "role": "admin",
  "permissions": {
    "manage_api_keys": "all", // pragma: allowlist secret
    "manage_teams": ["team-uuid-1"],
    "manage_models": true,
    "view_usage": true,
    "view_monitor": true
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `email` | string | 是 | 管理员邮箱 |
| `username` | string | 是 | Cognito 登录用户名 |
| `temp_password` | string | 是 | 临时密码（首次登录必须修改） |
| `role` | string | 否 | `"super_admin"` 或 `"admin"`（默认: `"admin"`） |
| `permissions` | object | 否 | 权限范围（仅 `admin` 角色需要） |

**响应** (201)：`AdminUserResponse`

#### PUT /admin/users/{user_id}

更新管理员用户的角色或权限。

**请求体**（所有字段可选）：

```json
{
  "role": "admin",
  "permissions": { "manage_api_keys": "all", "view_usage": true }, // pragma: allowlist secret
  "is_active": true
}
```

**响应**：更新后的 `AdminUserResponse`。

#### DELETE /admin/users/{user_id}

停用管理员用户。不能停用自己。返回 204 No Content。

#### GET /admin/users/resources

列出所有可分配的资源（Token、团队、模型），供权限编辑器 UI 使用。

**响应**：

```json
{
  "api_keys": [{ "id": "uuid", "name": "Token Name" }],
  "teams": [{ "id": "uuid", "name": "Team Name" }],
  "models": [{ "id": "model-id", "name": "model-id" }]
}
```

### 2.7 团队管理

管理团队及其成员。需要 `manage_teams` 权限。

#### POST /admin/teams

创建团队。

**请求体**：

```json
{
  "name": "AI 研发团队",
  "monthly_budget_usd": 500.00,
  "monthly_reset_policy": "reset",
  "daily_limit_enabled": true
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 团队名称 |
| `monthly_budget_usd` | decimal | 是 | 月度预算（美元） |
| `monthly_reset_policy` | string | 否 | 重置策略：`"reset"`（默认）或 `"rollover"` |
| `daily_limit_enabled` | boolean | 否 | 是否启用日限额（默认: `true`） |

**响应** (201)：`TeamListItem`

```json
{
  "id": "uuid",
  "name": "AI 研发团队",
  "monthly_budget_usd": "500.00",
  "monthly_reset_policy": "reset",
  "daily_limit_enabled": true,
  "member_count": 0,
  "total_used_usd": "0.00",
  "unallocated_pool_usd": "500.00",
  "created_at": "2026-05-12T10:00:00"
}
```

#### GET /admin/teams

列出团队。

**响应**：`TeamListItem` 数组。

```json
[
  {
    "id": "uuid",
    "name": "AI 研发团队",
    "monthly_budget_usd": "500.00",
    "monthly_reset_policy": "reset",
    "daily_limit_enabled": true,
    "member_count": 5,
    "total_used_usd": "120.50",
    "unallocated_pool_usd": "79.50",
    "created_at": "2026-01-01T00:00:00"
  }
]
```

#### GET /admin/teams/{team_id}

获取团队仪表板（详细信息及成员列表）。

**响应**：`TeamDashboardResponse`

```json
{
  "id": "uuid",
  "name": "AI 研发团队",
  "monthly_budget_usd": "500.00",
  "monthly_reset_policy": "reset",
  "daily_limit_enabled": true,
  "total_allocated_usd": "420.50",
  "total_used_usd": "120.50",
  "unallocated_pool_usd": "79.50",
  "members": [
    {
      "token_id": "uuid",
      "token_name": "张三的 Token",
      "allocated_usd": "100.00",
      "used_usd": "35.20",
      "remaining_usd": "64.80",
      "daily_limit_usd": "16.67",
      "daily_used_usd": "5.30",
      "is_active": true,
      "last_used_at": "2026-05-12T09:30:00"
    }
  ]
}
```

#### PUT /admin/teams/{team_id}

更新团队设置。

**请求体**（所有字段可选）：

```json
{
  "name": "AI 研发团队（更名）",
  "monthly_budget_usd": 800.00,
  "monthly_reset_policy": "rollover",
  "daily_limit_enabled": false
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 团队名称 |
| `monthly_budget_usd` | decimal | 月度预算（美元） |
| `monthly_reset_policy` | string | 重置策略：`"reset"` 或 `"rollover"` |
| `daily_limit_enabled` | boolean | 是否启用日限额 |

**响应**：更新后的 `TeamListItem`。

#### DELETE /admin/teams/{team_id}

删除团队。返回 204 No Content。

#### POST /admin/teams/{team_id}/members

为团队添加成员（将已有 Token 加入团队）。

**请求体**：

```json
{
  "token_id": "uuid",
  "allocated_usd": 100.00
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `token_id` | string | 是 | 要添加的 Token UUID |
| `allocated_usd` | decimal | 是 | 分配额度（美元） |

**响应**：`TeamMemberSimpleResponse`

```json
{
  "token_id": "uuid",
  "token_name": "张三的 Token",
  "allocated_usd": "100.00"
}
```

#### DELETE /admin/teams/{team_id}/members/{token_id}

从团队中移除成员。返回 204 No Content。

#### PUT /admin/teams/{team_id}/members/{token_id}

调整成员的分配额度。

**请求体**：

```json
{
  "allocated_usd": 150.00
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `allocated_usd` | decimal | 是 | 新的分配额度（美元） |

**响应**：`TeamMemberSimpleResponse`

```json
{
  "token_id": "uuid",
  "token_name": "张三的 Token",
  "allocated_usd": "150.00"
}
```

#### POST /admin/teams/{team_id}/transfer

在团队成员间转移分配额度。

**请求体**：

```json
{
  "from_token_id": "uuid-source",
  "to_token_id": "uuid-target",
  "amount": 25.00
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `from_token_id` | string | 是 | 转出方 Token UUID |
| `to_token_id` | string | 是 | 转入方 Token UUID |
| `amount` | decimal | 是 | 转移金额（美元） |

**响应**：

```json
{
  "message": "Transfer successful"
}
```

#### POST /admin/teams/{team_id}/members/batch

批量创建团队成员。自动为每个成员生成新的 Token 并加入团队。

**请求体**：

```json
{
  "names": "张三,李四,王五",
  "per_member_allocation": 80.00,
  "expires_at": "2026-12-31T23:59:59",
  "quota_usd": 200.00,
  "allowed_ips": ["10.0.0.0/8"],
  "token_metadata": {"department": "research"},
  "model_names": ["claude-sonnet-4-5", "claude-haiku-3-5"]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `names` | string | 是 | 成员名称列表（逗号分隔） |
| `per_member_allocation` | decimal | 是 | 每个成员的分配额度（美元） |
| `expires_at` | datetime | 否 | Token 过期时间 |
| `quota_usd` | decimal | 否 | 每个 Token 的总配额 |
| `allowed_ips` | array | 否 | IP 白名单 |
| `token_metadata` | object | 否 | 自定义元数据 |
| `model_names` | array | 否 | 允许使用的模型名称列表 |

**响应**：`BatchCreateMembersResponse`

```json
{
  "created": [
    {
      "token_id": "uuid-1",
      "token_name": "张三",
      "token": "sk-ant-api03_abc123...",
      "allocated_usd": "80.00"
    },
    {
      "token_id": "uuid-2",
      "token_name": "李四",
      "token": "sk-ant-api03_def456...",
      "allocated_usd": "80.00"
    },
    {
      "token_id": "uuid-3",
      "token_name": "王五",
      "token": "sk-ant-api03_ghi789...",
      "allocated_usd": "80.00"
    }
  ],
  "total": 3
}
```

> 注意：响应中的 `token` 字段包含明文 Token 值，这是唯一一次返回。请妥善保存。

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

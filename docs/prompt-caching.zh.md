# 提示缓存（Prompt Caching）

Kolya BR Proxy 支持对 AWS Bedrock 上的 Anthropic 模型自动注入提示缓存断点。该功能通过缓存稳定的前缀（系统提示词、工具定义、对话历史）来降低成本和延迟。

## 工作原理

启用后，代理在将请求发送到 Bedrock 之前，自动在 Anthropic Messages API 请求体中注入 `cache_control` 断点，最多注入 3 个：

| 断点 | 目标 | 条件 |
|------|------|------|
| 1 | System prompt（最后一个 block） | 总字符数 >= 4096 |
| 2 | 最后一个 tool 定义 | 所有 tool 总字符数 >= 4096 |
| 3 | 倒数第二条 user 消息 | 总字符数 >= 4096 |

选择倒数第二条 user 消息（而非最后一条），因为最后一条每次请求都会变化，无法命中缓存。

## 控制优先级

```
请求级参数  >  服务端默认值（环境变量）
```

| 客户端传参 | 服务端默认 | 最终行为 |
|-----------|-----------|---------|
| `bedrock_auto_cache: true` | 任意 | 启用注入 |
| `bedrock_auto_cache: false` | 任意 | 禁用注入 |
| 未传 | `true` | 启用注入 |
| 未传 | `false` | 禁用注入 |

## 服务端配置

环境变量：

```bash
KBR_PROMPT_CACHE_AUTO_INJECT=true   # 默认值: true
```

默认为 `true`，因为主要客户端（Claude Code、OpenCode）使用标准 OpenAI SDK，无法发送自定义参数。这些客户端的典型场景是多轮 Agent 循环（system prompt + tools 固定），是缓存的理想场景。

## 按请求控制

### Body 方式（OpenAI SDK `extra_body`）

```python
# 多轮 Agent 循环 — 缓存收益高
response = client.chat.completions.create(
    model="us.anthropic.claude-sonnet-4-20250514-v1:0",
    messages=[...],
    tools=[...],
    max_tokens=4000,
    extra_body={"bedrock_auto_cache": True}
)
```

### Header 方式

```bash
curl -H "X-Bedrock-Auto-Cache: true" \
     -H "Authorization: Bearer kbr_xxx" \
     -d '{"model":"us.anthropic.claude-sonnet-4-20250514-v1:0","messages":[...]}' \
     https://api.example.com/v1/chat/completions
```

## 何时应禁用缓存

对于**一次性调用**（每次请求的 system prompt 或输入都不同），应禁用缓存。这类场景下缓存会产生 25% 的写入溢价，但命中率为 0% — 净成本反而增加。

典型的一次性场景：

- 动态输入的单次翻译调用
- 系统提示词包含时间戳或每次请求不同的变量
- 批处理任务，每次请求的上下文都不同

### 通过 Body 禁用

```python
# 一次性翻译 — 禁用以避免 25% 写入溢价
response = client.chat.completions.create(
    model="us.anthropic.claude-sonnet-4-20250514-v1:0",
    messages=[{"role": "user", "content": f"翻译: {dynamic_text}"}],
    max_tokens=2000,
    extra_body={"bedrock_auto_cache": False}
)
```

### 通过 Header 禁用

```bash
curl -H "X-Bedrock-Auto-Cache: false" ...
```

### 全局禁用

如果大部分工作负载是一次性调用，可将服务端默认值设为 `false`，让多轮客户端主动 opt-in：

```bash
KBR_PROMPT_CACHE_AUTO_INJECT=false
```

## 成本模型

| Token 类型 | 计费 |
|-----------|------|
| `cache_creation_input_tokens` | 基础输入价格的 1.25 倍（25% 写入溢价） |
| `cache_read_input_tokens` | 基础输入价格的 0.1 倍（90% 折扣） |
| `input_tokens` | 基础输入价格（未缓存部分） |

缓存在约 2 次相同前缀的请求后即可回本。对于 10+ 轮的 Agent 循环，节省非常可观。

## 通过日志验证缓存行为

代理在缓存指标非零时会输出到日志。

**首次请求（缓存写入）：**

```
INFO  Auto-injected prompt cache breakpoints: ['system', 'tools[-1]']
INFO  Bedrock invocation successful: model=us.anthropic.claude-sonnet-4-20250514-v1:0, api=invoke_model, attempt=1, duration=7.7s, input=7, output=152, cache_write=2359
INFO  Chat completion successful: request_id=chatcmpl-xxx, duration=7.7s, prompt=7, completion=152, cache_write=2359
```

**第二次相同请求（缓存命中）：**

```
INFO  Auto-injected prompt cache breakpoints: ['system', 'tools[-1]']
INFO  Bedrock invocation successful: model=us.anthropic.claude-sonnet-4-20250514-v1:0, api=invoke_model, attempt=1, duration=8.1s, input=7, output=178, cache_read=2359
INFO  Chat completion successful: request_id=chatcmpl-xxx, duration=8.1s, prompt=7, completion=178, cache_read=2359
```

**流式请求，部分命中（Agent 循环，新 user 消息）：**

```
INFO  Streaming chat completion successful: request_id=chatcmpl-xxx, duration=5.2s, prompt=105, completion=843, cache_write=1280, cache_read=3240
```

**缓存已禁用（日志中无缓存字段）：**

```
INFO  Bedrock invocation successful: model=us.anthropic.claude-sonnet-4-20250514-v1:0, api=invoke_model, attempt=1, duration=4.3s, input=1072, output=200
```

日志判读：

| 日志模式 | 含义 |
|---------|------|
| `cache_creation > 0`，`cache_read = 0` | 缓存已写入（首次请求） |
| `cache_creation = 0`，`cache_read > 0` | 缓存命中 |
| `cache_creation > 0`，`cache_read > 0` | 部分命中（稳定前缀已缓存，新内容被写入） |
| 两个字段都不出现 | 缓存未激活 |

## 测试与验证指南

本节提供端到端验证 prompt caching 是否正常工作的完整步骤，基于实际调试经验总结。

### 前置条件

- 本地 Backend 运行中（可选 `KBR_DEBUG=true` 开启 debug 级别日志）
- 一个有效的 API Token（`kbr_xxx`）
- 已安装 `curl` 和 `jq`

### 第 1 步：准备测试 Payload

缓存静默失败最常见的原因是：**被缓存的内容未达到 Bedrock 的最低 token 阈值**。

**Bedrock 各模型的缓存最低 token 数：**

| 模型 | 最低 Token 数 |
|------|-------------|
| Claude Sonnet 4 / 3.5 Sonnet | 1,024 |
| Claude Haiku 3.5 | 2,048 |
| Claude Opus 4.5 / Haiku 4.5 | 4,096 |

> **踩坑点**：代码中使用字符数做预检（`MIN_CACHEABLE_CHARS = 4096` 字符 ≈ 1024 tokens），但**实际缓存**由 Bedrock 按 token 数判定。一个 4096+ 字符的 system prompt 可能实际不足 1024 tokens，此时 Bedrock 不会报错，只会返回 `cache_creation_input_tokens=0` — 静默失败。

创建测试文件 `test-cache.json`，system prompt **远超**最低要求（建议 2000+ tokens，约 8000+ 字符）：

```bash
python3 -c "
import json

rules = []
for i in range(1, 21):
    rules.append(f'Rule {i}: This is an important architectural guideline number {i}. '
        'All implementations must follow strict coding standards including proper error handling, '
        'comprehensive input validation, secure authentication mechanisms, thorough logging, '
        'performance optimization strategies, database query optimization with proper indexing, '
        'API versioning and backward compatibility, comprehensive test coverage requirements, '
        'deployment automation with CI/CD pipelines, monitoring and alerting configuration, '
        'incident response procedures, capacity planning and auto-scaling policies, '
        'data encryption at rest and in transit, access control and authorization frameworks, '
        'code review processes and quality gates, documentation standards and maintenance.')

data = {
    'model': 'global.anthropic.claude-sonnet-4-6',
    'messages': [
        {'role': 'system', 'content': 'You are an expert architect. ' + ' '.join(rules)},
        {'role': 'user', 'content': 'Hello'}
    ]
}

with open('test-cache.json', 'w') as f:
    json.dump(data, f, ensure_ascii=False)

content = data['messages'][0]['content']
print(f'System prompt: {len(content)} chars (~{len(content)//4} tokens)')
"
```

预期输出：`System prompt: ~15000 chars (~3700 tokens)` — 远超 1024 最低要求。

### 第 2 步：首次请求（缓存写入）

```bash
curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer kbr_xxx" \
  -H "Content-Type: application/json" \
  -d @test-cache.json | jq '{input: .usage.prompt_tokens, output: .usage.completion_tokens, cache_write: .usage.prompt_tokens_details.cached_tokens}'
```

**预期日志：**

```
INFO  Auto-injected prompt cache breakpoints: ['system']
INFO  Bedrock invocation successful: model=global.anthropic.claude-sonnet-4-6, api=invoke_model, attempt=1, duration=7.7s, input=7, output=152, cache_write=2359
INFO  Chat completion successful: request_id=chatcmpl-xxx, duration=7.7s, prompt=7, completion=152, cache_write=2359
```

关键标志：
- `Auto-injected prompt cache breakpoints: ['system']` — 注入成功
- `cache_write=2359` — Bedrock 接受并缓存了 system prompt（2359 tokens）
- `input=7` — 只有 user message 计为普通 input

### 第 3 步：第二次请求（缓存命中）

在 **5 分钟内** 发送完全相同的请求：

```bash
curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer kbr_xxx" \
  -H "Content-Type: application/json" \
  -d @test-cache.json | jq '{input: .usage.prompt_tokens, output: .usage.completion_tokens, cache_read: .usage.prompt_tokens_details.cached_tokens}'
```

**预期日志：**

```
INFO  Auto-injected prompt cache breakpoints: ['system']
INFO  Bedrock invocation successful: model=global.anthropic.claude-sonnet-4-6, api=invoke_model, attempt=1, duration=8.1s, input=7, output=178, cache_read=2359
INFO  Chat completion successful: request_id=chatcmpl-xxx, duration=8.1s, prompt=7, completion=178, cache_read=2359
```

关键标志：
- `cache_read=2359` — 缓存命中！相同的 2359 tokens 从缓存读取
- `cache_write` 不出现 — 无需重新写入

### 第 4 步：验证流式模式

```bash
curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer kbr_xxx" \
  -H "Content-Type: application/json" \
  -d "$(jq '. + {stream: true}' test-cache.json)"
```

**预期日志：**

```
INFO  Streaming chat completion successful: request_id=chatcmpl-xxx, duration=5.2s, prompt=7, completion=200, cache_read=2359
```

### 故障排查

| 现象 | 原因 | 解决方法 |
|------|------|---------|
| 无 `Auto-injected` 日志 | `should_inject=false` — 自动缓存被禁用 | 检查 `KBR_PROMPT_CACHE_AUTO_INJECT` 环境变量，或请求中传 `bedrock_auto_cache: true` |
| 出现 `Auto-injected` 但 `cache_write=0` | System prompt 低于 Bedrock 的 **token** 最低要求（Sonnet 需 1024） | 加长 system prompt（8000+ 字符以确保超过 1024 tokens） |
| 首次 `cache_write` 正常但第二次无 `cache_read` | 缓存 TTL 过期（默认 5 分钟）或两次请求的 system prompt 不完全一致 | 5 分钟内发送第二次请求；确保 system prompt 完全相同 |
| 有 `cache_write` 但始终无 `cache_read` | 模型或区域可能不支持缓存 | 查阅 AWS 文档确认模型和区域支持 prompt caching |
| 日志中既无 `cache_write` 也无 `cache_read` | 客户端已手动设置 `cache_control`，自动注入被跳过 | 检查请求体中是否设置了 `bedrock_prompt_caching` |

### Debug 日志

如需更深入排查，将日志级别设为 DEBUG（修改 `backend/main.py` 中 `logging.basicConfig(level=logging.DEBUG)`），可以看到额外的诊断日志：

```
DEBUG  Prompt cache check: auto_cache=None, server_default=True, should_inject=True, has_cache_control=False, system_len=14969
```

该日志显示完整的决策链路：请求级覆盖 → 服务端默认值 → 最终决策 → 字符数。

## 与手动缓存配置的交互

如果客户端已通过 `bedrock_prompt_caching`（透传）设置了 `cache_control` 标记，自动注入会被完全跳过，避免冲突 — 此时由客户端自行管理缓存。

## 适用范围

自动注入仅对 Anthropic 模型（通过 `invoke_model` 路由）生效。使用 Converse API 的非 Anthropic 模型不受影响。

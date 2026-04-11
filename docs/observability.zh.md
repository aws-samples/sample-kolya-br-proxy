# 可观测性

本文档介绍系统的结构化日志、CloudWatch EMF 指标和 AWS X-Ray 链路追踪能力。

## 目录

- [概述](#概述)
- [配置项](#配置项)
- [结构化日志](#结构化日志)
- [CloudWatch EMF 指标](#cloudwatch-emf-指标)
- [AWS X-Ray 链路追踪](#aws-x-ray-链路追踪)
- [日志-追踪关联](#日志-追踪关联)
- [部署配置](#部署配置)
- [常见问题排查](#常见问题排查)

---

## 概述

所有可观测性功能**默认关闭**，通过环境变量控制。本地开发零开销，生产环境按需开启。

```
本地开发:   无需设置 → 文本日志，无指标，无追踪
预发布:     KBR_LOG_FORMAT=json, KBR_LOG_LEVEL=DEBUG
生产环境:   KBR_LOG_FORMAT=json, KBR_ENABLE_METRICS=true, KBR_OTEL_EXPORTER=xray
```

### 架构

```mermaid
graph TD
    App[FastAPI App] --> Logs[结构化日志<br/>JSON / text]
    App --> EMF[EMF 指标]
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

## 配置项

所有设置使用 `KBR_` 前缀，定义在 `backend/app/core/config.py`：

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `KBR_LOG_LEVEL` | `INFO` | 日志级别：`DEBUG`、`INFO`、`WARNING`、`ERROR` |
| `KBR_LOG_FORMAT` | `text` | 输出格式：`text`（人类可读）或 `json`（CloudWatch） |
| `KBR_ENABLE_METRICS` | `false` | 启用 CloudWatch Embedded Metrics Format 指标 |
| `KBR_OTEL_EXPORTER` | `""`（空） | OpenTelemetry 导出器：`""`（禁用）、`xray`、`otlp` |
| `KBR_OTEL_ENDPOINT` | `""`（空） | OTLP HTTP 端点覆盖（xray 模式）。空 = 自动检测 `http://$NODE_IP:4316/v1/traces` |

**修改任何设置需要重启服务**（Kubernetes 中通过 Pod 滚动更新）。

### 相关文件

| 文件 | 用途 |
|------|------|
| `backend/app/core/config.py` | 设置定义与校验 |
| `backend/app/core/json_formatter.py` | JSON 格式化器 + `configure_logging()` |
| `backend/app/core/metrics.py` | EMF 指标发射函数 |
| `backend/app/core/tracing.py` | OpenTelemetry 初始化 |
| `backend/app/core/log_context.py` | 请求级上下文注入（token_name、trace_id） |
| `backend/app/middleware/observability.py` | ASGI 中间件，采集 HTTP 级别指标 |

---

## 结构化日志

### 文本格式（默认）

```
2026-04-11 12:00:00 - app.services.bedrock - INFO - [alice-key] Bedrock invocation successful...
```

### JSON 格式（`KBR_LOG_FORMAT=json`）

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

主要特性：
- **自动采集 extra 字段**：所有 `logger.info("msg", extra={...})` 中的字段自动包含，无需改动代码
- **按 API Key 区分**：`token_name` 和 `token_id` 通过 `contextvars` 注入每条日志
- **追踪关联**：`trace_id` 和 `span_id` 来自 OpenTelemetry（启用追踪时）
- **健康检查过滤**：`/health/*` 访问日志自动过滤，减少噪音

### CloudWatch Logs Insights 查询示例

```sql
-- 查找特定 API Key 的所有日志
fields @timestamp, level, message, model, duration
| filter token_name = "alice-key"
| sort @timestamp desc

-- 慢请求（> 5 秒）
fields @timestamp, token_name, model, duration
| filter duration > 5
| sort duration desc

-- 错误日志及堆栈
fields @timestamp, logger, message, exception
| filter level = "ERROR"
| sort @timestamp desc

-- 根据 X-Ray trace_id 关联日志
fields @timestamp, level, message
| filter trace_id = "1-abc-def0123456789"
| sort @timestamp asc
```

---

## CloudWatch EMF 指标

CloudWatch Embedded Metrics Format 将指标以结构化 JSON 日志行形式输出，CloudWatch 自动提取为自定义指标 — 无需额外 agent 或 sidecar。

### 指标目录

所有指标使用命名空间 `KolyaBRProxy`。

#### 请求指标（每次 API 调用）

| 指标 | 单位 | 维度 | 说明 |
|------|------|------|------|
| `RequestDuration` | Seconds | Endpoint, Model, Streaming | 端到端请求耗时（包含代理开销 + Bedrock 调用） |
| `RequestCount` | Count | Endpoint, Model, Streaming | 请求计数 |
| `TokensInput` | Count | Endpoint, Model, Streaming | 输入 token 数 |
| `TokensOutput` | Count | Endpoint, Model, Streaming | 输出 token 数 |
| `CacheWriteTokens` | Count | Endpoint, Model, Streaming | Prompt Cache 写入 token 数（> 0 时才发射） |
| `CacheReadTokens` | Count | Endpoint, Model, Streaming | Prompt Cache 读取 token 数（> 0 时才发射） |
| `TimeToFirstToken` | Seconds | Endpoint, Model, Streaming | 从请求开始到第一个内容 delta 的时间（仅流式） |

#### Bedrock 调用指标（每次 AWS API 调用）

| 指标 | 单位 | 维度 | 说明 |
|------|------|------|------|
| `BedrockCallDuration` | Seconds | Model, Region, API | Bedrock API 调用本身的耗时 |

**关键关系**：`RequestDuration` 包含 `BedrockCallDuration`，两者之差即为代理开销（认证、格式转换、SSE 封装等）。

```mermaid
gantt
    title 请求耗时分解
    dateFormat X
    axisFormat %s

    section RequestDuration
    认证 + 格式转换            :a1, 0, 50
    BedrockCallDuration      :crit, a2, 50, 900
    SSE 封装 + 响应            :a3, 950, 50
```

#### 流式故障转移指标

| 指标 | 单位 | 维度 | 说明 |
|------|------|------|------|
| `FailoverTriggered` | Count | Level, PrimaryModel | 故障转移事件计数 |
| `StreamFailoverDuration` | Seconds | Level, PrimaryModel | 从首次失败到成功回退（或最终失败）的耗时 |

故障转移级别：
- **L1**：同模型不同区域（对客户端透明）
- **L2**：不同模型（通过 `x-actual-model` SSE 注释通知客户端）

#### HTTP 指标（来自中间件）

| 指标 | 单位 | 维度 | 说明 |
|------|------|------|------|
| `HttpRequestDuration` | Seconds | Method, Path | 所有端点的 HTTP 请求耗时 |
| `HttpRequestCount` | Count | Method, Path | HTTP 请求计数 |

### 埋点位置

| 位置 | 发射的指标 |
|------|-----------|
| `chat.py`（非流式） | RequestDuration、TokensInput/Output、CacheTokens |
| `chat.py`（流式） | RequestDuration、TokensInput/Output、CacheTokens、TTFT |
| `messages.py`（非流式） | RequestDuration、TokensInput/Output、CacheTokens |
| `messages.py`（流式） | RequestDuration、TokensInput/Output、CacheTokens、TTFT |
| `bedrock.py`（_invoke_inner） | BedrockCallDuration |
| `bedrock.py`（_invoke_stream_inner） | BedrockCallDuration |
| `bedrock.py`（invoke_stream 故障转移） | FailoverTriggered、StreamFailoverDuration |
| `observability.py`（中间件） | HttpRequestDuration、HttpRequestCount |

### TTFT（首 Token 响应时间）

在流式生成器中，首个 `content_block_delta` 事件到达时测量：

```python
if ttft is None:
    ttft = time.time() - start_time
```

捕获的是从请求到达到第一个实际内容 token 到达客户端的时间（不包括 `message_start` 和 `content_block_start` 事件）。

---

## AWS X-Ray 链路追踪

### 导出器选项

| `KBR_OTEL_EXPORTER` | 目标 | 使用场景 |
|---------------------|------|---------|
| `""`（空） | 禁用 | 本地开发 |
| `xray` | `http://$NODE_IP:4316`（CloudWatch Agent DaemonSet） | 生产环境，配合 CloudWatch Observability addon |
| `otlp` | `OTEL_EXPORTER_OTLP_ENDPOINT` 环境变量 | 自定义 OTLP 端点（如 Jaeger） |

> **为什么是 4316 而不是标准 4318？** CloudWatch Agent DaemonSet 的 OTLP HTTP 接收器监听 4316 端口。`NODE_IP` 通过 Kubernetes `fieldRef: status.hostIP` 注入，因为在容器网络命名空间中 `localhost` 指向 Pod 自身，无法到达宿主机上的 DaemonSet。

### 健康检查排除

`/health/*` 路径已从追踪中排除（通过 `FastAPIInstrumentor(excluded_urls="health")`），避免高频健康探针产生大量无用 trace。

### 自动埋点禁用

后端 Pod 使用 annotation `instrumentation.opentelemetry.io/inject-python: "false"` 禁用 CloudWatch Observability addon 的 Python 自动注入。原因：addon 的自动注入会修改 Python 启动命令，破坏 `app` 模块路径导致 `ModuleNotFoundError`。后端通过代码内手动初始化 OpenTelemetry（`tracing.py`）来替代。

### 追踪内容

1. **自动埋点**（通过 `FastAPIInstrumentor`）：
   - 所有 FastAPI 路由（`/health/*` 除外）— 每个 HTTP 请求一个根 span
   - 包含 HTTP 方法、路径、状态码、耗时

2. **手动 span**（`bedrock.py`）：
   - `bedrock.invoke` — 非流式 Bedrock API 调用（`_invoke_inner`）
   - `bedrock.invoke_stream` — 流式 Bedrock API 调用（`_invoke_stream_inner` 和 `_try_stream_with_content_timeout`）

Span 属性：

| 属性 | 说明 |
|------|------|
| `bedrock.model` | 用户面模型名称（仅非 failover 路径） |
| `bedrock.model_id` | 解析后的 Bedrock 模型 ID |
| `bedrock.region` | 目标 AWS 区域 |
| `bedrock.api` | 使用的 API：`invoke_model`、`converse`、`invoke_model_stream`、`converse_stream` |
| `bedrock.attempt` | 重试次数（仅非 failover 路径） |
| `bedrock.failover` | `true` 表示走 failover 超时路径（仅 failover 路径） |
| `bedrock.input_tokens` | 输入 token 数（响应后设置，仅非流式） |
| `bedrock.output_tokens` | 输出 token 数（响应后设置，仅非流式） |
| `bedrock.duration_s` | 调用耗时（秒） |

### X-Ray Trace 结构解读

在 X-Ray 控制台的 Trace 详情页，你会看到以下 span：

| Span 名称 | 来源 | 含义 |
|-----------|------|------|
| `POST /v1/messages` 等 | FastAPIInstrumentor | 根 span，覆盖整个 HTTP 请求生命周期 |
| `http receive` | ASGI 层 | 服务端接收请求体。流式请求中此 span 持续到整个响应生成完毕（ASGI 的 receive 循环等待客户端断开），因此占据几乎全部时间 |
| `http send` | ASGI 层 | 服务端向客户端发送数据。每次 SSE chunk 推送产生一个 `http send`（通常 0ms） |
| `bedrock.invoke` | 手动埋点 | 非流式 Bedrock API 调用的耗时 |
| `bedrock.invoke_stream` | 手动埋点 | 流式 Bedrock API 调用的耗时 |

#### 请求流示意

```
用户(浏览器/SDK)        KBP Server                 Bedrock
    │                      │                          │
    │── POST /v1/messages ──▶│                          │
    │                      │  [http receive 开始]      │
    │                      │                          │
    │                      │── invoke_stream ──────────▶│
    │                      │                          │
    │                      │◀── SSE chunk 1 ───────────│
    │◀── [http send] ────────│                          │
    │                      │◀── SSE chunk 2 ───────────│
    │◀── [http send] ────────│                          │
    │                      │◀── SSE chunk N ───────────│
    │◀── [http send] ────────│                          │
    │                      │                          │
    │                      │◀── [stream end] ──────────│
    │◀── [http send: DONE] ──│                          │
    │                      │  [http receive 结束]      │
```

- **`http receive` ≈ `bedrock.invoke_stream`**：时间几乎相同，差值是请求解析 + 格式转换的开销
- **多个 `http send`（0ms）**：每个对应一次 SSE event 推送

#### Trace 示例：流式请求（正常路径）

```
[POST /v1/messages]  ──────────────────────────── 3.5s
  ├─ http receive  ─────────────────────────── 3.4s
  ├─ http send × N                               0ms（每次 SSE chunk）
  └─ bedrock.invoke_stream         ─────────── 3.3s
       bedrock.model_id: anthropic.claude-sonnet-4-20250514-v1:0
       bedrock.region:   us-west-2
       bedrock.api:      invoke_model_stream
```

#### Trace 示例：Failover 超时切换

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

### 本地测试（Jaeger）

```bash
# 启动 Jaeger（OTLP HTTP 端口 4318，UI 端口 16686）
docker run -d --name jaeger \
  -p 4318:4318 \
  -p 16686:16686 \
  jaegertracing/all-in-one:latest

# 启动应用，使用 OTLP 导出器
KBR_OTEL_EXPORTER=otlp \
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
python -m uvicorn main:app
```

打开 `http://localhost:16686` 查看追踪。

---

## 日志-追踪关联

启用追踪后，每条日志自动包含当前 OpenTelemetry span 的 `trace_id` 和 `span_id`。由 `log_context.py` 中的 `RequestContextFilter` 注入。

### 关联流程

1. 请求到达 → FastAPI 自动埋点创建根 span
2. 该请求上下文内的所有日志包含相同的 `trace_id`
3. 在 CloudWatch 中，通过 Logs Insights 按 `trace_id` 过滤
4. 点击跳转到 X-Ray 控制台查看完整调用链瀑布图

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant FastAPI
    participant Bedrock

    Client->>FastAPI: POST /v1/chat/completions
    Note right of FastAPI: 创建根 span<br/>trace_id = 1-abc...

    FastAPI->>FastAPI: 认证通过
    Note right of FastAPI: log: INFO 认证通过<br/>trace_id = 1-abc...

    FastAPI->>Bedrock: bedrock.invoke span
    Bedrock-->>FastAPI: 响应 (1.2s)
    Note right of FastAPI: log: INFO Bedrock 成功<br/>trace_id = 1-abc...

    FastAPI-->>Client: 200 OK
    Note right of FastAPI: log: INFO 200 返回<br/>trace_id = 1-abc...

    Note over FastAPI: CloudWatch Logs Insights:<br/>filter trace_id = "1-abc..."<br/>→ 显示全部 3 条日志

    Note over Bedrock: X-Ray Console:<br/>调用链瀑布图，包含<br/>FastAPI + bedrock.invoke span
```

---

## 部署配置

### Kubernetes ConfigMap

```yaml
# k8s/application/backend-configmap.yaml
KBR_LOG_FORMAT: "json"
KBR_LOG_LEVEL: "INFO"
KBR_ENABLE_METRICS: "true"
KBR_OTEL_EXPORTER: "xray"
```

### CloudWatch Observability Addon

通过 EKS addon `amazon-cloudwatch-observability` 部署 CloudWatch Agent DaemonSet，提供：
- **Fluent Bit**：容器日志采集 → CloudWatch Logs
- **CloudWatch Agent**：Container Insights 指标 + OTLP HTTP 接收器（端口 4316）→ X-Ray
- **自动 Python 注入**（已禁用）：通过 annotation `inject-python: "false"` 关闭

```hcl
# iac/modules/eks-karpenter/eks.tf
amazon-cloudwatch-observability = {
  pod_identity_association = [{
    role_arn        = aws_iam_role.cloudwatch_agent[0].arn
    service_account = "cloudwatch-agent"
  }]
}
```

### 后端 Pod 关键配置

```yaml
# k8s/application/backend-deployment.yaml.template
metadata:
  annotations:
    # 禁用 addon 的 Python 自动注入，避免破坏模块路径
    instrumentation.opentelemetry.io/inject-python: "false"
env:
  # CloudWatch Agent DaemonSet 运行在宿主机上，
  # 容器内 localhost 无法访问，需要宿主机 IP
  - name: NODE_IP
    valueFrom:
      fieldRef:
        fieldPath: status.hostIP
```

### 所需 IAM 权限

CloudWatch Agent 的 ServiceAccount 通过 Pod Identity 关联 IAM 角色，需要：
- `CloudWatchAgentServerPolicy` — 日志、指标、Container Insights
- `AWSXrayWriteOnlyAccess` — X-Ray trace 导出

后端 Pod 本身**不需要**额外的 X-Ray 权限，因为 trace 通过 CloudWatch Agent DaemonSet 中转。

### 健康检查端点

`GET /health/metrics` 返回当前可观测性配置：

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

## 常见问题排查

### 指标未出现在 CloudWatch 中

1. 确认 `KBR_ENABLE_METRICS=true` 已设置
2. 检查 `GET /health/metrics` — `metrics_enabled` 应为 `true`
3. 确保 EMF 日志组 `/kbp/backend/metrics` 存在或自动创建
4. 检查 Pod IAM 角色有 `cloudwatch:PutMetricData` 权限

### 追踪未出现在 X-Ray 中

1. 确认 `KBR_OTEL_EXPORTER=xray` 已设置
2. CloudWatch Agent DaemonSet 必须运行正常：`kubectl get ds -n amazon-cloudwatch`
3. 确认 `NODE_IP` 环境变量已注入（`kubectl exec <pod> -- env | grep NODE_IP`）
4. 检查 Pod 能访问 `http://$NODE_IP:4316`
5. 确认 CloudWatch Agent IAM 角色有 `AWSXrayWriteOnlyAccess` 策略
6. 检查 CloudWatch Agent 日志：`kubectl logs -n amazon-cloudwatch -l app.kubernetes.io/name=cloudwatch-agent`
7. `/health/*` 路径不会出现在追踪中（已排除）

### JSON 日志没有 extra 字段

- extra 字段必须通过 `logger.info("msg", extra={"key": value})` 传入
- 不可序列化的值会自动转为字符串
- `_BUILTIN_ATTRS` 中的字段（Python LogRecord 内部属性）按设计排除

### 日志级别不生效

- `KBR_LOG_LEVEL` 需要重启 — 仅在启动时由 `configure_logging()` 读取一次
- 有效值：`DEBUG`、`INFO`、`WARNING`、`ERROR`（不区分大小写）
- 第三方库（uvicorn、sqlalchemy）遵循 root logger 的级别设置

# 性能与并发配置

本文档详细说明项目在高并发场景下的优化措施和超时配置。

## 目录

- [高并发处理策略](#高并发处理策略)
- [超时配置详解](#超时配置详解)
- [并发能力评估](#并发能力评估)
- [性能优化建议](#性能优化建议)

---

## 高并发处理策略

### 1. 数据库连接池管理

#### 配置位置
- `backend/app/core/database.py`
- `backend/app/core/config.py`

#### 配置参数

```python
DATABASE_POOL_SIZE = 10        # 连接池大小
DATABASE_MAX_OVERFLOW = 20     # 最大溢出连接数
```

**实际可用连接数 = 10 + 20 = 30 个并发数据库连接**

#### 工作原理

```
请求 1-10  → 使用连接池中的常驻连接（快速）
请求 11-30 → 创建临时溢出连接（稍慢）
请求 31+   → 等待连接释放（排队）
```

#### 优势

- ✅ 避免频繁创建/销毁连接（性能开销大）
- ✅ 限制最大连接数，保护数据库不被压垮
- ✅ 自动连接回收和健康检查

#### 环境差异

```python
if settings.DEBUG:
    # 开发环境：不使用连接池（NullPool）
    # 每次请求创建新连接，便于调试
    engine = create_async_engine(..., poolclass=NullPool)
else:
    # 生产环境：使用连接池
    engine = create_async_engine(..., pool_size=10, max_overflow=20)
```

#### 会话管理

```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()  # 异常时回滚
            raise
        finally:
            await session.close()     # 确保连接释放
```

---

### 2. AWS Bedrock 并发限制（信号量）

#### 配置位置
- `backend/app/services/bedrock.py`
- `backend/app/core/config.py`

#### 配置参数

```python
BEDROCK_MAX_CONCURRENT_REQUESTS = 50  # 最大并发请求数
```

#### 实现方式

```python
# 使用 asyncio.Semaphore 控制并发
self._semaphore = asyncio.Semaphore(50)

async def invoke(self, model_name: str, request: BedrockRequest):
    async with self._semaphore:  # 获取信号量许可
        return await self._invoke_inner(model_name, request)
```

#### 工作原理

```
并发请求 1-50  → 立即执行
并发请求 51+   → 等待前面的请求完成
```

#### 为什么需要信号量？

1. **AWS Bedrock 有配额限制**
   - 每个账户/区域有并发请求限制
   - 超过限制会被 throttle（429 错误）

2. **保护下游服务**
   - 避免突发流量压垮 Bedrock
   - 提供平滑的背压（backpressure）

3. **流式响应特殊处理**

```python
async def invoke_stream(self, model_name: str, request: BedrockRequest):
    async with self._semaphore:  # 整个流式响应期间持有信号量
        async for event in self._invoke_stream_inner(model_name, request):
            yield event
    # 流结束后才释放信号量
```

---

### 3. Uvicorn 服务器并发控制

#### 配置位置
- `backend/main.py`
- `backend/app/core/config.py`

#### 配置参数

```python
UVICORN_TIMEOUT_KEEP_ALIVE = 120      # 保持连接 120 秒
UVICORN_LIMIT_CONCURRENCY = 100       # 每个 worker 最多 100 个并发连接
UVICORN_LIMIT_MAX_REQUESTS = 10000    # 处理 10000 个请求后重启 worker
```

#### 启动配置

```python
uvicorn.run(
    "main:app",
    host="0.0.0.0",
    port=settings.PORT,
    timeout_keep_alive=120,
    limit_concurrency=100,
    limit_max_requests=10000,
)
```

#### 参数说明

| 参数 | 作用 | 为什么需要 |
|------|------|-----------|
| `timeout_keep_alive=120` | 保持连接 2 分钟 | 支持 AI 流式响应（可能很长） |
| `limit_concurrency=100` | 限制并发连接数 | 防止单个 worker 过载 |
| `limit_max_requests=10000` | 定期重启 worker | 防止内存泄漏累积 |

---

### 4. Kubernetes 水平扩展（HPA）

#### 配置位置
- `k8s/application/hpa-backend.yaml`
- `k8s/application/backend-deployment.yaml`

#### HPA 配置

```yaml
# 后端自动扩展配置
minReplicas: 1      # 最少 1 个 Pod
maxReplicas: 10     # 最多 10 个 Pod

metrics:
- type: Resource
  resource:
    name: cpu
    target:
      type: Utilization
      averageUtilization: 70  # CPU 超过 70% 时扩容
```

#### 扩容策略

```
正常流量：1-2 个 Pod
中等流量：3-5 个 Pod（CPU > 70%）
高峰流量：6-10 个 Pod（持续高负载）
流量下降：自动缩容回 1 个 Pod
```

#### Pod 资源配置

```yaml
resources:
  requests:
    cpu: 100m      # 保证分配 0.1 核
    memory: 256Mi  # 保证分配 256MB
  limits:
    cpu: 500m      # 最多使用 0.5 核
    memory: 512Mi  # 最多使用 512MB
```

---

### 5. 异步数据库驱动

#### 配置

```python
# 使用 asyncpg（异步 PostgreSQL 驱动）
DATABASE_URL = "postgresql+asyncpg://user:password@host:5432/db"  # pragma: allowlist secret
```

#### 优势

- ✅ 支持真正的异步 I/O
- ✅ 不阻塞事件循环
- ✅ 更高的并发处理能力

#### 使用示例

```python
# 异步执行查询
async with async_session_maker() as session:
    result = await session.execute(query)  # 异步执行
    data = result.scalars().all()
```

---

## 完整的并发处理架构

```
┌─────────────────────────────────────────────────────────────┐
│                      用户请求                                 │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  AWS ALB (Application Load Balancer)                        │
│  - 负载均衡到多个 Pod                                         │
│  - 健康检查                                                   │
│  - 空闲超时：10 分钟（API）/ 5 分钟（前端）                    │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Kubernetes HPA (1-10 Pods)                                 │
│  - 根据 CPU 使用率自动扩缩容                                   │
│  - 每个 Pod: 0.5 核 CPU, 512MB 内存                          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Uvicorn Worker (每个 Pod)                                   │
│  - limit_concurrency: 100 (最多 100 并发连接)                │
│  - timeout_keep_alive: 120s (支持长连接)                     │
│  - limit_max_requests: 10000 (定期重启防内存泄漏)             │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  FastAPI Application                                        │
│  - 异步处理请求                                               │
│  - SecurityMiddleware (CORS/CSRF 检查)                       │
└─────────────────────────────────────────────────────────────┘
                            ↓
        ┌───────────────────┴───────────────────┐
        ↓                                       ↓
┌──────────────────┐                  ┌──────────────────┐
│  PostgreSQL      │                  │  AWS Bedrock     │
│  连接池: 10+20   │                  │  信号量: 50      │
│  (30 并发连接)   │                  │  (50 并发请求)   │
└──────────────────┘                  └──────────────────┘
```

---

## 并发能力评估

### 理论最大并发

#### 单个 Pod

- Uvicorn 并发连接：100
- 数据库连接池：30
- Bedrock 并发：50

#### 10 个 Pod（HPA 最大值）

- 总并发连接：100 × 10 = **1000**
- 总数据库连接：30 × 10 = **300**
- 总 Bedrock 请求：50 × 10 = **500**

### 实际瓶颈分析

| 资源 | 限制 | 瓶颈评估 |
|------|------|---------|
| **Uvicorn 连接** | 1000 | ✅ 足够（通常不是瓶颈） |
| **数据库连接** | 300 | ⚠️ 可能成为瓶颈（取决于查询复杂度） |
| **Bedrock 并发** | 500 | ⚠️ 受 AWS 配额限制 |
| **Pod CPU/内存** | 5 核 / 5GB | ⚠️ 计算密集型任务的瓶颈 |

---

## 超时配置详解

### 配置概览

| 层级 | 配置项 | 超时时间 | 说明 |
|------|--------|---------|------|
| **Bedrock 连接** | `connect_timeout` | 60 秒 | 建立连接的超时 |
| **Bedrock 读取** | `read_timeout` | **1800 秒 (30 分钟)** | 支持超长 AI 任务 |
| **Uvicorn Keep-Alive** | `timeout_keep_alive` | 120 秒 | 空闲连接超时（不影响请求） |
| **ALB 空闲超时（API）** | `idle_timeout` | **600 秒 (10 分钟)** | 可能成为瓶颈 |
| **ALB 空闲超时（前端）** | `idle_timeout` | 300 秒 (5 分钟) | 前端静态资源 |
| **流式心跳** | `STREAM_HEARTBEAT_INTERVAL` | 15 秒 | 保持连接活跃 |

---

### 1. Bedrock 客户端超时

#### 配置位置
`backend/app/services/bedrock.py`

```python
Config(
    region_name=settings.AWS_REGION,
    retries={"max_attempts": 3, "mode": "adaptive"},
    connect_timeout=60,    # 连接超时：60 秒
    read_timeout=1800,     # 读取超时：1800 秒 = 30 分钟
    max_pool_connections=settings.BEDROCK_MAX_CONCURRENT_REQUESTS,
    tcp_keepalive=True,
)
```

#### 说明

- **连接超时（60 秒）**：建立 TCP 连接的最大时间
- **读取超时（30 分钟）**：等待响应数据的最大时间
- ✅ 30 分钟足以支持超长的 AI 生成任务

---

### 2. Uvicorn Keep-Alive 超时

#### 配置位置
- `backend/main.py`
- `backend/app/core/config.py`

```python
UVICORN_TIMEOUT_KEEP_ALIVE = 120  # 120 秒 = 2 分钟
```

#### 重要说明

⚠️ **这不是请求超时！**

`timeout_keep_alive` 是**空闲连接**的保持时间：
- 如果连接在 120 秒内没有新请求，就关闭连接
- **不影响正在进行的请求**
- 请求可以运行任意长时间（受其他超时限制）

#### 实际行为

```python
# 客户端发起请求
POST /v1/chat/completions

# Uvicorn 开始处理请求
# ↓ 请求可以运行任意长时间（受其他超时限制）
# ↓ 30 分钟的 AI 生成任务
# ↓
# 响应完成

# 连接空闲 120 秒后关闭（如果没有新请求）
```

---

### 3. AWS ALB 空闲超时

#### 配置位置
- `k8s/application/ingress-api.yaml` (API 后端)
- `k8s/application/ingress-frontend.yaml` (前端)

#### API 后端配置

```yaml
# API 后端的 ALB 配置
alb.ingress.kubernetes.io/load-balancer-attributes: idle_timeout.timeout_seconds=600
```

**600 秒 = 10 分钟**

#### 前端配置

```yaml
# 前端的 ALB 配置
alb.ingress.kubernetes.io/load-balancer-attributes: idle_timeout.timeout_seconds=300
```

**300 秒 = 5 分钟**

#### 说明

- ALB 空闲超时：如果连接在指定时间内没有数据传输，ALB 会断开连接
- **对于流式响应很重要！**
- ⚠️ 10 分钟 < 30 分钟（Bedrock 超时），可能成为瓶颈

#### AWS ALB 限制

- 最小值：1 秒
- 最大值：4000 秒（约 66 分钟）
- 默认值：60 秒

---

### 4. 流式响应心跳机制

#### 配置位置
- `backend/app/core/config.py`
- `backend/app/api/v1/endpoints/chat.py`

#### 配置参数

```python
STREAM_HEARTBEAT_INTERVAL = 15  # 每 15 秒发送心跳
```

#### 实现代码

```python
async def stream_chat_completion(...):
    last_heartbeat = time.time()

    async for event in bedrock_client.invoke_stream(model, bedrock_request):
        # 发送心跳以保持连接活跃
        current_time = time.time()
        if current_time - last_heartbeat > settings.STREAM_HEARTBEAT_INTERVAL:
            yield ": heartbeat\n\n"  # SSE 注释格式
            last_heartbeat = current_time

        # 处理实际数据
        if event.type == "content_block_delta":
            yield chunk
            last_heartbeat = current_time  # 重置心跳计时
```

#### 工作原理

```
0s    - 请求开始
15s   - 发送心跳 ": heartbeat\n\n"
30s   - 发送心跳
45s   - 发送心跳
...
600s  - 发送心跳（ALB 不会断开，因为有数据传输）
...
1800s - 任务完成（最长 30 分钟）
```

#### ALB 的判断逻辑

- 只要有**任何数据传输**（包括心跳），就不算空闲
- 心跳每 15 秒发送一次，远小于 ALB 的 600 秒超时
- ✅ 即使任务运行 30 分钟，也不会被断开

---

## 超时场景分析

### 场景 1：流式响应（推荐）

```python
# 客户端发送请求
POST /v1/chat/completions
{
  "model": "claude-3-sonnet",
  "messages": [...],
  "stream": true  # 流式
}

# 时间线：
# 0s      - 请求到达
# 1s      - 开始返回第一个 token
# 1-300s  - 持续返回 tokens（每隔几秒一个）
# 15s     - 发送心跳（如果无数据）
# 30s     - 发送心跳
# ...
# 300s    - 完成
```

**结论：** ✅ 流式响应可以运行 30 分钟（心跳保持连接）

---

### 场景 2：非流式响应（短任务）

```python
# 客户端发送请求
POST /v1/chat/completions
{
  "model": "claude-3-sonnet",
  "messages": [...],
  "stream": false  # 非流式
}

# 时间线：
# 0s    - 请求到达
# 0-60s - Bedrock 处理（生成完整响应）
# 60s   - 返回完整响应
```

**结论：** ✅ 60 秒内完成，没有问题

---

### 场景 3：非流式响应（超长任务）

```python
# 假设一个任务需要 15 分钟，且中间没有输出
# 0s      - 请求到达
# 0-900s  - Bedrock 处理中（无数据传输）
# 600s    - ALB 超时，断开连接 ❌
# 900s    - Bedrock 返回结果（但连接已断开）
```

**结论：** ❌ 超过 10 分钟无数据传输会被 ALB 断开

---

## 超时配置链路

```
客户端
  ↓
AWS ALB (10 分钟空闲超时) ⚠️ 可能成为瓶颈
  ↓
Uvicorn (120 秒 keep-alive，不影响请求)
  ↓
FastAPI Application (无超时限制)
  ↓
Bedrock Client (30 分钟读取超时) ✅
  ↓
AWS Bedrock API
```

---

## 性能优化建议

### 短期优化（立即实施）

#### 1. 增加 ALB 超时到 30 分钟

修改 `k8s/application/ingress-api.yaml`：

```yaml
# 从 10 分钟增加到 30 分钟
alb.ingress.kubernetes.io/load-balancer-attributes: idle_timeout.timeout_seconds=1800
```

**优点：**
- ✅ 简单直接
- ✅ 支持超长的非流式任务
- ✅ 与 Bedrock 超时（30 分钟）一致

**缺点：**
- ⚠️ 占用 ALB 连接时间更长
- ⚠️ 可能影响连接池效率

---

#### 2. 推荐使用流式响应

在 API 文档中明确说明：

```python
@router.post("/chat/completions")
async def create_chat_completion(...):
    """
    Create a chat completion.

    **Timeout Limits:**
    - Streaming responses: Up to 30 minutes (with heartbeat)
    - Non-streaming responses: Up to 10 minutes (ALB timeout)

    **Recommendation:** Use streaming for long-running tasks.
    """
```

---

### 中期优化（计划实施）

#### 1. 监控超时情况

添加超时监控和告警：

```python
if duration > 600:  # 超过 10 分钟
    logger.warning("Long-running task detected", extra={
        "duration": duration,
        "model": model,
        "request_id": request_id
    })
```

#### 2. 数据库连接池调优

根据实际负载调整连接池大小：

```python
# 监控连接池使用情况
# 如果经常出现等待，增加连接池大小
DATABASE_POOL_SIZE = 20        # 从 10 增加到 20
DATABASE_MAX_OVERFLOW = 30     # 从 20 增加到 30
```

#### 3. Bedrock 并发限制调优

根据 AWS 配额和实际需求调整：

```python
# 检查 AWS Bedrock 配额
# 调整信号量大小
BEDROCK_MAX_CONCURRENT_REQUESTS = 100  # 从 50 增加到 100
```

---

### 长期优化（架构改进）

#### 1. 异步任务队列

对于超长任务，使用异步处理：

```python
# 使用 Celery 或 AWS SQS
@app.post("/chat/completions/async")
async def create_async_completion(...):
    # 创建任务
    task_id = await task_queue.enqueue(...)
    return {"task_id": task_id, "status": "pending"}

@app.get("/chat/completions/{task_id}")
async def get_completion_result(task_id: str):
    # 轮询结果
    result = await task_queue.get_result(task_id)
    return result
```

#### 2. 缓存层

添加 Redis 缓存减少数据库压力：

```python
# 缓存常用查询结果
@cache(ttl=300)  # 缓存 5 分钟
async def get_user_info(user_id: str):
    return await db.query(User).filter_by(id=user_id).first()
```

#### 3. 读写分离

使用 PostgreSQL 读副本分担查询压力：

```python
# 写操作使用主库
async with write_db() as session:
    await session.execute(insert_query)

# 读操作使用副本
async with read_db() as session:
    result = await session.execute(select_query)
```

---

## 配置文件参考

### 环境变量配置

```bash
# 数据库连接池
KBR_DATABASE_POOL_SIZE=10
KBR_DATABASE_MAX_OVERFLOW=20

# Bedrock 并发限制
KBR_BEDROCK_MAX_CONCURRENT_REQUESTS=50

# Uvicorn 服务器
KBR_UVICORN_TIMEOUT_KEEP_ALIVE=120
KBR_UVICORN_LIMIT_CONCURRENCY=100
KBR_UVICORN_LIMIT_MAX_REQUESTS=10000

# 流式响应心跳
KBR_STREAM_HEARTBEAT_INTERVAL=15
```

### Kubernetes 配置

```yaml
# HPA 配置
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: backend-hpa
spec:
  minReplicas: 1
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70

---
# Pod 资源配置
resources:
  requests:
    cpu: 100m
    memory: 256Mi
  limits:
    cpu: 500m
    memory: 512Mi
```

---

## 监控指标

### 关键指标

1. **数据库连接池**
   - 活跃连接数
   - 等待连接数
   - 连接超时次数

2. **Bedrock 并发**
   - 当前并发请求数
   - 等待队列长度
   - 请求延迟

3. **Pod 资源**
   - CPU 使用率
   - 内存使用率
   - Pod 数量变化

4. **请求超时**
   - 超过 10 分钟的请求数
   - ALB 超时错误数
   - 平均响应时间

---

## 故障排查

### 常见问题

#### 1. 504 Gateway Timeout

**原因：** ALB 空闲超时（10 分钟）

**解决方案：**
- 使用流式响应（推荐）
- 增加 ALB 超时到 30 分钟
- 优化任务执行时间

#### 2. 数据库连接耗尽

**症状：** `TimeoutError: QueuePool limit of size 10 overflow 20 reached`

**解决方案：**
- 增加连接池大小
- 检查是否有连接泄漏
- 优化查询性能

#### 3. Bedrock Throttling

**症状：** `ThrottlingException: Rate exceeded`

**解决方案：**
- 检查 AWS 配额
- 调整信号量大小
- 实现请求重试机制

---

## 总结

本项目通过**多层并发控制**实现高并发处理：

1. ✅ **应用层**：Uvicorn 限制并发连接（100/worker）
2. ✅ **数据库层**：连接池管理（10+20 连接）
3. ✅ **外部服务层**：信号量限制 Bedrock 并发（50）
4. ✅ **基础设施层**：Kubernetes HPA 自动扩容（1-10 Pods）
5. ✅ **负载均衡层**：AWS ALB 分发流量
6. ✅ **超时保护**：心跳机制保持长连接

这是一个**标准的云原生高并发架构**，可以支持数千级别的并发请求。

---

## 相关文档

- [安全配置](./security.zh.md)
- [部署指南](../README.zh.md#部署)
- [API 文档](../README.zh.md#api-文档)

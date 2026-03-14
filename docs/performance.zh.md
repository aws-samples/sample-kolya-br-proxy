# 性能与并发配置

本文档详细说明项目在高并发场景下的优化措施和超时配置。

## 目录

- [高并发处理策略](#高并发处理策略)
  - [Prompt Cache 费用计算](#7-prompt-cache-费用计算)
  - [客户端断开检测](#8-客户端断开检测提前终止流式响应)
  - [ALB 负载均衡算法](#9-alb-负载均衡算法)
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

### 2. AWS Bedrock 请求控制（分布式令牌桶 + 信号量）

#### 配置位置
- `backend/app/services/bedrock.py`
- `backend/app/core/config.py`

#### 配置参数

```python
BEDROCK_MAX_CONCURRENT_REQUESTS = 50   # 最大并发请求数（信号量，每 Pod）
BEDROCK_ACCOUNT_RPM = 500             # AWS Bedrock 账户级 RPM 配额
BEDROCK_EXPECTED_PODS = 3             # 预期 Pod 数（仅在无 Redis 的 local 模式下使用）
BEDROCK_RATE_BURST = 10               # 最大突发大小（令牌桶容量）
```

#### 双层控制：分布式令牌桶 + 信号量

本项目使用**两种互补机制**控制 Bedrock API 访问：

| 机制 | 控制维度 | 解决的问题 |
|------|---------|-----------|
| **分布式令牌桶（Redis）** | 全局所有 Pod 的请求**速率**（req/s） | "整个集群每秒能发多少个新请求？" |
| **信号量** | 每 Pod 的**并发数**（同时进行） | "这个 Pod 能同时跑多少个请求？" |

两者缺一不可，因为解决的是不同问题：

```
没有令牌桶：50 个请求可能在 1ms 内同时到达 → Bedrock 限流
没有信号量：无限请求排队等待 → Pod 内存耗尽
```

#### 分布式令牌桶算法（Redis + Lua）

令牌桶实现为**分布式限流器**，使用 Redis 和原子 Lua 脚本，在所有 Pod 之间提供全局限流。

**核心概念：**

```
所有 Pod 通过 Redis 共享一个令牌桶：
- 令牌以固定速率添加（Redis 模式：BEDROCK_ACCOUNT_RPM / 60 每秒）
- 桶有最大容量（BEDROCK_RATE_BURST）
- 任何 Pod 的每个请求都必须从桶中取走 1 个令牌
- 如果桶是空的，请求等待
- 所有状态存储在 Redis 中（通过 Lua 脚本保证原子性）
```

**实现代码（Redis Lua 脚本 -- 原子操作）：**

```lua
-- 令牌桶状态存储在 Redis key 中
local tokens = tonumber(redis.call('get', KEYS[1]) or capacity)
local last_refill = tonumber(redis.call('get', KEYS[2]) or now)
local elapsed = now - last_refill
tokens = math.min(capacity, tokens + elapsed * rate)
if tokens >= 1.0 then
    tokens = tokens - 1.0
    redis.call('set', KEYS[1], tokens)
    redis.call('set', KEYS[2], now)
    return 1  -- 获取成功
else
    return 0  -- 等待
end
```

**优雅降级（LocalTokenBucket 回退）：**

```python
class LocalTokenBucket:
    """Redis 不可用时的单 Pod 回退方案。"""
    def __init__(self, rate: float, capacity: int):
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._last_refill = time.monotonic()

    async def acquire(self):
        while True:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            wait = (1.0 - self._tokens) / self._rate
            await asyncio.sleep(wait)
```

当 Redis 不可用时，每个 Pod 回退到 `LocalTokenBucket` -- 按 Pod 限流继续生效（而非跳过限流）。这意味着系统优雅降级：限流仍然执行，只是不再全局协调。

**时间线示例（Redis 模式：rate=8.33/s，来自 500 RPM，burst=10）：**

```
0.0s  桶: [██████████] 10 个令牌
      ← 10 个请求同时到达，全部立即通过
0.0s  桶: [          ] 0 个令牌
      ← 第 11 个请求等待...
0.12s 桶: [█         ] 补充 1 个令牌 (8.33 tokens/s × 0.12s ≈ 1)
      ← 第 11 个请求通过
0.24s 桶: [█         ] 1 个令牌
      ← 下一个请求通过
...   稳定状态：每秒通过 ~8.33 个请求（= 500 RPM）
1.2s  连续 1.2 秒无请求
      桶: [██████████] 10 个令牌（补满）
      ← 又可以突发了
```

**为什么选择令牌桶而不是固定窗口或滑动窗口：**

| 算法 | 突发处理 | 窗口边界问题 | 复杂度 |
|------|---------|------------|--------|
| 固定窗口 | 差（窗口边界允许 2 倍突发） | 有 | 低 |
| 滑动窗口 | 好 | 无 | 中 |
| **令牌桶** | **最优（自然突发 + 平滑速率）** | **无** | **低** |

令牌桶天然适合处理突发流量（AI Proxy 的典型负载模式），同时严格保证平均速率。

#### 请求生命周期

```
请求到达
  ↓
TokenBucket.acquire()    ← 等待速率限制令牌（控制 req/s）
  ↓
Semaphore.acquire()      ← 等待并发槽位（控制并行数）
  ↓
Bedrock API 调用
  ↓
Semaphore.release()      ← 释放并发槽位（流结束时释放）
```

```python
async def invoke(self, model_name, request):
    await self._rate_limiter.acquire()   # 令牌桶：速率控制
    async with self._semaphore:          # 信号量：并发控制
        return await self._invoke_inner(model_name, request)

async def invoke_stream(self, model_name, request):
    await self._rate_limiter.acquire()   # 令牌桶：速率控制
    async with self._semaphore:          # 信号量：整个流期间持有
        async for event in self._invoke_stream_inner(model_name, request):
            yield event
```

#### 多 Pod 速率限制策略

使用**分布式 Redis 令牌桶**后，所有 Pod 共享一个全局速率限制。无需按 Pod 数分割配额 -- Redis 原子地确保全局速率。

```
                    Bedrock 配额: 500 RPM (8.33 req/s)
                    ┌──────────────────────────────────┐
                    │                                    │
  Pod 1 ─────┐     │                                    │
  Pod 2 ─────┤─[Redis 令牌桶: 8.33 req/s]──▶           │
  Pod 3 ─────┘     │        AWS Bedrock API             │
  ...              │                                    │
  Pod N ─────┘     │  全局速率: 8.33 req/s = 500 RPM   │
                    └──────────────────────────────────┘
```

**分布式限流的优势：**

- 无需估算预期 Pod 数 -- 无论运行多少个 Pod，全局速率始终准确
- Pod 扩缩容不影响整体限流
- 降级时（Redis 不可用），每个 Pod 使用 `LocalTokenBucket`，按保守的单 Pod 速率计算（`账户 RPM / 60 / 预期 Pod 数`）
- Karpenter 负责创建 Node（基础设施），HPA 控制 Pod 数量 -- maxReplicas 是硬上限

#### 自适应重试作为安全兜底

即使有 Pod 级别的速率限制，botocore 的 `adaptive` 重试模式提供最后一层保护：

```python
Config(
    retries={"max_attempts": 3, "mode": "adaptive"},
)
```

如果 Bedrock 仍然返回 429（限流），SDK 会自动指数退避重试。这处理了多个 Pod 同时突发的边缘情况。

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

### 6. API Token 哈希查找优化

#### 配置位置
- `backend/app/core/security.py`
- `backend/app/services/token.py`
- `backend/app/models/token.py`

#### 实现原理

使用 SHA256 哈希实现 O(1) 数据库索引查找，替代 O(n) 线性扫描。

```python
# 生成 token 哈希（security.py）
def hash_token(token: str) -> str:
    """使用 SHA256 对 token 进行哈希"""
    return hashlib.sha256(token.encode()).hexdigest()
```

#### 工作流程

**1. Token 创建时**

```python
# 用户创建 API Token
plain_token = generate_api_token()  # 生成: kbr_abc123def456...

# 计算哈希值存入数据库
token_hash = hash_token(plain_token)  # SHA256 哈希

# 数据库存储
token = APIToken(
    token_hash=token_hash,           # 用于快速查找
    encrypted_token=encrypt_token(plain_token),  # 用于恢复原文
)
```

**2. Token 验证时**

```python
# 客户端发送请求
Authorization: Bearer kbr_abc123def456...

# 后端验证（优化后）
token_hash = hash_token(plain_token)  # 计算哈希

# 直接通过哈希查询（使用数据库索引）
result = await db.execute(
    select(APIToken).where(
        APIToken.token_hash == token_hash,  # 索引查询，O(1)
        APIToken.is_active.is_(True)
    )
)
```

#### 性能对比

| 方法 | 查询方式 | 时间复杂度 | 实际耗时 | 说明 |
|------|---------|-----------|---------|------|
| **优化前** | 遍历所有 token 逐个解密比对 | O(n) | ~10 秒 | 20,000 个 token |
| **优化后** | 哈希索引直接查询 | O(1) | ~0.5 毫秒 | 使用数据库索引 |
| **性能提升** | - | - | **20,000 倍** | - |

#### 性能测试结果

```python
# 测试场景：数据库中有 20,000 个 API Token

# 优化前（线性扫描）
for token in all_tokens:  # 20,000 次循环
    if decrypt_token(token.encrypted_token) == plain_token:
        return token
# 耗时：~10 秒（每次解密 0.5ms × 20,000）

# 优化后（哈希索引）
token_hash = hash_token(plain_token)  # 0.01ms
token = db.query(APIToken).filter_by(token_hash=token_hash).first()  # 0.5ms
# 耗时：~0.5 毫秒（索引查询）
```

#### 数据库索引

```python
# models/token.py
class APIToken(Base):
    __tablename__ = "api_tokens"

    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    #                                              ^^^^^ 关键：创建索引
```

**索引的作用：**
- ✅ 将查询时间从 O(n) 降低到 O(1)
- ✅ 数据库自动维护 B-Tree 索引结构
- ✅ 支持快速精确匹配查询

#### 安全优势

**1. 数据库泄露保护**

```python
# 假设数据库被攻击者获取
# 攻击者看到的数据：
{
    "token_hash": "a3f5b8c9d2e1f4a7b6c5d8e9f1a2b3c4...",  # SHA256 哈希
    "encrypted_token": "gAAAAABf3x..."                    # Fernet 加密
}

# 攻击者无法：
# ❌ 从 token_hash 反推原始 token（SHA256 单向哈希）
# ❌ 解密 encrypted_token（需要 KBR_JWT_SECRET_KEY）
# ❌ 使用 token_hash 调用 API（API 需要原始 token）
```

**2. 无需密钥管理**

```python
# 哈希查找：无需密钥
token_hash = hashlib.sha256(token.encode()).hexdigest()  # 纯算法

# 对比：加密存储需要密钥
_fernet = Fernet(_get_encryption_key())  # 需要 KBR_JWT_SECRET_KEY
encrypted = _fernet.encrypt(token.encode())
```

**优势：**
- ✅ 哈希是确定性的（同样输入 = 同样输出）
- ✅ 不需要密钥存储和管理
- ✅ 不存在密钥泄露风险
- ✅ 适合用于数据库索引查询

#### 双重保护机制

本项目使用**哈希 + 加密**双重保护：

```python
# 1. 哈希（用于查找）
token_hash = hash_token(plain_token)  # SHA256，无密钥
# 用途：数据库索引查询，O(1) 性能
# 安全：单向哈希，无法反推原文

# 2. 加密（用于存储）
encrypted_token = encrypt_token(plain_token)  # Fernet，需要密钥
# 用途：可恢复原始 token（如需要重新显示）
# 安全：对称加密，需要 KBR_JWT_SECRET_KEY 才能解密
```

#### 实际应用场景

**场景 1：API 请求验证（高频）**

```python
# 每个 API 请求都需要验证 token
# 使用哈希查找，0.5ms 完成

@router.post("/v1/chat/completions")
async def chat(token: str = Depends(get_api_token)):
    # token 已通过哈希查找验证（快速）
    return await process_chat(token)
```

**场景 2：Token 管理界面（低频）**

```python
# 用户查看自己的 token 列表
# 可以选择显示完整 token（解密）

@router.get("/tokens/{token_id}/reveal")
async def reveal_token(token_id: UUID):
    token = await token_service.get_token_by_id(token_id)
    plain_token = decrypt_token(token.encrypted_token)  # 解密恢复
    return {"token": plain_token}
```

#### 配置要求

```bash
# 环境变量（用于加密存储，不影响哈希查找）
KBR_JWT_SECRET_KEY=your-secret-key-here

# 数据库迁移（确保索引存在）
alembic upgrade head
```

#### 监控指标

```python
# 记录 token 验证性能
import time

start = time.time()
token = await token_service.validate_token(plain_token)
duration = time.time() - start

if duration > 0.01:  # 超过 10ms
    logger.warning("Slow token validation", extra={
        "duration": duration,
        "token_id": token.id if token else None
    })
```

---

### 7. Prompt Cache 费用计算

Prompt cache token（cache 写入和 cache 读取）与常规 input token 采用不同费率计价。详细公式、数据库存储和 OpenAI 兼容响应格式，请参阅[动态价格系统 — 价格计算](./pricing-system.zh.md#价格计算)。

---

### 8. 客户端断开检测（提前终止流式响应）

#### 问题

当客户端在流式传输过程中断开（例如用户在 opencode 中按 ESC），如果不检测：
- Bedrock 继续生成 token（浪费费用）
- 信号量持续被占用（阻塞其他请求）
- Pod 资源被占用直到流自然结束

#### 解决方案

流式 generator 每约 1 秒检查一次 `request.is_disconnected()`。检测到断开后立即 break，触发 async generator 清理链：

```python
async for event in bedrock_client.invoke_stream(model, bedrock_request):
    # 节流检查断开（约 1 秒间隔）
    if http_request and current_time - last_heartbeat > 1.0:
        if await http_request.is_disconnected():
            break  # 触发清理链

    yield f"data: {chunk}\n\n"
```

#### 清理链路

```
chat.py: break（客户端断开）
  ↓ Python async generator 协议：调用内层 generator 的 .aclose()
bedrock.py: invoke_stream() 退出
  ↓ async with self._semaphore: __aexit__ → 信号量释放 ✅
  ↓ async with self.session.client(...): __aexit__ → HTTP 连接关闭 ✅
Bedrock: 收到 TCP FIN/RST → 停止生成 ✅
```

#### 断开后的行为

- 已消费的 token **仍然记录**到数据库（费用不能漏记）
- Usage chunk 和 done marker **不发送**（客户端已断开）
- 日志标记 `client_disconnected: true`，便于监控

#### 为什么不逐 chunk 检查

`is_disconnected()` 是异步调用（检查 ASGI receive channel）。每个 chunk 都检查会增加不必要的开销。约 1 秒的节流间隔在响应速度和性能之间取得平衡。

---

### 9. ALB 负载均衡算法

#### 配置

```yaml
alb.ingress.kubernetes.io/target-group-attributes: >
  deregistration_delay.timeout_seconds=30,
  load_balancing.algorithm.type=round_robin
```

#### 为什么全局令牌桶下用 `round_robin`

有了分布式 Redis 令牌桶做全局限流后，`round_robin` 是最合适的：

- 全局令牌桶已经控制了所有 Pod 的请求速率
- 每个 Pod 收到的请求经过统一限流，处理时间基本一致
- 轮询保证均匀分配，避免热点
- `least_outstanding_requests` 在此场景下反而有害：流式响应会长时间保持连接，让 Pod _看起来_很忙（实际只是在等 Bedrock 输出）——新请求会堆积到恰好流数较少的 Pod

```
全局令牌桶（Redis）：              Round Robin：
所有 Pod 共享一个速率限制 →       Pod 1: ████ (4 个流) ← 新请求
8.33 req/s（500 RPM）            Pod 2: ████ (4 个流)
                                  Pod 3: ████ (4 个流)
                                         （均匀分布）
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
┌──────────────────┐    ┌───────────────┐    ┌──────────────────┐
│  PostgreSQL      │    │  Redis        │    │  AWS Bedrock       │
│  连接池: 10+20   │    │  分布式       │    │  分布式            │
│  (30 并发连接)   │    │  令牌桶       │    │  令牌桶(Redis)     │
└──────────────────┘    │  (全局)       │    │  信号量: 50        │
                        └───────────────┘    └────────────────────┘
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
| **Bedrock 连接** | `connect_timeout` | 10 秒 | 建立连接的超时 |
| **Bedrock 读取** | `read_timeout` | **300 秒 (5 分钟)** | 每次 chunk 读取超时（覆盖 thinking 模型暂停和长 prefill） |
| **Uvicorn Keep-Alive** | `timeout_keep_alive` | 120 秒 | 空闲连接超时（不影响请求） |
| **ALB 空闲超时（API）** | `idle_timeout` | **600 秒 (10 分钟)** | 外层兜底；必须大于 read_timeout，确保 Bedrock 错误先返回 |
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
    connect_timeout=10,    # 连接超时：10 秒
    read_timeout=300,      # 读取超时：5 分钟，覆盖 thinking 模型暂停
    max_pool_connections=settings.BEDROCK_MAX_CONCURRENT_REQUESTS,
    tcp_keepalive=True,
)
```

#### 说明

- **连接超时（10 秒）**：建立 TCP 连接的最大时间
- **读取超时（300 秒）**：每次 socket read 的最大等待时间，作用于首字节和后续每个 streaming chunk。Thinking 模型（如 Claude extended thinking）在推理阶段可能暂停数分钟才产出输出
- ✅ 300 秒覆盖 thinking 模型暂停、长 prefill 延迟和 Bedrock 排队等待

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
- ✅ ALB 空闲超时（600 秒）> Bedrock read timeout（300 秒），确保 Bedrock 错误先返回有意义的错误信息，而不是 504
- 流式场景下心跳每 15 秒发送一次，无论 idle timeout 多大都不会超时

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
120s  - 发送心跳（ALB 不会断开，因为有数据传输）
...
结束   - 任务完成（streaming 无总时长限制）
```

#### ALB 的判断逻辑

- 只要有**任何数据传输**（包括心跳），就不算空闲
- 心跳每 15 秒发送一次，远小于 ALB 的 600 秒超时
- ✅ 即使任务运行很长时间，也不会被断开

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

**结论：** ✅ 流式响应可以无限运行（心跳保持连接）

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
# 假设一个任务需要 3 分钟，且中间没有输出
# 0s      - 请求到达
# 0-180s  - Bedrock 处理中（无数据传输）
# 300s    - Bedrock read_timeout 触发，后端返回有意义的错误 ❌
# （如果 read_timeout 未触发）
# 600s    - ALB 空闲超时，断开连接作为最终兜底 ❌
```

**结论：** ❌ 非流式任务超过 300 秒会被 read_timeout 终止。长任务请使用 streaming。

---

## 超时配置链路

```
客户端
  ↓
AWS ALB (10 分钟空闲超时) ✅ 外层兜底，大于 read_timeout
  ↓
Uvicorn (120 秒 keep-alive，不影响请求)
  ↓
FastAPI Application (无超时限制)
  ↓
Bedrock Client (300 秒读取超时) ✅ 覆盖 thinking 模型暂停
  ↓
AWS Bedrock API
```

---

## 性能优化建议

### 短期优化（立即实施）

#### 1. 推荐使用流式响应

在 API 文档中明确说明：

```python
@router.post("/chat/completions")
async def create_chat_completion(...):
    """
    Create a chat completion.

    **超时链：**
    - Bedrock connect: 10 秒（TCP 连接）
    - Bedrock read: 300 秒（每次 chunk 读取超时，覆盖 thinking 暂停）
    - ALB idle: 600 秒（外层兜底；流式心跳保持连接活跃）

    **建议：** 长任务请使用 streaming。
    """
```

---

### 中期优化（计划实施）

#### 1. 监控超时情况

添加超时监控和告警：

```python
if duration > 60:  # 超过 60 秒
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

# Bedrock 请求控制
KBR_BEDROCK_MAX_CONCURRENT_REQUESTS=50
KBR_BEDROCK_ACCOUNT_RPM=500
KBR_BEDROCK_EXPECTED_PODS=3
KBR_BEDROCK_RATE_BURST=10

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
   - 超过 300 秒的请求数（read timeout）
   - ALB 超时错误数（600 秒兜底）
   - 平均响应时间

---

## 故障排查

### 常见问题

#### 1. 504 Gateway Timeout

**原因：** Bedrock 读取超时（300 秒）或 ALB 空闲超时（600 秒）

**解决方案：**
- 使用流式响应（推荐）
- 检查 Bedrock 服务是否正常
- 验证到 Bedrock 端点的网络连通性

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
3. ✅ **外部服务层**：分布式 Redis 令牌桶（全局速率）+ 信号量（50 并发）控制 Bedrock 访问，Redis 不可用时回退到 LocalTokenBucket
4. ✅ **基础设施层**：Kubernetes HPA 自动扩容（1-10 Pods）
5. ✅ **负载均衡层**：AWS ALB 使用 round-robin 算法（配合全局令牌桶均匀分配）
6. ✅ **超时保护**：心跳机制保持长连接
7. ✅ **费用优化**：Prompt cache 差异化计价（详见[价格系统](./pricing-system.zh.md#prompt-cache-差异化计价)）
8. ✅ **资源保护**：客户端断开检测，提前终止 Bedrock 流

---

## 相关文档

- [动态价格系统](./pricing-system.zh.md)
- [安全配置](./security.zh.md)
- [部署指南](../README.zh.md#部署)
- [API 文档](../README.zh.md#api-文档)

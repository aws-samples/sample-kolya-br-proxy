# Performance and Concurrency Configuration

This document details the optimization measures and timeout configurations for high-concurrency scenarios.

## Table of Contents

- [High Concurrency Handling Strategies](#high-concurrency-handling-strategies)
  - [Prompt Cache Cost Calculation](#7-prompt-cache-cost-calculation)
  - [Client Disconnect Detection](#8-client-disconnect-detection-early-stream-termination)
  - [ALB Load Balancing Algorithm](#9-alb-load-balancing-algorithm)
- [Timeout Configuration Details](#timeout-configuration-details)
- [Concurrency Capacity Assessment](#concurrency-capacity-assessment)
- [Performance Optimization Recommendations](#performance-optimization-recommendations)

---

## High Concurrency Handling Strategies

### 1. Database Connection Pool Management

#### Configuration Location
- `backend/app/core/database.py`
- `backend/app/core/config.py`

#### Configuration Parameters

```python
DATABASE_POOL_SIZE = 10        # Connection pool size
DATABASE_MAX_OVERFLOW = 20     # Maximum overflow connections
```

**Actual available connections = 10 + 20 = 30 concurrent database connections**

#### How It Works

```
Requests 1-10  → Use persistent connections from pool (fast)
Requests 11-30 → Create temporary overflow connections (slower)
Requests 31+   → Wait for connection release (queued)
```

#### Advantages

- ✅ Avoid frequent connection creation/destruction (high performance overhead)
- ✅ Limit maximum connections to protect database from overload
- ✅ Automatic connection recycling and health checks

#### Environment Differences

```python
if settings.DEBUG:
    # Development: No connection pooling (NullPool)
    # Create new connection per request for easier debugging
    engine = create_async_engine(..., poolclass=NullPool)
else:
    # Production: Use connection pooling
    engine = create_async_engine(..., pool_size=10, max_overflow=20)
```

#### Session Management

```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()  # Rollback on exception
            raise
        finally:
            await session.close()     # Ensure connection release
```

---

### 2. AWS Bedrock Request Control (Distributed Token Bucket + Semaphore)

#### Configuration Location
- `backend/app/services/bedrock.py`
- `backend/app/core/config.py`

#### Configuration Parameters

```python
BEDROCK_MAX_CONCURRENT_REQUESTS = 50   # Maximum concurrent requests (semaphore, per Pod)
BEDROCK_ACCOUNT_RPM = 500             # AWS Bedrock account-level RPM quota
BEDROCK_EXPECTED_PODS = 3             # Expected Pods (only used in local mode without Redis)
BEDROCK_RATE_BURST = 10               # Maximum burst size (token bucket capacity)
```

#### Two-Layer Control: Distributed Token Bucket + Semaphore

This project uses **two complementary mechanisms** to control Bedrock API access:

| Mechanism | Controls | Question It Answers |
|-----------|----------|-------------------|
| **Distributed Token Bucket (Redis)** | Request **rate** (req/s) globally across all Pods | "How fast can the entire cluster send new requests?" |
| **Semaphore** | **Concurrency** (simultaneous) per Pod | "How many requests can run at the same time on this Pod?" |

Both are needed because they solve different problems:

```
Without token bucket: 50 requests could arrive in 1ms → Bedrock throttled
Without semaphore:    Unlimited requests queued → Pod memory exhaustion
```

#### Distributed Token Bucket Algorithm (Redis + Lua)

The token bucket is implemented as a **distributed rate limiter** using Redis and an atomic Lua script, providing global rate limiting across all Pods.

**Core Concept:**

```
A single token bucket shared across all Pods via Redis:
- Tokens are added at a fixed rate (BEDROCK_ACCOUNT_RPM / 60 per second in Redis mode)
- The bucket has a maximum capacity (BEDROCK_RATE_BURST)
- Each request from any Pod must take 1 token from the bucket
- If the bucket is empty, the request waits
- All state is stored in Redis (atomic via Lua script)
```

**Implementation (Redis Lua script -- atomic operation):**

```lua
-- Token bucket state stored in Redis key
local tokens = tonumber(redis.call('get', KEYS[1]) or capacity)
local last_refill = tonumber(redis.call('get', KEYS[2]) or now)
local elapsed = now - last_refill
tokens = math.min(capacity, tokens + elapsed * rate)
if tokens >= 1.0 then
    tokens = tokens - 1.0
    redis.call('set', KEYS[1], tokens)
    redis.call('set', KEYS[2], now)
    return 1  -- acquired
else
    return 0  -- wait
end
```

**Graceful Degradation (LocalTokenBucket fallback):**

```python
class LocalTokenBucket:
    """Per-Pod fallback when Redis is unavailable."""
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

When Redis is down, each Pod falls back to `LocalTokenBucket` -- per-Pod rate limiting continues (not skip). This means the system degrades gracefully: rate limiting is still enforced, just not globally coordinated.

**Timeline Example (Redis mode: rate=8.33/s from 500 RPM, burst=10):**

```
0.0s  Bucket: [██████████] 10 tokens
      ← 10 requests arrive simultaneously, all pass immediately
0.0s  Bucket: [          ] 0 tokens
      ← 11th request waits...
0.12s Bucket: [█         ] 1 token refilled (8.33 tokens/s × 0.12s ≈ 1)
      ← 11th request passes
0.24s Bucket: [█         ] 1 token
      ← next request passes
...   Steady state: ~8.33 requests per second (= 500 RPM)
1.2s  No requests for 1.2 seconds
      Bucket: [██████████] 10 tokens (refilled to capacity)
      ← Ready for another burst
```

**Why Token Bucket Instead of Fixed Window or Sliding Window:**

| Algorithm | Burst Handling | Boundary Issue | Complexity |
|-----------|---------------|----------------|------------|
| Fixed Window | Poor (reset at window boundary allows 2x burst) | Yes | Low |
| Sliding Window | Good | No | Medium |
| **Token Bucket** | **Best (natural burst + smooth rate)** | **No** | **Low** |

Token bucket naturally handles bursty traffic (common in AI proxy workloads) while maintaining a strict average rate.

#### Request Lifecycle

```
Request arrives
  ↓
TokenBucket.acquire()    ← Wait for rate limit token (controls req/s)
  ↓
Semaphore.acquire()      ← Wait for concurrency slot (controls parallelism)
  ↓
Bedrock API call
  ↓
Semaphore.release()      ← Free concurrency slot (on stream end)
```

```python
async def invoke(self, model_name, request):
    await self._rate_limiter.acquire()   # Token bucket: rate control
    async with self._semaphore:          # Semaphore: concurrency control
        return await self._invoke_inner(model_name, request)

async def invoke_stream(self, model_name, request):
    await self._rate_limiter.acquire()   # Token bucket: rate control
    async with self._semaphore:          # Semaphore: held for entire stream
        async for event in self._invoke_stream_inner(model_name, request):
            yield event
```

#### Multi-Pod Rate Limiting Strategy

With the **distributed Redis token bucket**, all Pods share a single global rate limit. There is no need to divide the quota by the number of Pods -- Redis ensures the global rate is enforced atomically.

```
                    Bedrock Quota: 500 RPM (8.33 req/s)
                    ┌──────────────────────────────────┐
                    │                                    │
  Pod 1 ─────┐     │                                    │
  Pod 2 ─────┤─[Redis Token Bucket: 8.33 req/s]──▶     │
  Pod 3 ─────┘     │        AWS Bedrock API             │
  ...              │                                    │
  Pod N ─────┘     │  Global rate: 8.33 req/s = 500 RPM│
                    └──────────────────────────────────┘
```

**Advantages of distributed rate limiting:**

- No need to estimate expected Pod count -- the global rate is always correct regardless of how many Pods are running
- Scaling up/down Pods does not affect the overall rate limit
- During fallback (Redis down), each Pod uses `LocalTokenBucket` with a conservative per-Pod rate calculated as `Account RPM / 60 / expected Pods`
- Karpenter provisions Nodes (infrastructure), HPA controls Pod count -- maxReplicas is the hard cap

#### Adaptive Retry as Safety Net

Even with per-Pod rate limiting, the botocore `adaptive` retry mode provides a final safety layer:

```python
Config(
    retries={"max_attempts": 3, "mode": "adaptive"},
)
```

If Bedrock still returns 429 (throttling), the SDK automatically retries with exponential backoff. This handles edge cases where multiple Pods burst simultaneously.

---

### 3. Uvicorn Server Concurrency Control

#### Configuration Location
- `backend/main.py`
- `backend/app/core/config.py`

#### Configuration Parameters

```python
UVICORN_TIMEOUT_KEEP_ALIVE = 120      # Keep connection alive for 120 seconds
UVICORN_LIMIT_CONCURRENCY = 100       # Max 100 concurrent connections per worker
UVICORN_LIMIT_MAX_REQUESTS = 10000    # Restart worker after 10000 requests
```

#### Startup Configuration

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

#### Parameter Descriptions

| Parameter | Purpose | Why Needed |
|-----------|---------|------------|
| `timeout_keep_alive=120` | Keep connection for 2 minutes | Support long AI streaming responses |
| `limit_concurrency=100` | Limit concurrent connections | Prevent single worker overload |
| `limit_max_requests=10000` | Periodic worker restart | Prevent memory leak accumulation |

---

### 4. Kubernetes Horizontal Pod Autoscaling (HPA)

#### Configuration Location
- `k8s/application/hpa-backend.yaml`
- `k8s/application/backend-deployment.yaml`

#### HPA Configuration

```yaml
# Backend autoscaling configuration
minReplicas: 1      # Minimum 1 Pod
maxReplicas: 10     # Maximum 10 Pods

metrics:
- type: Resource
  resource:
    name: cpu
    target:
      type: Utilization
      averageUtilization: 70  # Scale up when CPU > 70%
```

#### Scaling Strategy

```
Normal traffic:  1-2 Pods
Medium traffic:  3-5 Pods (CPU > 70%)
Peak traffic:    6-10 Pods (sustained high load)
Traffic drops:   Auto-scale back to 1 Pod
```

#### Pod Resource Configuration

```yaml
resources:
  requests:
    cpu: 100m      # Guaranteed 0.1 core
    memory: 256Mi  # Guaranteed 256MB
  limits:
    cpu: 500m      # Maximum 0.5 core
    memory: 512Mi  # Maximum 512MB
```

---

### 5. Async Database Driver

#### Configuration

```python
# Use asyncpg (async PostgreSQL driver)
DATABASE_URL = "postgresql+asyncpg://user:password@host:5432/db"  # pragma: allowlist secret
```

#### Advantages

- ✅ Support true async I/O
- ✅ Non-blocking event loop
- ✅ Higher concurrent processing capacity

#### Usage Example

```python
# Execute query asynchronously
async with async_session_maker() as session:
    result = await session.execute(query)  # Async execution
    data = result.scalars().all()
```

---

### 6. API Token Hash Lookup Optimization

#### Configuration Location
- `backend/app/core/security.py`
- `backend/app/services/token.py`
- `backend/app/models/token.py`

#### Implementation Principle

Uses SHA256 hashing to achieve O(1) database index lookup, replacing O(n) linear scanning.

```python
# Generate token hash (security.py)
def hash_token(token: str) -> str:
    """Hash token using SHA256"""
    return hashlib.sha256(token.encode()).hexdigest()
```

#### Workflow

**1. Token Creation**

```python
# User creates API Token
plain_token = generate_api_token()  # Generates: kbr_abc123def456...

# Calculate hash for database storage
token_hash = hash_token(plain_token)  # SHA256 hash

# Database storage
token = APIToken(
    token_hash=token_hash,           # For fast lookup
    encrypted_token=encrypt_token(plain_token),  # For recovery
)
```

**2. Token Validation**

```python
# Client sends request
Authorization: Bearer kbr_abc123def456...

# Backend validation (optimized)
token_hash = hash_token(plain_token)  # Calculate hash

# Query directly by hash (using database index)
result = await db.execute(
    select(APIToken).where(
        APIToken.token_hash == token_hash,  # Index query, O(1)
        APIToken.is_active.is_(True)
    )
)
```

#### Performance Comparison

| Method | Query Type | Time Complexity | Actual Time | Notes |
|--------|-----------|----------------|-------------|-------|
| **Before** | Iterate all tokens, decrypt and compare | O(n) | ~10 seconds | 20,000 tokens |
| **After** | Hash index direct query | O(1) | ~0.5 milliseconds | Using database index |
| **Improvement** | - | - | **20,000x faster** | - |

#### Performance Test Results

```python
# Test scenario: Database contains 20,000 API Tokens

# Before optimization (linear scan)
for token in all_tokens:  # 20,000 iterations
    if decrypt_token(token.encrypted_token) == plain_token:
        return token
# Time: ~10 seconds (0.5ms per decryption × 20,000)

# After optimization (hash index)
token_hash = hash_token(plain_token)  # 0.01ms
token = db.query(APIToken).filter_by(token_hash=token_hash).first()  # 0.5ms
# Time: ~0.5 milliseconds (index query)
```

#### Database Index

```python
# models/token.py
class APIToken(Base):
    __tablename__ = "api_tokens"

    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    #                                              ^^^^^ Key: Create index
```

**Index Benefits:**
- ✅ Reduces query time from O(n) to O(1)
- ✅ Database automatically maintains B-Tree index structure
- ✅ Supports fast exact match queries

#### Security Advantages

**1. Database Breach Protection**

```python
# Assume database is compromised by attacker
# Attacker sees:
{
    "token_hash": "a3f5b8c9d2e1f4a7b6c5d8e9f1a2b3c4...",  # SHA256 hash
    "encrypted_token": "gAAAAABf3x..."                    # Fernet encryption
}

# Attacker cannot:
# ❌ Reverse token_hash to original token (SHA256 is one-way)
# ❌ Decrypt encrypted_token (requires KBR_JWT_SECRET_KEY)
# ❌ Use token_hash to call API (API requires original token)
```

**2. No Key Management Required**

```python
# Hash lookup: No key needed
token_hash = hashlib.sha256(token.encode()).hexdigest()  # Pure algorithm

# Compare: Encryption requires key
_fernet = Fernet(_get_encryption_key())  # Requires KBR_JWT_SECRET_KEY
encrypted = _fernet.encrypt(token.encode())
```

**Advantages:**
- ✅ Hashing is deterministic (same input = same output)
- ✅ No key storage or management needed
- ✅ No key leakage risk
- ✅ Suitable for database index queries

#### Dual Protection Mechanism

This project uses **hash + encryption** dual protection:

```python
# 1. Hash (for lookup)
token_hash = hash_token(plain_token)  # SHA256, no key
# Purpose: Database index query, O(1) performance
# Security: One-way hash, cannot reverse to original

# 2. Encryption (for storage)
encrypted_token = encrypt_token(plain_token)  # Fernet, requires key
# Purpose: Recoverable original token (if need to display again)
# Security: Symmetric encryption, requires KBR_JWT_SECRET_KEY to decrypt
```

#### Real-World Use Cases

**Scenario 1: API Request Validation (High Frequency)**

```python
# Every API request needs token validation
# Using hash lookup, completes in 0.5ms

@router.post("/v1/chat/completions")
async def chat(token: str = Depends(get_api_token)):
    # Token already validated via hash lookup (fast)
    return await process_chat(token)
```

**Scenario 2: Token Management UI (Low Frequency)**

```python
# User views their token list
# Can choose to display full token (decrypt)

@router.get("/tokens/{token_id}/reveal")
async def reveal_token(token_id: UUID):
    token = await token_service.get_token_by_id(token_id)
    plain_token = decrypt_token(token.encrypted_token)  # Decrypt to recover
    return {"token": plain_token}
```

#### Configuration Requirements

```bash
# Environment variable (for encryption storage, doesn't affect hash lookup)
KBR_JWT_SECRET_KEY=your-secret-key-here

# Database migration (ensure index exists)
alembic upgrade head
```

#### Monitoring Metrics

```python
# Record token validation performance
import time

start = time.time()
token = await token_service.validate_token(plain_token)
duration = time.time() - start

if duration > 0.01:  # More than 10ms
    logger.warning("Slow token validation", extra={
        "duration": duration,
        "token_id": token.id if token else None
    })
```

---

### 7. Prompt Cache Cost Calculation

Prompt cache tokens (cache write and cache read) are priced differently from regular input tokens. For detailed formula, database storage, and OpenAI-compatible response format, see [Dynamic Pricing System — Price Calculation](./pricing-system.md#price-calculation).

---

### 8. Client Disconnect Detection (Early Stream Termination)

#### Problem

When a client disconnects mid-stream (e.g., user presses ESC in opencode), without detection:
- Bedrock continues generating tokens (wasting money)
- Semaphore remains held (blocking other requests)
- Pod resources occupied until stream completes naturally

#### Solution

The streaming generator checks `request.is_disconnected()` every ~1 second. On disconnect, it immediately breaks the loop, triggering async generator cleanup:

```python
async for event in bedrock_client.invoke_stream(model, bedrock_request):
    # Throttled disconnect check (~1 second interval)
    if http_request and current_time - last_heartbeat > 1.0:
        if await http_request.is_disconnected():
            break  # Triggers cleanup chain

    yield f"data: {chunk}\n\n"
```

#### Cleanup Chain

```
chat.py: break (client disconnected)
  ↓ Python async generator protocol: .aclose() called on inner generator
bedrock.py: invoke_stream() exits
  ↓ async with self._semaphore: __aexit__ → semaphore released ✅
  ↓ async with self.session.client(...): __aexit__ → HTTP connection closed ✅
Bedrock: receives TCP FIN/RST → stops generation ✅
```

#### What Happens After Disconnect

- Tokens already consumed are **still recorded** to the database (costs should not be lost)
- Usage chunk and done marker are **not sent** (client is gone)
- Log entry includes `client_disconnected: true` for monitoring

#### Why Not Check Every Chunk

`is_disconnected()` is an async call that checks the ASGI receive channel. Checking every chunk would add unnecessary overhead. The ~1 second throttle interval balances responsiveness with performance.

---

### 9. ALB Load Balancing Algorithm

#### Configuration

```yaml
alb.ingress.kubernetes.io/target-group-attributes: >
  deregistration_delay.timeout_seconds=30,
  load_balancing.algorithm.type=round_robin
```

#### Why `round_robin` With a Global Token Bucket

With the distributed Redis token bucket providing global rate limiting, `round_robin` is the best fit:

- The global token bucket already controls the request rate across all Pods
- Each Pod receives the same rate-limited workload, so processing time per request is similar
- Round-robin ensures even distribution, preventing hot spots
- `least_outstanding_requests` would be counterproductive here: streaming responses keep connections open for seconds, making Pods _appear_ busy when they're just waiting for Bedrock output — new requests would pile up on Pods that happen to have fewer streams

```
Global Token Bucket (Redis):    Round Robin:
All Pods share one rate limit → Pod 1: ████ (4 streams) ← next request
8.33 req/s (500 RPM)            Pod 2: ████ (4 streams)
                                 Pod 3: ████ (4 streams)
                                        (evenly distributed)
```

---

## Complete Concurrency Handling Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      User Requests                           │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  AWS ALB (Application Load Balancer)                        │
│  - Load balance across multiple Pods                        │
│  - Health checks                                            │
│  - Idle timeout: 10 min (API) / 5 min (Frontend)           │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Kubernetes HPA (1-10 Pods)                                 │
│  - Auto-scale based on CPU utilization                      │
│  - Each Pod: 0.5 CPU core, 512MB memory                    │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Uvicorn Worker (per Pod)                                   │
│  - limit_concurrency: 100 (max 100 concurrent connections) │
│  - timeout_keep_alive: 120s (support long connections)     │
│  - limit_max_requests: 10000 (periodic restart)            │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  FastAPI Application                                        │
│  - Async request processing                                 │
│  - SecurityMiddleware (CORS/CSRF checks)                    │
└─────────────────────────────────────────────────────────────┘
                            ↓
        ┌───────────────────┴───────────────────┐
        ↓                                       ↓
┌──────────────────┐    ┌───────────────┐    ┌──────────────────┐
│  PostgreSQL      │    │  Redis        │    │  AWS Bedrock       │
│  Pool: 10+20     │    │  Distributed  │    │  Distributed       │
│  (30 concurrent) │    │  Token Bucket │    │  TokenBucket(Redis)│
└──────────────────┘    │  (global)     │    │  Semaphore: 50     │
                        └───────────────┘    └────────────────────┘
```

---

## Concurrency Capacity Assessment

### Theoretical Maximum Concurrency

#### Single Pod

- Uvicorn concurrent connections: 100
- Database connection pool: 30
- Bedrock concurrency: 50

#### 10 Pods (HPA Maximum)

- Total concurrent connections: 100 × 10 = **1000**
- Total database connections: 30 × 10 = **300**
- Total Bedrock requests: 50 × 10 = **500**

### Actual Bottleneck Analysis

| Resource | Limit | Bottleneck Assessment |
|----------|-------|----------------------|
| **Uvicorn Connections** | 1000 | ✅ Sufficient (usually not a bottleneck) |
| **Database Connections** | 300 | ⚠️ May become bottleneck (depends on query complexity) |
| **Bedrock Concurrency** | 500 | ⚠️ Limited by AWS quotas |
| **Pod CPU/Memory** | 5 cores / 5GB | ⚠️ Bottleneck for compute-intensive tasks |

---

## Timeout Configuration Details

### Configuration Overview

| Layer | Configuration | Timeout | Description |
|-------|--------------|---------|-------------|
| **Bedrock Connect** | `connect_timeout` | 10 seconds | Connection establishment timeout |
| **Bedrock Read** | `read_timeout` | **300 seconds (5 min)** | Per-chunk read timeout (covers thinking model pauses and long prefill) |
| **Uvicorn Keep-Alive** | `timeout_keep_alive` | 120 seconds | Idle connection timeout (doesn't affect requests) |
| **ALB Idle (API)** | `idle_timeout` | **600 seconds (10 min)** | Outer fallback; must exceed read_timeout so Bedrock errors surface first |
| **ALB Idle (Frontend)** | `idle_timeout` | 300 seconds (5 min) | Frontend static resources |
| **Streaming Heartbeat** | `STREAM_HEARTBEAT_INTERVAL` | 15 seconds | Keep connection alive |

---

### 1. Bedrock Client Timeout

#### Configuration Location
`backend/app/services/bedrock.py`

```python
Config(
    region_name=settings.AWS_REGION,
    retries={"max_attempts": 3, "mode": "adaptive"},
    connect_timeout=10,    # Connection timeout: 10 seconds
    read_timeout=300,      # Read timeout: 5 min, covers thinking model pauses
    max_pool_connections=settings.BEDROCK_MAX_CONCURRENT_REQUESTS,
    tcp_keepalive=True,
)
```

#### Description

- **Connection timeout (10 seconds)**: Maximum time to establish TCP connection
- **Read timeout (300 seconds)**: Maximum time to wait between consecutive data chunks on the socket. Applies to both first byte and subsequent streaming chunks. Thinking models (e.g. Claude with extended thinking) may pause for minutes during reasoning before producing output
- ✅ 300 seconds covers thinking model pauses, long prefill latency, and Bedrock queue wait times

---

### 2. Uvicorn Keep-Alive Timeout

#### Configuration Location
- `backend/main.py`
- `backend/app/core/config.py`

```python
UVICORN_TIMEOUT_KEEP_ALIVE = 120  # 120 seconds = 2 minutes
```

#### Important Note

⚠️ **This is NOT a request timeout!**

`timeout_keep_alive` is the **idle connection** keep-alive time:
- If connection has no new requests within 120 seconds, close the connection
- **Does not affect ongoing requests**
- Requests can run for any duration (subject to other timeout limits)

#### Actual Behavior

```python
# Client initiates request
POST /v1/chat/completions

# Uvicorn starts processing request
# ↓ Request can run for any duration (subject to other timeout limits)
# ↓ 30-minute AI generation task
# ↓
# Response completed

# Connection closes after 120 seconds of idle (if no new requests)
```

---

### 3. AWS ALB Idle Timeout

#### Configuration Location
- `k8s/application/ingress-api.yaml` (API backend)
- `k8s/application/ingress-frontend.yaml` (Frontend)

#### API Backend Configuration

```yaml
# API backend ALB configuration
alb.ingress.kubernetes.io/load-balancer-attributes: idle_timeout.timeout_seconds=600
```

**600 seconds = 10 minutes**

#### Frontend Configuration

```yaml
# Frontend ALB configuration
alb.ingress.kubernetes.io/load-balancer-attributes: idle_timeout.timeout_seconds=300
```

**300 seconds = 5 minutes**

#### Description

- ALB idle timeout: If connection has no data transfer within specified time, ALB disconnects
- **Important for streaming responses!**
- ✅ ALB idle timeout (600s) > Bedrock read timeout (300s), ensuring Bedrock errors surface first with meaningful messages instead of a generic 504
- For streaming, heartbeats every 15s keep ALB alive regardless of idle timeout

#### AWS ALB Limits

- Minimum: 1 second
- Maximum: 4000 seconds (approximately 66 minutes)
- Default: 60 seconds

---

### 4. Streaming Response Heartbeat Mechanism

#### Configuration Location
- `backend/app/core/config.py`
- `backend/app/api/v1/endpoints/chat.py`

#### Configuration Parameters

```python
STREAM_HEARTBEAT_INTERVAL = 15  # Send heartbeat every 15 seconds
```

#### Implementation Code

```python
async def stream_chat_completion(...):
    last_heartbeat = time.time()

    async for event in bedrock_client.invoke_stream(model, bedrock_request):
        # Send heartbeat to keep connection alive
        current_time = time.time()
        if current_time - last_heartbeat > settings.STREAM_HEARTBEAT_INTERVAL:
            yield ": heartbeat\n\n"  # SSE comment format
            last_heartbeat = current_time

        # Process actual data
        if event.type == "content_block_delta":
            yield chunk
            last_heartbeat = current_time  # Reset heartbeat timer
```

#### How It Works

```
0s    - Request starts
15s   - Send heartbeat ": heartbeat\n\n"
30s   - Send heartbeat
45s   - Send heartbeat
...
120s  - Send heartbeat (ALB won't disconnect, data is being transferred)
...
End   - Task completes (no total duration limit for streaming)
```

#### ALB Decision Logic

- As long as there is **any data transfer** (including heartbeats), it's not considered idle
- Heartbeat sent every 15 seconds, well within ALB's 600-second timeout
- ✅ Even if task runs for a long time, connection won't be dropped

---

## Timeout Scenario Analysis

### Scenario 1: Streaming Response (Recommended)

```python
# Client sends request
POST /v1/chat/completions
{
  "model": "claude-3-sonnet",
  "messages": [...],
  "stream": true  # Streaming
}

# Timeline:
# 0s      - Request arrives
# 1s      - Start returning first token
# 1-300s  - Continuously return tokens (every few seconds)
# 15s     - Send heartbeat (if no data)
# 30s     - Send heartbeat
# ...
# 300s    - Complete
```

**Conclusion:** ✅ Streaming response can run indefinitely (heartbeat keeps connection alive)

---

### Scenario 2: Non-Streaming Response (Short Task)

```python
# Client sends request
POST /v1/chat/completions
{
  "model": "claude-3-sonnet",
  "messages": [...],
  "stream": false  # Non-streaming
}

# Timeline:
# 0s    - Request arrives
# 0-60s - Bedrock processing (generating complete response)
# 60s   - Return complete response
```

**Conclusion:** ✅ Completes within 60 seconds, no problem

---

### Scenario 3: Non-Streaming Response (Very Long Task)

```python
# Assume a task takes 3 minutes with no intermediate output
# 0s      - Request arrives
# 0-180s  - Bedrock processing (no data transfer)
# 300s    - Bedrock read_timeout triggers, backend returns meaningful error ❌
# (If read_timeout didn't trigger)
# 600s    - ALB idle timeout, disconnects as final fallback ❌
```

**Conclusion:** ❌ Non-streaming tasks exceeding 300 seconds will be terminated by read_timeout. Use streaming for longer tasks.

---

## Timeout Configuration Chain

```
Client
  ↓
AWS ALB (10-minute idle timeout) ✅ Outer fallback, exceeds read_timeout
  ↓
Uvicorn (120-second keep-alive, doesn't affect requests)
  ↓
FastAPI Application (no timeout limit)
  ↓
Bedrock Client (300-second read timeout) ✅ Covers thinking model pauses
  ↓
AWS Bedrock API
```

---

## Performance Optimization Recommendations

### Short-Term Optimization (Immediate Implementation)

#### 1. Recommend Using Streaming Responses

Clearly state in API documentation:

```python
@router.post("/chat/completions")
async def create_chat_completion(...):
    """
    Create a chat completion.

    **Timeout Chain:**
    - Bedrock connect: 10 seconds (TCP connection)
    - Bedrock read: 300 seconds (per-chunk timeout, covers thinking pauses)
    - ALB idle: 600 seconds (outer fallback; heartbeat keeps alive during streaming)

    **Recommendation:** Use streaming for long-running tasks.
    """
```

---

### Mid-Term Optimization (Planned Implementation)

#### 1. Monitor Timeout Situations

Add timeout monitoring and alerts:

```python
if duration > 60:  # More than 60 seconds
    logger.warning("Long-running task detected", extra={
        "duration": duration,
        "model": model,
        "request_id": request_id
    })
```

#### 2. Database Connection Pool Tuning

Adjust connection pool size based on actual load:

```python
# Monitor connection pool usage
# If frequent waiting occurs, increase pool size
DATABASE_POOL_SIZE = 20        # Increase from 10 to 20
DATABASE_MAX_OVERFLOW = 30     # Increase from 20 to 30
```

#### 3. Bedrock Concurrency Limit Tuning

Adjust based on AWS quotas and actual needs:

```python
# Check AWS Bedrock quotas
# Adjust semaphore size
BEDROCK_MAX_CONCURRENT_REQUESTS = 100  # Increase from 50 to 100
```

---

### Long-Term Optimization (Architecture Improvements)

#### 1. Async Task Queue

Use async processing for very long tasks:

```python
# Use Celery or AWS SQS
@app.post("/chat/completions/async")
async def create_async_completion(...):
    # Create task
    task_id = await task_queue.enqueue(...)
    return {"task_id": task_id, "status": "pending"}

@app.get("/chat/completions/{task_id}")
async def get_completion_result(task_id: str):
    # Poll for result
    result = await task_queue.get_result(task_id)
    return result
```

#### 2. Caching Layer

Add Redis caching to reduce database pressure:

```python
# Cache frequently used query results
@cache(ttl=300)  # Cache for 5 minutes
async def get_user_info(user_id: str):
    return await db.query(User).filter_by(id=user_id).first()
```

#### 3. Read-Write Separation

Use PostgreSQL read replicas to distribute query load:

```python
# Write operations use primary
async with write_db() as session:
    await session.execute(insert_query)

# Read operations use replica
async with read_db() as session:
    result = await session.execute(select_query)
```

---

## Configuration File Reference

### Environment Variable Configuration

```bash
# Database connection pool
KBR_DATABASE_POOL_SIZE=10
KBR_DATABASE_MAX_OVERFLOW=20

# Bedrock request control
KBR_BEDROCK_MAX_CONCURRENT_REQUESTS=50
KBR_BEDROCK_ACCOUNT_RPM=500
KBR_BEDROCK_EXPECTED_PODS=3
KBR_BEDROCK_RATE_BURST=10

# Uvicorn server
KBR_UVICORN_TIMEOUT_KEEP_ALIVE=120
KBR_UVICORN_LIMIT_CONCURRENCY=100
KBR_UVICORN_LIMIT_MAX_REQUESTS=10000

# Streaming response heartbeat
KBR_STREAM_HEARTBEAT_INTERVAL=15
```

### Kubernetes Configuration

```yaml
# HPA configuration
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
# Pod resource configuration
resources:
  requests:
    cpu: 100m
    memory: 256Mi
  limits:
    cpu: 500m
    memory: 512Mi
```

---

## Monitoring Metrics

### Key Metrics

1. **Database Connection Pool**
   - Active connections
   - Waiting connections
   - Connection timeout count

2. **Bedrock Concurrency**
   - Current concurrent requests
   - Wait queue length
   - Request latency

3. **Pod Resources**
   - CPU utilization
   - Memory utilization
   - Pod count changes

4. **Request Timeouts**
   - Requests exceeding 300 seconds (read timeout)
   - ALB timeout errors (600 seconds fallback)
   - Average response time

---

## Troubleshooting

### Common Issues

#### 1. 504 Gateway Timeout

**Cause:** Bedrock read timeout (300 seconds) or ALB idle timeout (600 seconds)

**Solutions:**
- Use streaming responses (recommended)
- Check if Bedrock service is healthy
- Verify network connectivity to Bedrock endpoint

#### 2. Database Connection Exhaustion

**Symptoms:** `TimeoutError: QueuePool limit of size 10 overflow 20 reached`

**Solutions:**
- Increase connection pool size
- Check for connection leaks
- Optimize query performance

#### 3. Bedrock Throttling

**Symptoms:** `ThrottlingException: Rate exceeded`

**Solutions:**
- Check AWS quotas
- Adjust semaphore size
- Implement request retry mechanism

---

## Summary

This project implements high-concurrency handling through **multi-layer concurrency control**:

1. ✅ **Application Layer**: Uvicorn limits concurrent connections (100/worker)
2. ✅ **Database Layer**: Connection pool management (10+20 connections)
3. ✅ **External Service Layer**: Distributed Redis token bucket (global rate) + Semaphore (50 concurrent) for Bedrock, with LocalTokenBucket fallback
4. ✅ **Infrastructure Layer**: Kubernetes HPA auto-scaling (1-10 Pods)
5. ✅ **Load Balancing Layer**: AWS ALB with round-robin algorithm (even distribution with global token bucket)
6. ✅ **Timeout Protection**: Heartbeat mechanism maintains long connections
7. ✅ **Cost Optimization**: Prompt cache differentiated pricing (see [Pricing System](./pricing-system.md#prompt-cache-differentiated-pricing))
8. ✅ **Resource Protection**: Client disconnect detection stops Bedrock stream early

---

## Related Documentation

- [Dynamic Pricing System](./pricing-system.md)
- [Security Configuration](./security.md)
- [Deployment Guide](../README.md#deployment)
- [API Documentation](../README.md#api-documentation)

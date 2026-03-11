# Performance and Concurrency Configuration

This document details the optimization measures and timeout configurations for high-concurrency scenarios.

## Table of Contents

- [High Concurrency Handling Strategies](#high-concurrency-handling-strategies)
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

### 2. AWS Bedrock Concurrency Limiting (Semaphore)

#### Configuration Location
- `backend/app/services/bedrock.py`
- `backend/app/core/config.py`

#### Configuration Parameters

```python
BEDROCK_MAX_CONCURRENT_REQUESTS = 50  # Maximum concurrent requests
```

#### Implementation

```python
# Use asyncio.Semaphore to control concurrency
self._semaphore = asyncio.Semaphore(50)

async def invoke(self, model_name: str, request: BedrockRequest):
    async with self._semaphore:  # Acquire semaphore permit
        return await self._invoke_inner(model_name, request)
```

#### How It Works

```
Concurrent requests 1-50  → Execute immediately
Concurrent requests 51+   → Wait for previous requests to complete
```

#### Why Semaphore Is Needed

1. **AWS Bedrock Has Quota Limits**
   - Each account/region has concurrent request limits
   - Exceeding limits results in throttling (429 errors)

2. **Protect Downstream Services**
   - Prevent burst traffic from overwhelming Bedrock
   - Provide smooth backpressure

3. **Special Handling for Streaming Responses**

```python
async def invoke_stream(self, model_name: str, request: BedrockRequest):
    async with self._semaphore:  # Hold semaphore for entire stream duration
        async for event in self._invoke_stream_inner(model_name, request):
            yield event
    # Release semaphore after stream ends
```

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
┌──────────────────┐                  ┌──────────────────┐
│  PostgreSQL      │                  │  AWS Bedrock     │
│  Pool: 10+20     │                  │  Semaphore: 50   │
│  (30 concurrent) │                  │  (50 concurrent) │
└──────────────────┘                  └──────────────────┘
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
| **Bedrock Connect** | `connect_timeout` | 60 seconds | Connection establishment timeout |
| **Bedrock Read** | `read_timeout` | **1800 seconds (30 min)** | Support long AI tasks |
| **Uvicorn Keep-Alive** | `timeout_keep_alive` | 120 seconds | Idle connection timeout (doesn't affect requests) |
| **ALB Idle (API)** | `idle_timeout` | **600 seconds (10 min)** | May become bottleneck |
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
    connect_timeout=60,    # Connection timeout: 60 seconds
    read_timeout=1800,     # Read timeout: 1800 seconds = 30 minutes
    max_pool_connections=settings.BEDROCK_MAX_CONCURRENT_REQUESTS,
    tcp_keepalive=True,
)
```

#### Description

- **Connection timeout (60 seconds)**: Maximum time to establish TCP connection
- **Read timeout (30 minutes)**: Maximum time to wait for response data
- ✅ 30 minutes is sufficient for very long AI generation tasks

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
- ⚠️ 10 minutes < 30 minutes (Bedrock timeout), may become bottleneck

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
600s  - Send heartbeat (ALB won't disconnect, data is being transferred)
...
1800s - Task completes (maximum 30 minutes)
```

#### ALB Decision Logic

- As long as there is **any data transfer** (including heartbeats), it's not considered idle
- Heartbeat sent every 15 seconds, much less than ALB's 600-second timeout
- ✅ Even if task runs for 30 minutes, connection won't be dropped

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

**Conclusion:** ✅ Streaming response can run for 30 minutes (heartbeat keeps connection alive)

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
# Assume a task takes 15 minutes with no intermediate output
# 0s      - Request arrives
# 0-900s  - Bedrock processing (no data transfer)
# 600s    - ALB timeout, disconnects ❌
# 900s    - Bedrock returns result (but connection already closed)
```

**Conclusion:** ❌ More than 10 minutes without data transfer will be disconnected by ALB

---

## Timeout Configuration Chain

```
Client
  ↓
AWS ALB (10-minute idle timeout) ⚠️ May become bottleneck
  ↓
Uvicorn (120-second keep-alive, doesn't affect requests)
  ↓
FastAPI Application (no timeout limit)
  ↓
Bedrock Client (30-minute read timeout) ✅
  ↓
AWS Bedrock API
```

---

## Performance Optimization Recommendations

### Short-Term Optimization (Immediate Implementation)

#### 1. Increase ALB Timeout to 30 Minutes

Modify `k8s/application/ingress-api.yaml`:

```yaml
# Increase from 10 minutes to 30 minutes
alb.ingress.kubernetes.io/load-balancer-attributes: idle_timeout.timeout_seconds=1800
```

**Advantages:**
- ✅ Simple and straightforward
- ✅ Support very long non-streaming tasks
- ✅ Consistent with Bedrock timeout (30 minutes)

**Disadvantages:**
- ⚠️ Occupies ALB connections longer
- ⚠️ May affect connection pool efficiency

---

#### 2. Recommend Using Streaming Responses

Clearly state in API documentation:

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

### Mid-Term Optimization (Planned Implementation)

#### 1. Monitor Timeout Situations

Add timeout monitoring and alerts:

```python
if duration > 600:  # More than 10 minutes
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

# Bedrock concurrency limit
KBR_BEDROCK_MAX_CONCURRENT_REQUESTS=50

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
   - Requests exceeding 10 minutes
   - ALB timeout errors
   - Average response time

---

## Troubleshooting

### Common Issues

#### 1. 504 Gateway Timeout

**Cause:** ALB idle timeout (10 minutes)

**Solutions:**
- Use streaming responses (recommended)
- Increase ALB timeout to 30 minutes
- Optimize task execution time

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
3. ✅ **External Service Layer**: Semaphore limits Bedrock concurrency (50)
4. ✅ **Infrastructure Layer**: Kubernetes HPA auto-scaling (1-10 Pods)
5. ✅ **Load Balancing Layer**: AWS ALB distributes traffic
6. ✅ **Timeout Protection**: Heartbeat mechanism maintains long connections

This is a **standard cloud-native high-concurrency architecture** that can support thousands of concurrent requests.

---

## Related Documentation

- [Security Configuration](./security.md)
- [Deployment Guide](../README.md#deployment)
- [API Documentation](../README.md#api-documentation)

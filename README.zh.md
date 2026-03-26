<p align="center">
  <img src="assets/kbp.png" alt="Kolya BR Proxy" width="180" />
</p>

<h1 align="center">Kolya BR Proxy</h1>

<p align="center">
  <strong>AI 网关 — 提供兼容 OpenAI 和 Anthropic 的 API，后端接入 AWS Bedrock</strong>
</p>

<p align="center">
  <a href="README.md">English</a> &middot;
  <a href="docs/architecture.zh.md">架构</a> &middot;
  <a href="docs/deployment.zh.md">部署</a> &middot;
  <a href="docs/api-reference.zh.md">API 参考</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Vue-3-4FC08D?logo=vuedotjs&logoColor=white" alt="Vue 3" />
  <img src="https://img.shields.io/badge/AWS_Bedrock-FF9900?logo=amazonaws&logoColor=white" alt="AWS Bedrock" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License" />
</p>

---

## 为什么选择 Kolya BR Proxy？

| | |
|---|---|
| **双 API，一个 Key** | 同时支持 OpenAI (`/v1/chat/completions`) 和 Anthropic (`/v1/messages`) 端点。同一个 `sk-ant-api03_` 格式的 Key 可用于 Cursor、Cline、Claude Code、OpenAI SDK。 |
| **最高 90% 成本节省** | Prompt Cache 读取按 0.1 倍计费；Agent 循环仅 2 次请求即可回本，10+ 轮节省约 60%。 |
| **企业级安全** | 三层 CSRF 防御、AWS WAF、SHA256 + AES-128 Token 双重保护、OAuth SSO（Cognito / Entra ID）。 |
| **生产就绪** | 分布式 Redis 限流、HPA 自动扩缩（1-10 Pods）、流式心跳、Karpenter 节点伸缩。 |

---

## 截图预览

<p align="center">
  <img src="assets/dashboard-cache-pricing.png" width="80%" alt="仪表盘" />
</p>

<details>
<summary><strong>更多截图</strong></summary>

| | |
|---|---|
| ![API Keys](assets/api-cache-settings.png) | ![模型管理](assets/models-management.png) |
| ![Playground](assets/playground.png) | ![使用量监控](assets/monitoring.png) |

</details>

---

## 架构

```mermaid
graph LR
    Client["客户端 (Cursor / Claude Code / SDK)"] -->|OpenAI 或 Anthropic API| Backend["后端 (FastAPI)"]
    Frontend["前端 (Vue 3 + Quasar)"] -->|管理 API| Backend
    Backend -->|InvokeModel - Claude| Bedrock["AWS Bedrock"]
    Backend -->|Converse API - Nova / DeepSeek| Bedrock
    Backend -->|asyncpg| DB[(PostgreSQL)]
    Backend -.->|缓存 + 限流| Redis[(Redis)]
    subgraph AWS EKS
        Frontend
        Backend
    end
```

**双 API 路由** — 客户端选择自己偏好的格式：

| 端点 | 认证方式 | 格式 | 客户端 |
|------|---------|------|--------|
| `POST /v1/chat/completions` | `Authorization: Bearer` | OpenAI | Cursor, Cline, OpenAI SDK |
| `POST /v1/messages` | `x-api-key` | Anthropic Messages | Claude Code, Anthropic SDK |
| `GET /v1/models` | 两种均可 | OpenAI | 所有客户端 |

两条路由共享同一个 Bedrock 后端、Token 验证、配额追踪和 Prompt Cache 管线。

---

## 快速开始

### 前提条件

- Python 3.12+、Node.js 18+、PostgreSQL 15+（或 Docker）
- 具有 Bedrock 访问权限的 AWS 凭证
- [uv](https://github.com/astral-sh/uv) 包管理器

### 1. 数据库

```bash
docker run -d --name kbp-postgres \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=kolyabrproxy -p 5432:5432 postgres:15
```

### 2. 后端

```bash
cd backend
uv sync
cp .env.example .env        # 编辑填入你的配置
uv run alembic upgrade head
KBR_ENV=local uv run python main.py
```

后端运行在 `http://localhost:8000`（`KBR_DEBUG=true` 时可访问 `/docs` Swagger UI）。

### 3. 前端

```bash
cd frontend && npm install && npm run dev
```

前端运行在 `http://localhost:9000`。

### 4. 测试

```bash
# OpenAI 兼容格式
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-ant-api03_YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"us.anthropic.claude-sonnet-4-20250514-v1:0","messages":[{"role":"user","content":"Hi"}],"stream":true}'

# Anthropic 兼容格式
curl http://localhost:8000/v1/messages \
  -H "x-api-key: sk-ant-api03_YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"us.anthropic.claude-sonnet-4-20250514-v1:0","max_tokens":1024,"messages":[{"role":"user","content":"Hi"}],"stream":true}'
```

---

## 客户端配置

### Claude Code

```bash
export ANTHROPIC_BASE_URL=https://api.your-domain.com/v1
export ANTHROPIC_API_KEY=sk-ant-api03_YOUR_TOKEN
```

Claude Code 会自动通过 `/v1/models` 发现模型，通过 `/v1/messages` 发送请求。

### Cursor / Cline

| 设置 | 值 |
|------|------|
| Base URL | `https://api.your-domain.com/v1` |
| API Key | `sk-ant-api03_YOUR_TOKEN` |
| Model | `us.anthropic.claude-sonnet-4-20250514-v1:0` |

### OpenAI SDK (Python)

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-ant-api03_YOUR_TOKEN",  # pragma: allowlist secret
    base_url="https://api.your-domain.com/v1",
)

response = client.chat.completions.create(
    model="us.anthropic.claude-sonnet-4-20250514-v1:0",
    messages=[{"role": "user", "content": "Hello!"}],
    stream=True,
)
for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

### Anthropic SDK (Python)

```python
import anthropic

client = anthropic.Anthropic(
    api_key="sk-ant-api03_YOUR_TOKEN",  # pragma: allowlist secret
    base_url="https://api.your-domain.com/v1",
)

message = client.messages.create(
    model="us.anthropic.claude-sonnet-4-20250514-v1:0",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello!"}],
)
print(message.content[0].text)
```

---

## 核心功能

### 双 API 网关
- **OpenAI 兼容** — `/v1/chat/completions`、`/v1/models`
- **Anthropic 兼容** — `/v1/messages`，完整支持 thinking、adaptive 模式、tool use
- 流式和非流式响应，15 秒心跳保持连接活跃
- 多模态（文本 + 图像）、工具调用、扩展思考

### 多厂商支持
- **Anthropic Claude** 使用原生 InvokeModel API（thinking、effort、prompt caching）
- **Amazon Nova、DeepSeek、Mistral、Llama** 通过 Converse API
- 统一转换层支持 19 家厂商

### 成本优化
- **Prompt Cache** — 读取 90% 折扣，自动注入缓存断点（每请求最多 4 个）
- **按模型按 Token 计费** — 动态价格来自 AWS API（181+ 个地区价格记录）
- **实时追踪** — 后台异步记录使用量，每个 API Token 配额限制

### 安全
- API Token：SHA256 哈希索引 O(1) 查询 + Fernet AES-128 加密存储
- OAuth SSO：Cognito（默认）+ Microsoft Entra ID，PKCE + HttpOnly Refresh Cookie
- CSRF：Origin + Referer + 自定义头三重校验
- WAF：按端点层级限流（20/300/2000 req 每 5min），SQLi/XSS 托管规则
- 密钥：External Secrets Operator + AWS Secrets Manager，通过 Pod Identity 自动同步

### 基础设施
- Kubernetes 原生：EKS + Karpenter + Metrics Server
- 两种部署模式：完整 IaC（`deploy-all.sh`）或现有集群（`deploy-to-existing.sh`）
- 可选 Global Accelerator 实现 Anycast 低延迟路由
- 分布式 Redis 令牌桶限流，Redis 不可用时自动回退 per-Pod 模式

---

## 技术栈

| 层级 | 技术 |
|------|------|
| **前端** | Vue 3, Quasar, TypeScript, Pinia, Vite |
| **后端** | Python 3.12+, FastAPI, SQLAlchemy (async), Alembic, Pydantic |
| **数据库** | PostgreSQL（生产环境 Aurora），asyncpg |
| **缓存** | Redis（限流、Token 缓存） |
| **认证** | JWT, AWS Cognito, Microsoft OAuth |
| **云服务** | AWS Bedrock, EKS, ECR, WAF, Secrets Manager |
| **IaC** | Terraform, Karpenter, External Secrets Operator |

---

## 文档

| 文档 | 描述 |
|------|------|
| [架构概览](docs/architecture.zh.md) | 系统架构、组件图、认证流程 |
| [API 参考](docs/api-reference.zh.md) | 完整端点文档及示例 |
| [请求转换](docs/request-translation.zh.md) | OpenAI/Anthropic 到 Bedrock 格式映射 |
| [Prompt 缓存](docs/prompt-caching.zh.md) | 自动注入机制、成本模型、断点策略 |
| [计费系统](docs/pricing-system.zh.md) | 按 Token 计费、动态定价 |
| [安全防护](docs/security.zh.md) | CSRF、WAF、Token 保护、OAuth |
| [性能优化](docs/performance.zh.md) | 流式优化、限流、超时调优、HPA |
| [部署 SOP](docs/deployment.zh.md) | 部署、销毁及运维指南 |
| [OAuth 配置](docs/oauth-setup.zh.md) | Cognito 和 Microsoft OAuth 配置 |

---

## 开发

```bash
# 后端
cd backend
uv run ruff check .     # 代码检查
uv run ruff format .    # 格式化
uv run pytest           # 测试

# 前端
cd frontend
npm run lint            # 代码检查
npm run format          # 格式化
```

---

## 许可

MIT License — 详见 [LICENSE](LICENSE)。

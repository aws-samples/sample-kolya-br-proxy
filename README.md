<p align="center">
  <img src="assets/kbp.png" alt="Kolya BR Proxy" width="180" />
</p>

<h1 align="center">Kolya BR Proxy</h1>

<p align="center">
  <strong>AI Gateway providing OpenAI & Anthropic compatible APIs backed by AWS Bedrock and Google Gemini</strong>
</p>

<p align="center">
  <a href="README.zh.md">中文</a> &middot;
  <a href="docs/architecture.md">Architecture</a> &middot;
  <a href="docs/deployment.md">Deployment</a> &middot;
  <a href="docs/api-reference.md">API Reference</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Vue-3-4FC08D?logo=vuedotjs&logoColor=white" alt="Vue 3" />
  <img src="https://img.shields.io/badge/AWS_Bedrock-FF9900?logo=amazonaws&logoColor=white" alt="AWS Bedrock" />
  <img src="https://img.shields.io/badge/Google_Gemini-4285F4?logo=google&logoColor=white" alt="Google Gemini" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License" />
</p>

---

## Why Kolya BR Proxy?

| | |
|---|---|
| **Dual API, one key** | Both OpenAI (`/v1/chat/completions`) and Anthropic (`/v1/messages`) endpoints. Same `sk-ant-api03_` key works everywhere — Cursor, Cline, Claude Code, OpenAI SDK. |
| **Multi-cloud LLM routing** | AWS Bedrock (Claude, Nova, DeepSeek, Mistral, Llama, 19+ providers) + Google Gemini (native `generateContent` API). One proxy, all models. |
| **Up to 90% cost savings** | Prompt caching reads at 0.1x price. Agent loops save ~60% after just 2 requests. |
| **Enterprise security** | 3-layer CSRF, AWS WAF, SHA256 + AES-128 token protection, OAuth SSO (Cognito / Entra ID). |
| **Production-ready** | Distributed Redis rate limiting, HPA autoscaling (1-10 Pods), streaming heartbeat, Karpenter node scaling. |

---

## Screenshots

<p align="center">
  <img src="assets/dashboard-cache-pricing.png" width="80%" alt="Dashboard" />
</p>

<details>
<summary><strong>More screenshots</strong></summary>

| | |
|---|---|
| ![API Keys](assets/api-cache-settings.png) | ![Models](assets/models-management.png) |
| ![Playground](assets/playground.png) | ![Monitoring](assets/monitoring.png) |

</details>

---

## Architecture

```mermaid
graph LR
    Client["Client (Cursor / Claude Code / SDK)"] -->|OpenAI or Anthropic API| Backend["Backend (FastAPI)"]
    Frontend["Frontend (Vue 3 + Quasar)"] -->|Admin API| Backend
    Backend -->|InvokeModel - Claude| Bedrock["AWS Bedrock"]
    Backend -->|Converse API - Nova / DeepSeek / Llama| Bedrock
    Backend -->|generateContent native API| Gemini["Google Gemini"]
    Backend -->|asyncpg| DB[(PostgreSQL)]
    Backend -.->|Cache + Rate Limit| Redis[(Redis)]
    subgraph AWS EKS
        Frontend
        Backend
    end
```

**Dual API routing** — Clients choose their preferred format:

| Endpoint | Auth | Format | Clients |
|----------|------|--------|---------|
| `POST /v1/chat/completions` | `Authorization: Bearer` | OpenAI | Cursor, Cline, OpenAI SDK |
| `POST /v1/messages` | `x-api-key` | Anthropic Messages | Claude Code, Anthropic SDK |
| `GET /v1/models` | Both | OpenAI | All clients |

Model routing is automatic — `gemini-*` models go to Google Gemini via the native `generateContent` API; all other models go to AWS Bedrock. Both routes share the same token validation, quota tracking, and usage recording pipeline.

---

## Quick Start

### Prerequisites

- Python 3.12+, Node.js 18+, PostgreSQL 15+ (or Docker)
- AWS credentials with Bedrock access
- [uv](https://github.com/astral-sh/uv) package manager

### 1. Database

```bash
docker run -d --name kbp-postgres \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=kolyabrproxy -p 5432:5432 postgres:15
```

### 2. Backend

```bash
cd backend
uv sync
cp .env.example .env        # edit with your values
uv run alembic upgrade head
KBR_ENV=local uv run python main.py
```

Backend runs at `http://localhost:8000` (Swagger UI at `/docs` when `KBR_DEBUG=true`).

### 3. Frontend

```bash
cd frontend && npm install && npm run dev
```

Frontend runs at `http://localhost:9000`.

### 4. Test

```bash
# OpenAI-compatible
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-ant-api03_YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"us.anthropic.claude-sonnet-4-20250514-v1:0","messages":[{"role":"user","content":"Hi"}],"stream":true}'

# Anthropic-compatible
curl http://localhost:8000/v1/messages \
  -H "x-api-key: sk-ant-api03_YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"us.anthropic.claude-sonnet-4-20250514-v1:0","max_tokens":1024,"messages":[{"role":"user","content":"Hi"}],"stream":true}'
```

---

## Client Configuration

### Claude Code

```bash
export ANTHROPIC_BASE_URL=https://api.your-domain.com/v1
export ANTHROPIC_API_KEY=sk-ant-api03_YOUR_TOKEN
```

Claude Code will auto-discover models via `/v1/models` and send requests to `/v1/messages`.

### Cursor / Cline

| Setting | Value |
|---------|-------|
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

## Key Features

### Dual API Gateway
- **OpenAI compatible** — `/v1/chat/completions`, `/v1/models`
- **Anthropic compatible** — `/v1/messages` with full thinking, adaptive mode, tool use support
- Streaming and non-streaming with 15s heartbeat keep-alive
- Multi-modal (text + images), tool calling, extended thinking

### Multi-Provider Support
- **Anthropic Claude** via native InvokeModel API (thinking, effort, prompt caching)
- **Amazon Nova, DeepSeek, Mistral, Llama** via Converse API
- **Google Gemini** via native `generateContent` / `streamGenerateContent` API (image generation 🍌, tool calling, implicit caching)
- 19+ providers through unified translation layer

### Cost Optimization
- **Prompt caching** — 90% discount on reads, auto-injection of cache breakpoints (up to 4 per request)
- **Per-token billing** — Dynamic pricing from AWS API (181+ regional pricing records) + Gemini 3-tier pricing (Google official page → LiteLLM JSON → static legacy table)
- **Real-time tracking** — Background async usage recording with per-token quota limits

### Security
- API tokens: SHA256 hash index for O(1) lookup + Fernet AES-128 encrypted storage
- OAuth SSO: Cognito (default) + Microsoft Entra ID, PKCE + HttpOnly refresh cookies
- CSRF: Origin + Referer + custom header triple validation
- WAF: Rate limiting (20/300/2000 req per 5min by tier), SQLi/XSS managed rules
- Secrets: External Secrets Operator + AWS Secrets Manager, auto-sync via Pod Identity

### Infrastructure
- Kubernetes-native: EKS + Karpenter + Metrics Server
- Two deployment modes: full IaC (`deploy-all.sh`) or existing cluster (`deploy-to-existing.sh`)
- Optional Global Accelerator for Anycast low-latency routing
- Distributed Redis token bucket rate limiting with per-Pod fallback

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Vue 3, Quasar, TypeScript, Pinia, Vite |
| **Backend** | Python 3.12+, FastAPI, SQLAlchemy (async), Alembic, Pydantic |
| **Database** | PostgreSQL (Aurora in prod), asyncpg |
| **Cache** | Redis (rate limiting, token caching) |
| **Auth** | JWT, AWS Cognito, Microsoft OAuth |
| **Cloud** | AWS Bedrock, EKS, ECR, WAF, Secrets Manager, Google Gemini API |
| **IaC** | Terraform, Karpenter, External Secrets Operator |

---

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/architecture.md) | System overview, component diagrams, auth flows |
| [API Reference](docs/api-reference.md) | Full endpoint docs with examples |
| [Request Translation](docs/request-translation.md) | OpenAI/Anthropic to Bedrock format mapping |
| [Prompt Caching](docs/prompt-caching.md) | Auto-injection, cost model, breakpoint strategy |
| [Pricing System](docs/pricing-system.md) | Per-token billing, dynamic pricing |
| [Security](docs/security.md) | CSRF, WAF, token protection, OAuth |
| [Performance](docs/performance.md) | Streaming, rate limiting, timeout tuning, HPA |
| [Deployment SOP](docs/deployment.md) | Deploy, teardown, and operations |
| [OAuth Setup](docs/oauth-setup.md) | Cognito & Microsoft OAuth configuration |

---

## Development

```bash
# Backend
cd backend
uv run ruff check .     # lint
uv run ruff format .    # format
uv run pytest           # test

# Frontend
cd frontend
npm run lint            # lint
npm run format          # format
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.

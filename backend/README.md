# Kolya BR Proxy -- Backend

FastAPI-based OpenAI-compatible API gateway that proxies requests to AWS Bedrock models (Claude, Nova, DeepSeek, Mistral, Llama, etc.).

## Tech Stack

- **Framework**: FastAPI (Python 3.12+)
- **Database**: PostgreSQL with SQLAlchemy (async)
- **Authentication**: JWT + Microsoft OAuth + AWS Cognito OAuth
- **AWS Services**: Bedrock (InvokeModel API for Anthropic models, Converse API for others)
- **Package Manager**: uv

## Quick Start

```bash
# Install dependencies
uv sync

# Configure environment (copy and edit)
cp .env.example .env

# Run database migrations
uv run alembic upgrade head

# Start development server
uv run uvicorn main:app --reload --port 8000
```

Visit `http://localhost:8000/docs` for interactive Swagger UI (debug mode only).

## Project Structure

```
app/
├── api/
│   ├── v1/endpoints/      # Gateway API (OpenAI-compatible)
│   │   ├── chat.py        #   POST /v1/chat/completions
│   │   └── models.py      #   GET  /v1/models
│   ├── admin/endpoints/   # Admin API (JWT auth)
│   │   ├── auth.py        #   Login, OAuth, refresh, profile
│   │   ├── tokens.py      #   API token CRUD
│   │   ├── models.py      #   Model management
│   │   ├── usage.py       #   Usage statistics
│   │   └── audit.py       #   Audit logs
│   ├── health.py          # Health probes
│   └── deps.py            # Dependency injection
├── core/                  # Config, database, security
├── models/                # SQLAlchemy models
├── schemas/               # Pydantic schemas (OpenAI + Bedrock)
├── services/              # Business logic
└── middleware/             # Security middleware
```

## Documentation

- **[Request Translation](../docs/request-translation.md)** -- how requests are translated between OpenAI, Bedrock, and Anthropic formats
- **[API Reference](../docs/api-reference.md)** -- full endpoint documentation with request/response examples
- **[Architecture](../docs/architecture.md)** -- system design, data flow, component overview
- **[OAuth Setup](../docs/oauth-setup.md)** -- Microsoft and Cognito OAuth configuration
- **[Deployment](../docs/deployment.md)** -- production and non-production deployment guide

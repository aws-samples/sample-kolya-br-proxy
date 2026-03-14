# Architecture

Comprehensive architecture documentation for Kolya BR Proxy -- an AI Gateway that provides OpenAI-compatible API access to AWS Bedrock models (Claude, Nova, DeepSeek, Mistral, Llama, etc.).

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [Backend Layer Architecture](#2-backend-layer-architecture)
3. [Database ER Diagram](#3-database-er-diagram)
4. [Frontend Architecture](#4-frontend-architecture)
5. [Infrastructure Architecture](#5-infrastructure-architecture)
6. [Authentication Flow](#6-authentication-flow)
7. [Request Processing Flow](#7-request-processing-flow)
8. [Pricing Model](#8-pricing-model)

---

## 1. System Architecture Overview

The system follows a classic three-tier architecture: a Vue 3 frontend served by Nginx, a FastAPI backend running on Uvicorn, and AWS Bedrock as the upstream LLM provider. All components run inside an AWS EKS cluster with PostgreSQL for persistence, Redis for distributed rate limiting, and External Secrets Operator (ESO) for secrets management.

```mermaid
graph LR
    subgraph Clients ["Client Applications"]
        OAI["OpenAI SDK / Client Libraries"]
        Browser["Admin Dashboard<br/>(Browser)"]
    end

    subgraph AWS_EKS ["AWS EKS Cluster"]
        subgraph Frontend_Pod ["Frontend Pod"]
            Nginx["Nginx"]
            Vue["Vue 3 / Quasar SPA"]
        end

        subgraph Backend_Pod ["Backend Pod"]
            Uvicorn["Uvicorn ASGI Server"]
            FastAPI["FastAPI Application"]
        end

        ALB["Application Load<br/>Balancer (ALB)"]
    end

    subgraph Data_Stores ["Data Stores"]
        PG["Aurora PostgreSQL"]
        Redis["Redis Standalone<br/>(distributed rate limiting)"]
    end

    subgraph AWS_Services ["AWS Services"]
        Bedrock["AWS Bedrock<br/>(Claude, Nova, DeepSeek,<br/>Mistral, Llama)"]
    end

    OAI -->|"HTTPS /v1/*"| ALB
    Browser -->|"HTTPS /*"| ALB
    ALB -->|"Frontend routes"| Nginx
    ALB -->|"API routes"| Uvicorn
    Nginx --> Vue
    Uvicorn --> FastAPI
    FastAPI -->|"InvokeModel /<br/>Converse API"| Bedrock
    FastAPI -->|"SQLAlchemy async"| PG
    FastAPI -.->|"Distributed rate limiting"| Redis
```

### Key Design Decisions

| Decision | Rationale |
|---|---|
| OpenAI-compatible API | Drop-in replacement; clients only change `base_url` and `api_key` |
| Singleton `BedrockClient` | One shared aioboto3 session + connection pool per process |
| Asyncio semaphore (50) | Back-pressure to match connection pool size; prevents request queuing |
| JWT for dashboard, API keys for gateway | Separate auth concerns; API keys are long-lived, JWTs are short-lived |
| Background usage recording | `record_usage` runs as a background task to avoid blocking responses |

---

## 2. Backend Layer Architecture

The backend is organized into four layers: API (routing + validation), Middleware (security + CORS), Service (business logic), and Data (SQLAlchemy models). The entry point is `backend/main.py` which sets up the FastAPI app via the `create_app()` factory and the `lifespan` context manager.

```mermaid
graph TD
    subgraph API_Layer ["API Layer (Routers)"]
        Health["/health<br/>health_router"]
        Admin["/admin<br/>admin_router"]
        V1["/v1<br/>gateway_router"]

        subgraph Admin_Sub ["Admin Endpoints"]
            Auth_EP["/admin/auth<br/>OAuth (Cognito, Microsoft), refresh"]
            Tokens_EP["/admin/tokens<br/>CRUD API keys"]
            Usage_EP["/admin/usage<br/>usage statistics"]
            Audit_EP["/admin/audit-logs<br/>audit log queries"]
            Models_EP["/admin/models<br/>model management"]
        end

        subgraph V1_Sub ["Gateway Endpoints (OpenAI-compatible)"]
            Chat_EP["/v1/chat/completions<br/>streaming + non-streaming"]
            Models_List["/v1/models<br/>list available models"]
        end

        Admin --> Admin_Sub
        V1 --> V1_Sub
    end

    subgraph Middleware_Layer ["Middleware Layer"]
        direction LR
        Cache_MW["Cache-Control<br/>Middleware"]
        Security_MW["SecurityMiddleware<br/>(CSRF, origin, headers)"]
        CORS_MW["CORSMiddleware<br/>(FastAPI built-in)"]
    end

    subgraph Service_Layer ["Service Layer"]
        BedrockSvc["BedrockClient<br/>(singleton, semaphore=50)"]
        ReqTranslator["RequestTranslator<br/>(OpenAI -> Bedrock)"]
        ResTranslator["ResponseTranslator<br/>(Bedrock -> OpenAI)"]
        TokenSvc["TokenService<br/>(validate, CRUD)"]
        AuthSvc["AuthService<br/>(OAuth user creation)"]
        RefreshSvc["RefreshTokenService<br/>(token rotation)"]
        AuditSvc["AuditLogService<br/>(security events)"]
        PricingSvc["ModelPricing<br/>(cost calculation)"]
        BGTasks["BackgroundTaskManager<br/>(usage recording)"]
        OAuthSvc["MicrosoftOAuth /<br/>CognitoOAuth"]
    end

    subgraph Data_Layer ["Data Layer (SQLAlchemy Async Models)"]
        UserModel["User"]
        APITokenModel["APIToken"]
        ModelModel["Model"]
        UsageModel["UsageRecord"]
        AuditModel["AuditLog"]
        RefreshModel["RefreshToken"]
        OAuthModel["OAuthState"]
        SysConfig["SystemConfig"]
    end

    API_Layer --> Middleware_Layer
    Middleware_Layer --> Service_Layer
    Service_Layer --> Data_Layer
```

### Middleware Stack Order

Middleware is registered in `create_app()` in `backend/main.py`. FastAPI processes middleware in reverse registration order (last added = outermost). The effective processing order for an incoming request is:

1. **Cache-Control** -- adds `no-cache, no-store` headers to every response
2. **SecurityMiddleware** -- origin validation, CSRF protection (`X-Requested-With`), security response headers (`X-Content-Type-Options`, `X-Frame-Options`, CSP)
3. **CORSMiddleware** -- handles `OPTIONS` preflight, sets `Access-Control-*` headers

### Lifespan Events

```python
# backend/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()                   # Initialize database connection pool
    BedrockClient.get_instance()      # Create singleton Bedrock client
    yield
    # Shutdown: cleanup resources
```

---

## 3. Database ER Diagram

All models use UUID primary keys and are defined in `backend/app/models/`. Relationships are enforced via SQLAlchemy ORM with cascade deletes where appropriate.

```mermaid
erDiagram
    User ||--o{ APIToken : "owns"
    User ||--o{ UsageRecord : "generates"
    User ||--o{ RefreshToken : "has"
    User ||--o{ AuditLog : "triggers"
    APIToken ||--o{ UsageRecord : "tracks"
    APIToken ||--o{ Model : "enables"
    RefreshToken ||--o{ RefreshToken : "parent-child"

    User {
        uuid id PK
        string email UK
        string password_hash "nullable (unused, OAuth-only)"
        enum auth_method "MICROSOFT | COGNITO"
        boolean is_active
        boolean is_admin
        boolean email_verified
        decimal current_balance "Numeric(10,2)"
        string microsoft_id UK "nullable"
        string first_name
        string last_name
        datetime created_at
        datetime updated_at
        datetime last_login_at
    }

    APIToken {
        uuid id PK
        uuid user_id FK
        string name
        string token_hash UK "SHA256"
        string encrypted_token "Fernet AES-128"
        datetime expires_at "nullable"
        decimal quota_usd "Numeric(10,2) nullable"
        string_array allowed_ips "nullable"
        boolean is_active
        boolean is_deleted
        json token_metadata
        datetime created_at
        datetime updated_at
        datetime last_used_at
        datetime deleted_at
    }

    Model {
        uuid id PK
        uuid token_id FK "CASCADE"
        string model_name
        boolean is_active
        boolean is_deleted
        datetime created_at
        datetime updated_at
        datetime deleted_at
    }

    UsageRecord {
        uuid id PK
        uuid user_id FK
        uuid token_id FK
        string request_id
        string model
        int prompt_tokens
        int completion_tokens
        int total_tokens
        int cache_creation_input_tokens "Cache write tokens"
        int cache_read_input_tokens "Cache read tokens"
        decimal cost_usd "Numeric(10,4)"
        json request_metadata
        datetime created_at
    }

    AuditLog {
        uuid id PK
        uuid user_id FK "nullable, SET NULL"
        enum action "LOGIN_SUCCESS, TOKEN_CREATED, etc."
        boolean success
        text details "JSON string"
        string error_message
        string ip_address
        string user_agent
        string resource_type
        string resource_id
        datetime created_at
    }

    RefreshToken {
        uuid id PK
        uuid user_id FK "CASCADE"
        string token_hash UK "SHA256"
        uuid family_id "for theft detection"
        uuid parent_token_id FK "self-ref, SET NULL"
        datetime created_at
        datetime expires_at
        boolean is_revoked
        datetime revoked_at
        string revoked_reason
        string ip_address
        string user_agent
    }

    OAuthState {
        uuid id PK
        string state UK
        string provider "microsoft | cognito"
        datetime created_at
        datetime expires_at "10 min TTL"
    }

    SystemConfig {
        uuid id PK
        string key UK
        text value
        text description
        boolean is_public
        datetime created_at
        datetime updated_at
    }
```

### Key Model Notes

- **User.auth_method**: Enum with values `MICROSOFT`, `COGNITO`. All users authenticate via OAuth and have `password_hash = NULL`.
- **APIToken**: Stores both `token_hash` (SHA256, for lookup) and `encrypted_token` (Fernet AES, for recovery). The `quota_usd` field limits total spending per token. Model access is controlled via the related `Model` table rather than an array column.
- **Model**: Each row links one Bedrock model name to one APIToken. A token can access only models with `is_active=True` and `is_deleted=False`.
- **RefreshToken.family_id**: Groups related tokens for theft detection. If a revoked token is reused, the entire family is revoked.

---

## 4. Frontend Architecture

The frontend is a Vue 3 SPA built with the Quasar framework (dark theme). It uses Pinia stores for state management, Vue Router for navigation with authentication guards, and Axios with automatic 401 refresh interceptors.

```mermaid
graph TD
    subgraph Pages ["Pages (src/pages/)"]
        Login["LoginPage"]
        CognitoCallback["CognitoCallbackPage"]
        MSCallback["MicrosoftCallbackPage"]
        Dashboard["DashboardPage"]
        Tokens["TokensPage"]
        Models["ModelsPage"]
        Playground["PlaygroundPage"]
        Monitor["MonitorPage"]
        Settings["SettingsPage"]
        NotFound["ErrorNotFound"]
    end

    subgraph Layout ["Layout"]
        MainLayout["MainLayout.vue<br/>(sidebar nav, user menu,<br/>dark theme shell)"]
    end

    subgraph Stores ["Pinia Stores (src/stores/)"]
        AuthStore["auth.ts<br/>OAuth redirect, logout, JWT mgmt"]
        TokenStore["tokens.ts<br/>API key CRUD"]
        ModelStore["models.ts<br/>model management"]
        DashStore["dashboard.ts<br/>usage overview stats"]
        MonitorStore["monitor.ts<br/>usage charts & analytics"]
    end

    subgraph Boot ["Boot (src/boot/)"]
        Axios["axios.ts<br/>API client, 401 interceptor,<br/>auto token refresh"]
    end

    subgraph Router ["Router"]
        Routes["routes.ts<br/>requiresAuth guards"]
    end

    Router -->|"requiresAuth: true"| MainLayout
    Router -->|"requiresAuth: false"| Login
    Router -->|"requiresAuth: false"| CognitoCallback
    Router -->|"requiresAuth: false"| MSCallback

    MainLayout --> Dashboard
    MainLayout --> Tokens
    MainLayout --> Models
    MainLayout --> Playground
    MainLayout --> Monitor
    MainLayout --> Settings

    Pages --> Stores
    Stores --> Boot
    Boot -->|"HTTP requests to /admin/*"| Backend["Backend API"]
```

### Route Structure

| Path | Page | Auth Required | Description |
|---|---|---|---|
| `/login` | LoginPage | No | User login (OAuth provider selection) |
| `/auth/cognito/callback` | CognitoCallbackPage | No | Cognito OAuth callback |
| `/auth/microsoft/callback` | MicrosoftCallbackPage | No | Microsoft OAuth callback |
| `/` | DashboardPage | Yes | Overview, usage stats |
| `/tokens` | TokensPage | Yes | API key management |
| `/models` | ModelsPage | Yes | Model configuration |
| `/playground` | PlaygroundPage | Yes | Test conversations |
| `/monitor` | MonitorPage | Yes | Usage charts & analytics |
| `/settings` | SettingsPage | Yes | Account settings |

### Sidebar Navigation

The `MainLayout.vue` renders a persistent left drawer with these menu items: Dashboard, API Keys, Models, Playground, Monitor, Settings. The header shows the app title and a user menu (email, balance, settings, logout).

---

## 5. Infrastructure Architecture

Infrastructure is defined in Terraform (`iac-612674025488-us-west-2/`). It provisions a VPC, EKS cluster with Karpenter autoscaling, Aurora PostgreSQL, Redis for distributed rate limiting, and optional Global Accelerator. Secrets are managed via AWS Secrets Manager with External Secrets Operator (ESO) syncing them into Kubernetes.

```mermaid
graph TD
    subgraph AWS_Region ["AWS Region (us-west-2)"]
        subgraph VPC ["VPC Module"]
            subgraph Public_Subnets ["Public Subnets"]
                ALB["Application Load<br/>Balancer (ALB)<br/>(dynamically created)"]
                NAT["NAT Gateway"]
            end

            subgraph Private_Subnets ["Private Subnets"]
                subgraph EKS ["EKS Cluster (eks_karpenter module)"]
                    Karpenter["Karpenter<br/>Node Autoscaler"]
                    LBC["AWS Load Balancer<br/>Controller"]
                    FrontendPod["Frontend Pod<br/>(Vue3/Quasar + Nginx)"]
                    BackendPod["Backend Pod<br/>(FastAPI + Uvicorn)"]
                end
                Aurora["Aurora PostgreSQL<br/>(RDS Module)<br/>(private, no external access)"]
                Redis_Pod["Redis Standalone<br/>(kbp namespace)"]
                ESO["External Secrets<br/>Operator (ESO)"]
            end
        end

        ECR["ECR<br/>(Container Registry)"]
        Bedrock["AWS Bedrock"]
        SecretsManager["AWS Secrets Manager"]
        GA["Global Accelerator<br/>(optional)"]
    end

    Internet["Internet"] -->|"HTTPS"| GA
    GA --> ALB
    Internet -->|"HTTPS (direct)"| ALB
    ALB --> FrontendPod
    ALB --> BackendPod
    BackendPod -->|"Via NAT"| Bedrock
    BackendPod --> Aurora
    BackendPod -.->|"Rate limiting"| Redis_Pod
    ESO -->|"Sync secrets<br/>(refreshInterval: 1h)"| SecretsManager
    Karpenter --> Private_Subnets
    LBC -.->|"Creates & manages"| ALB
    ECR -.->|"Pull images"| EKS
```

### Secrets Management (ESO + AWS Secrets Manager)

Secrets are stored in **AWS Secrets Manager** and automatically synced to Kubernetes Secrets by the **External Secrets Operator (ESO)**. This replaces local `secrets.yaml` files and ensures secrets never exist in version control.

| Component | Role |
|---|---|
| AWS Secrets Manager | Single source of truth for all secrets (DB credentials, JWT keys, OAuth client secrets, etc.) |
| External Secrets Operator (ESO) | Runs in-cluster, watches `ExternalSecret` CRDs, and syncs secrets from AWS Secrets Manager to K8s Secrets |
| Pod Identity | ESO authenticates to AWS Secrets Manager via EKS Pod Identity (no static AWS credentials) |
| `deploy-all.sh` | Pushes secrets to AWS Secrets Manager via `aws secretsmanager put-secret-value` during deployment |

**Sync behavior:**
- `refreshInterval: 1h` -- ESO re-fetches secrets from Secrets Manager every hour
- Secrets are created as standard Kubernetes Secrets, consumed by Pods via `envFrom` or `env` references
- Secret rotation in AWS Secrets Manager is automatically picked up within the refresh interval

### Redis for Distributed Rate Limiting

A **Redis standalone** instance runs in the `kbp` (kolya-br-proxy) namespace to provide distributed rate limiting across all backend Pods.

| Aspect | Details |
|---|---|
| Deployment | Redis standalone in `kbp` namespace (Kubernetes Deployment + Service) |
| Purpose | Global token bucket rate limiting via atomic Lua scripts |
| Fallback | If Redis is unavailable, each Pod falls back to a local in-memory `LocalTokenBucket` (per-Pod rate limiting, not skip) |
| Access | Backend Pods connect via Kubernetes Service DNS (`redis.kbp.svc.cluster.local`) |

### Terraform Modules

| Module | Source Path | Purpose |
|---|---|---|
| `vpc` | `./modules/vpc` | VPC with public/private subnets, IGW, NAT, security groups |
| `rds_aurora_postgresql` | `./modules/rds-aurora-postgresql` | Aurora PostgreSQL with encryption, backups, monitoring |
| `eks_karpenter` | `./modules/eks-karpenter` | EKS cluster + Karpenter for node autoscaling |
| `eks_addons` | `./modules/eks-addons` | Karpenter Helm chart, AWS LB Controller |
| `global_accelerator` | `./modules/global-accelerator` | Optional GA for global edge routing |

### Environment Differences

| Setting | Production | Non-Production |
|---|---|---|
| `deletion_protection` | `true` | `false` |
| `backup_retention_period` | 7 days | 1 day |
| `performance_insights` | Enabled | Disabled |
| `monitoring_interval` | 60s | 0 (disabled) |
| `skip_final_snapshot` | `false` | `true` |
| `apply_immediately` | `false` | `true` |
| `flow_logs` (GA) | Enabled | Disabled |

---

## 6. Authentication Flow

The system supports two OAuth authentication methods: **AWS Cognito** (default) and **Microsoft Entra ID**. There is no local username/password authentication. The admin dashboard uses JWT (access + refresh tokens), while the OpenAI-compatible gateway uses API keys (`kbr_` prefix).

### 6.1 OAuth Flow (Cognito / Microsoft)

```mermaid
sequenceDiagram
    participant User as User (Browser)
    participant FE as Frontend
    participant BE as Backend
    participant IdP as Identity Provider<br/>(Microsoft / Cognito)
    participant DB as PostgreSQL

    User->>FE: Click "Sign in with Microsoft"
    FE->>BE: GET /admin/auth/microsoft/authorize?redirect_uri=...
    BE->>DB: Store OAuthState (state token, 10 min TTL)
    BE-->>FE: {authorization_url, state}
    FE->>IdP: Redirect to authorization_url

    User->>IdP: Authenticate + consent
    IdP-->>FE: Redirect to /auth/microsoft/callback?code=...&state=...
    FE->>BE: POST /admin/auth/microsoft/callback {code, state, redirect_uri}
    BE->>DB: Verify OAuthState (CSRF check)
    BE->>IdP: Exchange code for tokens
    IdP-->>BE: {access_token, id_token}
    BE->>IdP: Fetch user profile (MS Graph / Cognito userInfo)
    IdP-->>BE: {email, name, sub}
    BE->>DB: Find or create User (auth_method=MICROSOFT)
    BE->>DB: Create RefreshToken + AuditLog
    BE-->>FE: {access_token, refresh_token, user}
    FE->>FE: Store tokens, redirect to dashboard
```

### 6.2 API Key Authentication (Gateway)

```mermaid
sequenceDiagram
    participant Client as OpenAI Client
    participant BE as Backend (FastAPI)
    participant Redis as Redis (optional)
    participant DB as PostgreSQL

    Client->>BE: POST /v1/chat/completions<br/>Authorization: Bearer kbr_xxx...
    BE->>BE: Extract token from Bearer header

    alt Redis available
        BE->>Redis: Check token cache (SHA256 hash)
        Redis-->>BE: Cache hit / miss
    end

    alt Cache miss or Redis unavailable
        BE->>DB: SELECT * FROM api_tokens<br/>WHERE token_hash = SHA256(kbr_xxx)
        DB-->>BE: APIToken record
    end

    BE->>BE: Check is_active, is_expired
    BE->>DB: SUM(cost_usd) for token
    BE->>BE: Check quota_usd >= total_used
    BE-->>Client: Token validated (or 401/429 error)
```

### Token Comparison

| Property | JWT Access Token | JWT Refresh Token | API Key (`kbr_`) |
|---|---|---|---|
| Lifetime | 30 minutes | 7 days | Until expiry or revocation |
| Used by | Admin dashboard | Admin dashboard (refresh) | OpenAI-compatible clients |
| Storage | localStorage | localStorage | Client configuration |
| Validation | JWT decode + signature | DB lookup (hash + family) | DB lookup (SHA256 hash) |
| Rotation | On refresh | On each use (new token issued) | Manual |

---

## 7. Request Processing Flow

This section details the full lifecycle of a `/v1/chat/completions` request, from token validation through Bedrock invocation to usage recording.

### 7.1 Sequence Diagram

```mermaid
sequenceDiagram
    participant Client as OpenAI Client
    participant MW as Middleware Stack
    participant Chat as chat.py endpoint
    participant Deps as deps.py (DI)
    participant TokenSvc as TokenService
    participant DB as PostgreSQL
    participant Translator as RequestTranslator /<br/>ResponseTranslator
    participant Bedrock as BedrockClient<br/>(semaphore=50)
    participant AWS as AWS Bedrock API
    participant Pricing as ModelPricing
    participant BG as BackgroundTaskManager

    Client->>MW: POST /v1/chat/completions<br/>Authorization: Bearer kbr_xxx
    MW->>MW: SecurityMiddleware: origin + CSRF check
    MW->>MW: CORS headers
    MW->>Chat: Route to handler

    Chat->>Deps: Depends(get_current_token)
    Deps->>TokenSvc: validate_token(kbr_xxx)
    TokenSvc->>DB: SELECT by token_hash
    DB-->>TokenSvc: APIToken
    TokenSvc-->>Chat: Validated APIToken

    Chat->>DB: SUM(cost_usd) WHERE token_id = ?
    DB-->>Chat: total_used
    Chat->>Chat: Check quota: total_used < quota_usd
    Note over Chat: 429 if quota exceeded

    Chat->>DB: SELECT models WHERE token_id = ?<br/>AND is_active AND NOT is_deleted
    DB-->>Chat: Allowed model names
    Chat->>Chat: Check request.model in allowed_models
    Note over Chat: 403 if model not allowed

    Chat->>Translator: RequestTranslator.openai_to_bedrock(request)
    Translator-->>Chat: BedrockRequest

    alt Streaming (stream=true)
        Chat->>Bedrock: invoke_stream(model, request)
        Note over Bedrock: Acquire semaphore (50 max)
        alt Anthropic model
            Bedrock->>AWS: invoke_model_with_response_stream(body)
            loop Stream events
                AWS-->>Bedrock: Anthropic SSE event (JSON)
                Bedrock->>Bedrock: _anthropic_event_to_bedrock()
            end
        else Non-Anthropic model (Nova, DeepSeek, etc.)
            Bedrock->>AWS: converse_stream(params)
            loop Stream events
                AWS-->>Bedrock: Converse stream event
                Bedrock->>Bedrock: _converse_stream_event_to_bedrock()
            end
        end
        Bedrock-->>Chat: BedrockStreamEvent
        Chat->>Translator: create_stream_chunk(...)
        Translator-->>Chat: SSE formatted chunk
        Chat-->>Client: data: {...}\n\n
        Chat-->>Client: data: [DONE]\n\n
        Note over Bedrock: Release semaphore
    else Non-streaming
        Chat->>Bedrock: invoke(model, request)
        Note over Bedrock: Acquire semaphore
        alt Anthropic model
            Bedrock->>AWS: invoke_model(body)
            AWS-->>Bedrock: Anthropic Messages API JSON
        else Non-Anthropic model (Nova, DeepSeek, etc.)
            Bedrock->>AWS: converse(params)
            AWS-->>Bedrock: Converse API JSON
        end
        Note over Bedrock: Release semaphore
        Bedrock-->>Chat: BedrockResponse
        Chat->>Translator: bedrock_to_openai(response)
        Translator-->>Chat: ChatCompletionResponse
        Chat-->>Client: JSON response
    end

    Chat->>BG: background: record_usage(...)
    BG->>Pricing: calculate_cost(model, tokens)
    Pricing-->>BG: cost_usd
    BG->>DB: INSERT INTO usage_records
```

### 7.2 Request/Response Translation

The proxy performs a three-phase translation: OpenAI format → internal `BedrockRequest` → Bedrock API call, and the reverse for responses. For Anthropic models, the request is sent as an Anthropic Messages API body via `invoke_model`. For non-Anthropic models (Nova, DeepSeek, Mistral, Llama, etc.), the request is converted to Converse API format via `converse`/`converse_stream`. This includes message conversion, tool call mapping, parameter translation, Bedrock extension pass-through, and automatic fixes (effort wrapping, max_tokens adjustment).

For the complete translation pipeline documentation, see **[Request Translation](request-translation.md)**.

---

## 8. Pricing Model

Cost is calculated per request based on actual AWS Bedrock pricing for each model. The `ModelPricing` class in `backend/app/services/pricing.py` maintains a pricing table with per-token rates.

### 8.1 Cost Calculation Flow

```mermaid
graph TD
    A["API Response received<br/>with token counts"] --> B["Extract model, prompt_tokens,<br/>completion_tokens,<br/>cache_creation_input_tokens,<br/>cache_read_input_tokens"]
    B --> C{"Model in<br/>PRICING table?"}
    C -->|"Yes"| D["Get model-specific<br/>(input_rate, output_rate)"]
    C -->|"No"| E["Fallback: Claude 3.5<br/>Sonnet pricing"]
    D --> F["cost = prompt_tokens × input_rate<br/>+ completion_tokens × output_rate<br/>+ cache_write_tokens × input_rate × 1.25<br/>+ cache_read_tokens × input_rate × 0.1"]
    E --> F
    F --> G["INSERT UsageRecord<br/>(cost_usd, tokens, cache tokens, model)"]
    G --> H["Token quota check on<br/>next request:<br/>SUM(cost_usd) vs quota_usd"]
```

> **Prompt Cache Pricing**: When prompt caching is enabled, cache write tokens are charged at 1.25x and cache read tokens at 0.1x the base input price. See [Dynamic Pricing System](pricing-system.md#prompt-cache-differentiated-pricing) for details.

### 8.2 Supported Model Pricing

| Model | Input (per 1M tokens) | Output (per 1M tokens) | Typical Use Case |
|---|---|---|---|
| Claude 3.5 Sonnet v2 | $3.00 | $15.00 | Balanced performance |
| Claude 3.5 Sonnet | $3.00 | $15.00 | Balanced performance |
| Claude 3 Sonnet | $3.00 | $15.00 | Standard tasks |
| Claude 3 Haiku | $0.25 | $1.25 | Fast, cost-effective |
| Claude 3 Opus | $15.00 | $75.00 | Highest intelligence |
| Mistral Large | $0.50 | $1.50 | European alternative |
| Mistral Small | $1.00 | $3.00 | Lightweight tasks |
| Llama 3 70B | $2.65 | $3.50 | Open source, large |
| Llama 3 8B | $0.30 | $0.60 | Open source, small |

### 8.3 Example Calculation

**Request**: Claude 3 Haiku, 10,000 input tokens, 5,000 output tokens

```
input_cost  = 10,000 * ($0.25 / 1,000,000) = $0.0025
output_cost =  5,000 * ($1.25 / 1,000,000) = $0.00625
total_cost  = $0.0025 + $0.00625 = $0.00875
```

### 8.4 Token Quota System

Each API token (`APIToken.quota_usd`) can have an optional spending limit. The quota check happens at the beginning of each request:

1. Query `SUM(cost_usd)` from `usage_records` for the token
2. Compare against `quota_usd`
3. If `total_used >= quota_usd`, return **HTTP 429** with message: `Token quota exceeded. Used: $X.XX, Quota: $Y.YY`

Usage recording is performed **asynchronously** via `BackgroundTaskManager` to avoid blocking the response to the client. The cost is calculated using `ModelPricing.calculate_cost()` with a fallback to Claude 3.5 Sonnet pricing if the model is not found in the pricing table.

### 8.5 Cost Disclaimer

Displayed costs are estimates based on token usage. Actual AWS billing may differ due to pricing updates, regional variations, additional AWS fees, and rounding differences in token counting.

---

## Related Documentation

| Document | Description |
|---|---|
| [Request Translation](request-translation.md) | Full request/response translation pipeline (OpenAI → Bedrock → Anthropic) |
| [Dynamic Pricing System](pricing-system.md) | Price fetching, cache-aware cost calculation, and pricing table display |
| [API Reference](api-reference.md) | Complete endpoint documentation with request/response examples |
| [OAuth Setup](oauth-setup.md) | Microsoft and Cognito OAuth configuration |
| [Deployment](deployment.md) | Production and non-production deployment guide |

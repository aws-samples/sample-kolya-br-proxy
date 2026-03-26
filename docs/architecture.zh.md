# 架构文档

Kolya BR Proxy 综合架构文档 -- 一个提供 OpenAI 兼容 API 和 Anthropic Messages API 访问 AWS Bedrock 模型（Claude、Nova、DeepSeek、Mistral、Llama 等）的 AI 网关。

---

## 目录

1. [系统架构概览](#1-系统架构概览)
2. [后端分层架构](#2-后端分层架构)
3. [数据库 ER 图](#3-数据库-er-图)
4. [前端架构](#4-前端架构)
5. [基础设施架构](#5-基础设施架构)
6. [认证流程](#6-认证流程)
7. [请求处理流程](#7-请求处理流程)
8. [计费模型](#8-计费模型)

---

## 1. 系统架构概览

系统采用经典三层架构：Nginx 托管的 Vue 3 前端、运行在 Uvicorn 上的 FastAPI 后端，以及作为上游 LLM 提供者的 AWS Bedrock。所有组件运行在 AWS EKS 集群内，使用 PostgreSQL 进行持久化存储、Redis 进行分布式限流，并通过 External Secrets Operator（ESO）管理密钥。

```mermaid
graph LR
    subgraph Clients ["Client Applications"]
        OAI["OpenAI SDK / Client Libraries"]
        Anthropic_SDK["Anthropic SDK / Client Libraries"]
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
        Redis["Redis Standalone<br/>(分布式限流)"]
    end

    subgraph AWS_Services ["AWS Services"]
        Bedrock["AWS Bedrock<br/>(Claude, Nova, DeepSeek,<br/>Mistral, Llama)"]
    end

    OAI -->|"HTTPS /v1/chat/*"| ALB
    Anthropic_SDK -->|"HTTPS /v1/messages"| ALB
    Browser -->|"HTTPS /*"| ALB
    ALB -->|"Frontend routes"| Nginx
    ALB -->|"API routes"| Uvicorn
    Nginx --> Vue
    Uvicorn --> FastAPI
    FastAPI -->|"InvokeModel /<br/>Converse API"| Bedrock
    FastAPI -->|"SQLAlchemy async"| PG
    FastAPI -.->|"分布式限流"| Redis
```

### 关键设计决策

| 决策 | 理由 |
|------|------|
| 双 API 兼容 | OpenAI 兼容（`/v1/chat/completions`）和 Anthropic Messages API（`/v1/messages`）；客户端只需修改 `base_url` 和 `api_key` |
| 可配置 API 密钥前缀 | 默认 `kbr_` 前缀；可选 `sk-ant-api03` 前缀以兼容 Claude Code / Anthropic SDK |
| 剥离历史 thinking blocks | Bedrock 不支持 adaptive 模式的 signature-only thinking blocks，发送前自动从对话历史中移除 |
| 单例 `BedrockClient` | 每进程一个共享 aioboto3 会话 + 连接池 |
| 异步信号量 (50) | 反压匹配连接池大小；防止请求排队 |
| 面板用 JWT，网关用 API 密钥 | 分离认证关注点；API 密钥长期有效，JWT 短期有效 |
| 后台使用量记录 | `record_usage` 作为后台任务运行，避免阻塞响应 |

---

## 2. 后端分层架构

后端分为四层：API 层（路由 + 验证）、中间件层（安全 + CORS）、服务层（业务逻辑）和数据层（SQLAlchemy 模型）。入口点是 `backend/main.py`，通过 `create_app()` 工厂函数和 `lifespan` 上下文管理器初始化 FastAPI 应用。

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

        subgraph V1_Sub ["Gateway Endpoints"]
            subgraph OpenAI_Sub ["OpenAI-compatible"]
                Chat_EP["/v1/chat/completions<br/>streaming + non-streaming"]
                Models_List["/v1/models<br/>list available models"]
            end
            subgraph Anthropic_Sub ["Anthropic Messages API"]
                Messages_EP["/v1/messages<br/>streaming + non-streaming"]
            end
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
        AnthReqTranslator["AnthropicRequestTranslator<br/>(Anthropic -> Bedrock)"]
        AnthResTranslator["AnthropicResponseTranslator<br/>(Bedrock -> Anthropic)"]
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

### 中间件栈顺序

中间件在 `backend/main.py` 的 `create_app()` 中注册。FastAPI 按注册的逆序处理中间件（最后添加 = 最外层）。入站请求的有效处理顺序为：

1. **Cache-Control** -- 为每个响应添加 `no-cache, no-store` 头
2. **SecurityMiddleware** -- 来源验证、CSRF 保护（`X-Requested-With`）、安全响应头（`X-Content-Type-Options`、`X-Frame-Options`、CSP）
3. **CORSMiddleware** -- 处理 `OPTIONS` 预检请求，设置 `Access-Control-*` 头

### 生命周期事件

```python
# backend/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()                   # 初始化数据库连接池
    BedrockClient.get_instance()      # 创建 Bedrock 客户端单例
    yield
    # 关闭：清理资源
```

启动时初始化数据库连接池和 Bedrock 客户端单例；关闭时清理资源。

---

## 3. 数据库 ER 图

所有模型使用 UUID 主键，定义在 `backend/app/models/`。通过 SQLAlchemy ORM 实施关系约束，适当位置使用级联删除。

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
        int cache_creation_input_tokens "Cache 写入 tokens"
        int cache_read_input_tokens "Cache 读取 tokens"
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
        string code_verifier "PKCE code_verifier (nullable)"
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

### 关键模型说明

- **User.auth_method**：枚举值包括 `MICROSOFT`、`COGNITO`。所有用户通过 OAuth 认证，`password_hash` 为 NULL。
- **APIToken**：同时存储 `token_hash`（SHA256，用于查找）和 `encrypted_token`（Fernet AES，用于恢复）。`quota_usd` 字段限制每个令牌的总消费。模型访问通过关联的 `Model` 表控制，而非数组列。
- **Model**：每行将一个 Bedrock 模型名称关联到一个 APIToken。令牌只能访问 `is_active=True` 且 `is_deleted=False` 的模型。
- **RefreshToken.family_id**：将相关令牌分组用于盗用检测。如果已撤销的令牌被重用，整个族群将被撤销。

---

## 4. 前端架构

前端是基于 Quasar 框架（暗色主题）构建的 Vue 3 SPA。使用 Pinia 存储进行状态管理，Vue Router 进行导航并带有认证守卫，以及带有自动 401 刷新拦截器的 Axios。

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

### 路由结构

| 路径 | 页面 | 需要认证 | 描述 |
|------|------|----------|------|
| `/login` | LoginPage | 否 | 用户登录（OAuth 提供商选择） |
| `/auth/cognito/callback` | CognitoCallbackPage | 否 | Cognito OAuth 回调 |
| `/auth/microsoft/callback` | MicrosoftCallbackPage | 否 | Microsoft OAuth 回调 |
| `/` | DashboardPage | 是 | 概览，使用统计 |
| `/tokens` | TokensPage | 是 | API 密钥管理 |
| `/models` | ModelsPage | 是 | 模型配置 |
| `/playground` | PlaygroundPage | 是 | 测试对话 |
| `/monitor` | MonitorPage | 是 | 使用量图表与分析 |
| `/settings` | SettingsPage | 是 | 账户设置 |

### 侧边栏导航

`MainLayout.vue` 渲染持久左侧抽屉，包含以下菜单项：仪表板、API 密钥、模型、Playground、监控、设置。顶部栏显示应用标题和用户菜单（邮箱、余额、设置、登出）。

---

## 5. 基础设施架构

基础设施使用 Terraform 定义（`iac/`）。所有配置集中在 `iac/terraform.tfvars` 作为唯一来源（账号、区域、域名、功能开关）。`deploy-all.sh` 脚本编排完整部署流程（Steps 0-5），`destroy.sh` 处理安全销毁。它配置 VPC、带有 Karpenter 自动扩缩的 EKS 集群、Aurora PostgreSQL、Redis 分布式限流，以及可选的 WAF / Global Accelerator。密钥通过 AWS Secrets Manager + External Secrets Operator（ESO）管理。

```mermaid
graph TD
    subgraph AWS_Region ["AWS Region"]
        subgraph VPC ["VPC Module"]
            subgraph Public_Subnets ["Public Subnets"]
                ALB["Application Load<br/>Balancer (ALB)<br/>(动态创建)"]
                NAT["NAT Gateway"]
            end

            subgraph Private_Subnets ["Private Subnets"]
                subgraph EKS ["EKS Cluster (eks_karpenter module)"]
                    Karpenter["Karpenter<br/>Node Autoscaler"]
                    LBC["AWS Load Balancer<br/>Controller"]
                    FrontendPod["Frontend Pod<br/>(Vue3/Quasar + Nginx)"]
                    BackendPod["Backend Pod<br/>(FastAPI + Uvicorn)"]
                end
                Aurora["Aurora PostgreSQL<br/>(RDS Module)<br/>(私有，无外部访问)"]
                Redis_Pod["Redis Standalone<br/>(kbp 命名空间)"]
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
    BackendPod -.->|"限流"| Redis_Pod
    ESO -->|"同步密钥<br/>(refreshInterval: 1h)"| SecretsManager
    Karpenter --> Private_Subnets
    LBC -.->|"创建和管理"| ALB
    ECR -.->|"Pull images"| EKS
```

### 密钥管理（ESO + AWS Secrets Manager）

密钥存储在 **AWS Secrets Manager** 中，由 **External Secrets Operator（ESO）** 自动同步到 Kubernetes Secrets。这取代了本地 `secrets.yaml` 文件，确保密钥不存在于版本控制中。

| 组件 | 角色 |
|------|------|
| AWS Secrets Manager | 所有密钥的单一事实来源（数据库凭证、JWT 密钥、OAuth 客户端密钥等） |
| External Secrets Operator（ESO） | 运行在集群内，监听 `ExternalSecret` CRD，从 AWS Secrets Manager 同步密钥到 K8s Secrets |
| Pod Identity | ESO 通过 EKS Pod Identity 认证 AWS Secrets Manager（无需静态 AWS 凭证） |
| `deploy-all.sh` Step 4 | 通过 `aws secretsmanager put-secret-value` 推送密钥（保留已有值） |

**同步行为：**
- `refreshInterval: 1h` -- ESO 每小时重新从 Secrets Manager 拉取密钥
- 密钥以标准 Kubernetes Secrets 形式创建，Pod 通过 `envFrom` 或 `env` 引用消费
- AWS Secrets Manager 中的密钥轮换会在刷新间隔内自动生效

### Redis 分布式限流

**Redis standalone** 实例运行在 `kbp`（kolya-br-proxy）命名空间中，为所有后端 Pod 提供分布式限流。

| 方面 | 详情 |
|------|------|
| 部署方式 | Redis standalone，部署在 `kbp` 命名空间（Kubernetes Deployment + Service） |
| 用途 | 通过原子 Lua 脚本实现全局令牌桶限流 |
| 降级策略 | Redis 不可用时，每个 Pod 回退到本地内存 `LocalTokenBucket`（按 Pod 限流，而非跳过限流） |
| 访问方式 | 后端 Pod 通过 Kubernetes Service DNS 连接（`redis.kbp.svc.cluster.local`） |

### 配置：`terraform.tfvars`

所有部署配置集中在 `iac/terraform.tfvars`。`deploy-all.sh` 和 `destroy.sh` 均从此文件读取和写入。

| 键 | 说明 |
|------|------|
| `account` / `region` | AWS 账号 ID 和目标区域 |
| `frontend_domain` / `api_domain` | 域名（如 `kbp.kolya.fun`、`api.kbp.kolya.fun`） |
| `project_name` / `project_name_alias` | 资源命名（部分资源用全名，部分用别名） |
| `enable_waf` | WAF 开关（Step 4 ALB 就绪后自动启用） |
| `enable_global_accelerator` | Global Accelerator 开关（Step 5） |
| `enable_cognito` | 认证方式开关（Step 0 选择） |
| `cognito_allowed_email_domains` | Cognito 邮箱域名白名单 |

### 部署流水线：`deploy-all.sh`

| 步骤 | 命令 | 功能 |
|------|------|------|
| 0 | `--step 0` | 自动检测账号/区域、选择认证方式、配置域名 → 写入 `terraform.tfvars` |
| 1 | `--step 1` | `terraform init` + `plan` + `apply`（VPC、EKS、RDS、Cognito 等） |
| 2 | `--step 2` | 部署 Helm charts（ALB Controller、Karpenter、Metrics Server） |
| 3 | `--step 3` | 构建 Docker 镜像推送到 ECR（域名从 tfvars 读取） |
| 4 | `--step 4` | 部署 K8s 应用（从 tfvars 生成配置、推送密钥到 SM、自动启用 WAF） |
| 5 | `--step 5` | 启用/禁用 Global Accelerator |

### 销毁流程：`destroy.sh`

1. 验证 AWS 身份，确认目标（账号、区域、workspace）
2. 初始化 Terraform，选择 workspace
3. 通过 `terraform apply` 禁用 WAF/GA（其 `data "aws_lb"` 查找需要 ALB 存在）
4. 清理 K8s 资源（先删 Ingress → 触发 ALB 删除，再删 ExternalSecrets、命名空间）
5. `terraform destroy` 销毁剩余基础设施

> **重要：** K8s 资源（特别是 Ingress/ALB）必须在 `terraform destroy` 前删除，否则 ALB 和 target group 会阻塞 Terraform。

### Terraform 模块

| 模块 | 源路径 | 用途 |
|------|--------|------|
| `vpc` | `./modules/vpc` | VPC 含公私子网、IGW、NAT、安全组 |
| `rds_aurora_postgresql` | `./modules/rds-aurora-postgresql` | Aurora PostgreSQL 含加密、备份、监控 |
| `eks_karpenter` | `./modules/eks-karpenter` | EKS 集群 + Karpenter 节点自动扩缩 |
| `eks_addons` | `./modules/eks-addons` | Karpenter Helm chart、AWS LB 控制器 |
| `cognito` | `./modules/cognito` | Cognito User Pool & App Client（callback URLs 从 `frontend_domain` 自动派生） |
| `waf` | `./modules/waf` | Web Application Firewall（ALB 就绪后自动启用） |
| `global_accelerator` | `./modules/global-accelerator` | 可选 GA 用于全球边缘路由 |

### 环境差异

| 设置 | 生产 | 非生产 |
|------|------|--------|
| `deletion_protection` | `true` | `false` |
| `backup_retention_period` | 7 天 | 1 天 |
| `performance_insights` | 启用 | 禁用 |
| `monitoring_interval` | 60s | 0（禁用） |
| `skip_final_snapshot` | `false` | `true` |
| `apply_immediately` | `false` | `true` |
| `flow_logs` (GA) | 启用 | 禁用 |

---

## 6. 认证流程

系统支持两种 OAuth 认证方式：**AWS Cognito** 和 **Microsoft Entra ID**（通过 `deploy-all.sh --step 0` 选择）。不支持本地用户名/密码认证。管理面板使用 JWT（访问令牌 + 刷新令牌），而网关 API 使用 API 密钥（`kbr_` 前缀）—— OpenAI 兼容端点通过 `Authorization: Bearer` 传递，Anthropic 端点通过 `x-api-key` 头传递。两种认证方式验证相同的 `kbr_` 令牌。Cognito 回调 URL 从 `terraform.tfvars` 中的 `frontend_domain` 自动派生。

### 6.1 OAuth 流程（Cognito / Microsoft）

```mermaid
sequenceDiagram
    participant User as User (Browser)
    participant FE as Frontend
    participant BE as Backend
    participant IdP as Identity Provider<br/>(Microsoft / Cognito)
    participant DB as PostgreSQL

    User->>FE: Click "Sign in with Microsoft"
    FE->>BE: GET /admin/auth/microsoft/login?redirect_uri=...
    BE->>BE: 生成 PKCE code_verifier + code_challenge (S256)
    BE->>DB: 存储 OAuthState (state, code_verifier, 10 min TTL)
    BE-->>FE: {authorization_url (含 code_challenge), state}
    FE->>IdP: Redirect to authorization_url

    User->>IdP: Authenticate + consent
    IdP-->>FE: Redirect to /auth/microsoft/callback?code=...&state=...
    FE->>BE: POST /admin/auth/microsoft/callback {code, state, redirect_uri}
    BE->>DB: 验证 OAuthState (CSRF 检查)，取回 code_verifier
    BE->>IdP: 用 code + code_verifier 换取 tokens
    IdP-->>BE: {access_token, id_token}
    BE->>IdP: Fetch user profile (MS Graph / Cognito userInfo)
    IdP-->>BE: {email, name, sub}
    BE->>DB: Find or create User (auth_method=MICROSOFT)
    BE->>DB: Create RefreshToken + AuditLog
    BE-->>FE: {access_token, user} + Set-Cookie: kbr_refresh_token (HttpOnly)
    FE->>FE: 存储 access_token 到 localStorage，跳转仪表板
```

### 6.2 API 密钥认证（网关）

相同的 `kbr_` API 密钥同时适用于 OpenAI 兼容和 Anthropic 端点，唯一区别是请求头格式：

- **OpenAI 路径**：`Authorization: Bearer kbr_xxx`（从 Bearer token 提取）
- **Anthropic 路径**：`x-api-key: kbr_xxx`（从 `x-api-key` 头提取）

两条路径使用相同的验证逻辑（Redis 缓存 → 数据库降级）。

```mermaid
sequenceDiagram
    participant Client as API Client<br/>(OpenAI or Anthropic SDK)
    participant BE as Backend (FastAPI)
    participant Redis as Redis (optional)
    participant DB as PostgreSQL

    alt OpenAI 兼容端点
        Client->>BE: POST /v1/chat/completions<br/>Authorization: Bearer kbr_xxx...
        BE->>BE: Extract token from Bearer header
    else Anthropic 端点
        Client->>BE: POST /v1/messages<br/>x-api-key: kbr_xxx...
        BE->>BE: Extract token from x-api-key header
    end

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

### 令牌类型对比

| 属性 | JWT 访问令牌 | JWT 刷新令牌 | API 密钥 (`kbr_`) |
|------|-------------|-------------|-------------------|
| 有效期 | 30 分钟 | 7 天 | 直到过期或撤销 |
| 使用者 | 管理面板 | 管理面板（刷新） | OpenAI / Anthropic 客户端 |
| 存储 | localStorage | HttpOnly cookie (`kbr_refresh_token`, Path=/admin/auth) | 客户端配置 |
| 验证 | JWT 解码 + 签名 | 数据库查找（哈希 + 族群） | 数据库查找（SHA256 哈希） |
| 轮换 | 刷新时 | 每次使用（签发新令牌） | 手动 |

---

## 7. 请求处理流程

本节详细描述网关请求的完整生命周期。代理支持两条 API 路径：

- **OpenAI 路径**（`/v1/chat/completions`）：在 OpenAI 和 Bedrock 格式之间进行完整转换
- **Anthropic 路径**（`/v1/messages`）：近乎直通，因为 Bedrock InvokeModel 原生使用 Anthropic Messages API 格式

### 7.1 OpenAI 路径时序图

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
        Note over Bedrock: 获取信号量 (最大 50)
        alt Anthropic 模型
            Bedrock->>AWS: invoke_model_with_response_stream(body)
            loop 流式事件
                AWS-->>Bedrock: Anthropic SSE 事件 (JSON)
                Bedrock->>Bedrock: _anthropic_event_to_bedrock()
            end
        else 非 Anthropic 模型 (Nova, DeepSeek 等)
            Bedrock->>AWS: converse_stream(params)
            loop 流式事件
                AWS-->>Bedrock: Converse 流事件
                Bedrock->>Bedrock: _converse_stream_event_to_bedrock()
            end
        end
        Bedrock-->>Chat: BedrockStreamEvent
        Chat->>Translator: create_stream_chunk(...)
        Translator-->>Chat: SSE 格式化 chunk
        Chat-->>Client: data: {...}\n\n
        Chat-->>Client: data: [DONE]\n\n
        Note over Bedrock: 释放信号量
    else Non-streaming
        Chat->>Bedrock: invoke(model, request)
        Note over Bedrock: 获取信号量
        alt Anthropic 模型
            Bedrock->>AWS: invoke_model(body)
            AWS-->>Bedrock: Anthropic Messages API JSON
        else 非 Anthropic 模型 (Nova, DeepSeek 等)
            Bedrock->>AWS: converse(params)
            AWS-->>Bedrock: Converse API JSON
        end
        Note over Bedrock: 释放信号量
        Bedrock-->>Chat: BedrockResponse
        Chat->>Translator: bedrock_to_openai(response)
        Translator-->>Chat: ChatCompletionResponse
        Chat-->>Client: JSON 响应
    end

    Chat->>BG: background: record_usage(...)
    BG->>Pricing: calculate_cost(model, tokens)
    Pricing-->>BG: cost_usd
    BG->>DB: INSERT INTO usage_records
```

### 7.2 Anthropic 路径时序图

Anthropic 路径是近乎直通的：由于 Bedrock 的 InvokeModel API 原生接受 Anthropic Messages API 格式，只需极少转换。与 OpenAI 路径的关键区别：

- 通过 `x-api-key` 头认证，而非 `Authorization: Bearer`
- 响应中保留 thinking blocks（OpenAI 路径会跳过它们）
- 流式使用 Anthropic SSE 格式（`event: type\ndata: {json}\n\n`）而非 OpenAI 格式（`data: {json}\n\n`）

```mermaid
sequenceDiagram
    participant Client as Anthropic Client
    participant MW as Middleware Stack
    participant Msg as messages.py endpoint
    participant Deps as deps.py (DI)
    participant TokenSvc as TokenService
    participant DB as PostgreSQL
    participant Translator as AnthropicRequestTranslator /<br/>AnthropicResponseTranslator
    participant Bedrock as BedrockClient<br/>(semaphore=50)
    participant AWS as AWS Bedrock API
    participant BG as BackgroundTaskManager

    Client->>MW: POST /v1/messages<br/>x-api-key: kbr_xxx
    MW->>MW: SecurityMiddleware + CORS
    MW->>Msg: Route to handler

    Msg->>Deps: Depends(get_current_token_from_api_key)
    Deps->>TokenSvc: validate_token(kbr_xxx)
    TokenSvc->>DB: SELECT by token_hash
    DB-->>TokenSvc: APIToken
    TokenSvc-->>Msg: Validated APIToken

    Msg->>Msg: 配额检查 + 模型访问检查

    Msg->>Translator: to_bedrock_with_passthrough(request)
    Note over Translator: 近 1:1 映射，<br/>保留 cache_control
    Translator-->>Msg: invoke_model 原始字典

    alt Streaming (stream=true)
        Msg->>Bedrock: invoke_stream(model, request)
        Bedrock->>AWS: invoke_model_with_response_stream(body)
        loop 流式事件
            AWS-->>Bedrock: Anthropic SSE 事件
            Bedrock-->>Msg: BedrockStreamEvent
        end
        Msg->>Translator: bedrock_stream_to_anthropic_events(event)
        Translator-->>Msg: Anthropic SSE 格式化字符串
        Msg-->>Client: event: content_block_delta\ndata: {...}\n\n
        Msg-->>Client: event: message_stop\ndata: {...}\n\n
    else Non-streaming
        Msg->>Bedrock: invoke(model, request)
        Bedrock->>AWS: invoke_model(body)
        AWS-->>Bedrock: Anthropic Messages API JSON
        Bedrock-->>Msg: BedrockResponse
        Msg->>Translator: bedrock_to_anthropic(response)
        Translator-->>Msg: AnthropicMessagesResponse
        Msg-->>Client: JSON 响应
    end

    Msg->>BG: background: record_usage(...)
```

### 7.3 请求/响应转换

代理在客户端 API 格式和 Bedrock 之间执行转换：

- **OpenAI 路径**：三阶段转换（OpenAI → `BedrockRequest` → Bedrock API → `BedrockResponse` → OpenAI）。包括消息转换、工具调用映射、参数翻译和自动修正。
- **Anthropic 路径**：近乎直通（Anthropic → 原始字典 → `invoke_model`）。由于 Bedrock 原生使用 Anthropic Messages API 格式处理 Claude 模型，只需极少转换。保留 `cache_control` 标记和 thinking blocks。

对于非 Anthropic 模型（Nova、DeepSeek、Mistral、Llama 等），两条路径都通过 `converse`/`converse_stream` 使用 Converse API。

完整的转换管线文档请参阅 **[请求转换管线](request-translation.zh.md)**。

---

## 8. 计费模型

成本按每次请求基于各模型的实际 AWS Bedrock 定价计算。`backend/app/services/pricing.py` 中的 `ModelPricing` 类维护一个按令牌计费的价格表。

### 8.1 成本计算流程

```mermaid
graph TD
    A["收到 API 响应<br/>含 token 计数"] --> B["提取 model、prompt_tokens、<br/>completion_tokens、<br/>cache_creation_input_tokens、<br/>cache_read_input_tokens"]
    B --> C{"模型在<br/>PRICING 表中？"}
    C -->|"是"| D["获取模型定价<br/>(input_rate, output_rate)"]
    C -->|"否"| E["回退：Claude 3.5<br/>Sonnet 定价"]
    D --> F["cost = prompt_tokens × input_rate<br/>+ completion_tokens × output_rate<br/>+ cache_write_tokens × input_rate × 1.25<br/>+ cache_read_tokens × input_rate × 0.1"]
    E --> F
    F --> G["INSERT UsageRecord<br/>(cost_usd, tokens, cache tokens, model)"]
    G --> H["下次请求时检查配额：<br/>SUM(cost_usd) vs quota_usd"]
```

> **Prompt Cache 计价**：开启 prompt caching 后，cache 写入 token 按 1.25x、cache 读取 token 按 0.1x 基础 input 价格计费。详见[动态价格系统](pricing-system.zh.md#prompt-cache-差异化计价)。

### 8.2 支持的模型定价

| 模型 | 输入（每 1M tokens） | 输出（每 1M tokens） | 典型用途 |
|------|---------------------|---------------------|----------|
| Claude 3.5 Sonnet v2 | $3.00 | $15.00 | 均衡性能 |
| Claude 3.5 Sonnet | $3.00 | $15.00 | 均衡性能 |
| Claude 3 Sonnet | $3.00 | $15.00 | 标准任务 |
| Claude 3 Haiku | $0.25 | $1.25 | 快速低成本 |
| Claude 3 Opus | $15.00 | $75.00 | 最高智能 |
| Mistral Large | $0.50 | $1.50 | 欧洲替代方案 |
| Mistral Small | $1.00 | $3.00 | 轻量级任务 |
| Llama 3 70B | $2.65 | $3.50 | 开源大模型 |
| Llama 3 8B | $0.30 | $0.60 | 开源小模型 |

### 8.3 计算示例

**请求**：Claude 3 Haiku，10,000 输入 tokens，5,000 输出 tokens

```
input_cost  = 10,000 * ($0.25 / 1,000,000) = $0.0025
output_cost =  5,000 * ($1.25 / 1,000,000) = $0.00625
total_cost  = $0.0025 + $0.00625 = $0.00875
```

### 8.4 令牌配额系统

每个 API 令牌（`APIToken.quota_usd`）可以有可选的消费限额。配额检查在每个请求开始时进行：

1. 查询该令牌的 `usage_records` 中 `SUM(cost_usd)`
2. 与 `quota_usd` 比较
3. 若 `total_used >= quota_usd`，返回 **HTTP 429** 并提示：`Token quota exceeded. Used: $X.XX, Quota: $Y.YY`

使用量记录通过 `BackgroundTaskManager` **异步** 执行，以避免阻塞对客户端的响应。成本使用 `ModelPricing.calculate_cost()` 计算，若模型不在价格表中则回退到 Claude 3.5 Sonnet 定价。

### 8.5 成本免责声明

显示的成本是基于令牌使用量的估算值。实际 AWS 账单可能因价格更新、区域差异、额外 AWS 费用和令牌计数的舍入差异而有所不同。

---

## 相关文档

| 文档 | 说明 |
|------|------|
| [请求转换管线](request-translation.zh.md) | 完整的请求/响应转换管线（OpenAI → Bedrock → Anthropic） |
| [动态价格系统](pricing-system.zh.md) | 价格获取、cache 差异化计费、价格表展示 |
| [API 参考](api-reference.zh.md) | 完整的端点文档及请求/响应示例 |
| [OAuth 配置](oauth-setup.zh.md) | Microsoft 和 Cognito OAuth 配置 |
| [部署指南](deployment.zh.md) | 生产和非生产环境部署指南 |

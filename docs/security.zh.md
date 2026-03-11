# 安全设计：WAF、CORS 与 CSRF 防护

本文档介绍 Kolya BR Proxy 的安全防护设计，包括 AWS WAF（ALB 层的限流与托管规则集）、跨域资源共享（CORS）和跨站请求伪造（CSRF）的防护——攻击原理、为什么 API 网关必须防范这些攻击，以及本项目的具体实现。

---

## 为什么 API 网关需要安全防护？

Kolya BR Proxy 同时服务两类客户端：

1. **API 客户端**（Cline、Cursor、OpenAI SDK）—— 使用 Bearer Token 直接调用 `/v1/*` 端点
2. **浏览器客户端**（Vue 管理面板）—— 通过 JWT（Bearer Token）调用 `/admin/*` 端点

本项目**不使用 Cookie 认证**。前端将 JWT 存储在 `localStorage` 中，通过 `Authorization: Bearer <token>` 头发送。这意味着浏览器不会自动附带凭证，传统 CSRF 攻击（依赖 Cookie 自动发送）对本项目的直接威胁较低。

尽管如此，本项目仍然实施了完整的 CORS 和 CSRF 防护，原因如下：

- **纵深防御（Defense in Depth）**—— 安全设计不应依赖单一机制。如果未来引入 Cookie（如 HttpOnly refresh token），防护已经就绪
- **Origin 验证**可以阻止来自非法域名的跨域请求，无论认证方式如何
- **安全响应头**防止点击劫持（Clickjacking）、MIME 嗅探、XSS 等浏览器端攻击
- **行业最佳实践**—— OWASP 推荐对所有 Web API 实施这些防护，不论当前认证方案

---

## CORS（跨域资源共享）

### 什么是 CORS？

浏览器的**同源策略（Same-Origin Policy）**默认禁止网页向不同源（协议 + 域名 + 端口）发起请求。CORS 是一组 HTTP 头，允许服务器明确声明哪些外部源可以访问其资源。

### 为什么本项目必须配置 CORS？

本项目的前端和后端运行在**不同的源（Origin）**上，属于典型的跨域架构：

| 环境 | 前端（管理面板） | 后端（API） | 是否跨域 |
|------|----------------|------------|---------|
| 本地开发 | `http://localhost:9000` | `http://localhost:8000` | 是（端口不同） |
| 生产环境 | `https://kbp.kolya.fun` | `https://api.kbp.kolya.fun` | 是（域名不同） |

根据浏览器的同源策略，协议、域名、端口三者中**任意一个不同**即为跨域。前端管理面板向后端 API 发起的每一个请求都是跨域请求。**如果后端不配置 CORS 白名单，浏览器会直接拦截所有来自前端的 API 调用，管理面板将完全无法工作。**

因此 CORS 配置是本项目的**基础需求**——不是可选的安全加固，而是前后端分离架构正常运行的前提。

但 CORS 配置不当同样危险：

- **`Access-Control-Allow-Origin: *`** —— 任何网站都可以读取 API 响应，可能泄露敏感数据
- **过宽的白名单** —— 攻击者可以利用被允许的域名发起攻击

正确的做法是**仅允许自己的前端域名**，拒绝其他一切来源。

### 攻击场景

```
1. 管理员登录 Kolya BR Proxy 管理面板（浏览器持有 JWT）
2. 管理员在新标签页打开攻击者的恶意网站 evil.com
3. evil.com 的 JavaScript 向 https://api.kbp.kolya.fun/admin/tokens 发起 GET 请求
4. 如果 CORS 配置为 *，浏览器允许 evil.com 读取响应
5. 攻击者获取到所有 API Token 列表
```

### 本项目的 CORS 实现

**配置入口**：`backend/main.py`

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins(),  # 严格白名单
    allow_credentials=True,                         # 允许携带凭证
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**分环境策略**：

| 环境 | `KBR_ALLOWED_ORIGINS` | 安全等级 |
|------|----------------------|---------|
| 本地开发 | `http://localhost:3000,http://localhost:9000` | 宽松（方便开发） |
| 非生产环境 | 非生产域名，可包含 `*`（测试用） | 中等 |
| 生产环境 | 仅允许生产域名（如 `https://kbp.kolya.fun`） | 严格 |

**生产环境校验**（`backend/app/core/config.py`）：

```python
@validator("ALLOWED_ORIGINS")
def validate_allowed_origins(cls, v, values):
    env = os.getenv("KBR_ENV", "non-prod")
    debug = values.get("DEBUG", False)
    if v == "*" and env == "prod" and not debug:
        logger.error("SECURITY WARNING: ALLOWED_ORIGINS is set to '*' in production.")
    return v
```

---

## CSRF（跨站请求伪造）

### 什么是 CSRF？

CSRF 攻击利用浏览器自动附带 Cookie 的机制，诱导已认证用户在不知情的情况下向目标网站发起请求。与 CORS 不同，CSRF 不需要读取响应——只需要请求被执行即可造成危害。

### 为什么 CORS 不能防止 CSRF？

这是一个常见误解。CORS 只控制**浏览器是否允许读取响应**，并不阻止请求的发送：

| 场景 | CORS 的作用 | CSRF 风险 |
|------|------------|----------|
| 简单 POST 请求（`Content-Type: application/x-www-form-urlencoded`） | 浏览器直接发送，不做预检 | **高风险** —— 请求已经到达服务器并执行 |
| JSON POST 请求（`Content-Type: application/json`） | 触发预检（OPTIONS），预检失败则不发送实际请求 | **低风险** —— 但依赖正确的 CORS 配置 |
| GET 请求 | 不做预检，直接发送 | 取决于 GET 是否有副作用 |

对于本项目的 JSON API，CORS 预检机制确实提供了一定保护。但仅依赖 CORS 是不够的：
- CORS 策略可能被错误配置
- 某些边缘情况下浏览器行为不一致
- 纵深防御原则要求多层防护

### 攻击场景（假设使用 Cookie 认证的系统）

本项目使用 localStorage + Bearer Token，不直接受此攻击影响。但以下场景说明了为什么 CSRF 防护在基于 Cookie 的系统中至关重要：

```
1. 用户已登录某 Web 应用（浏览器存有认证 Cookie）
2. 用户访问恶意页面 evil.com
3. evil.com 提交一个隐藏表单到目标站点
   （Content-Type: application/x-www-form-urlencoded，不触发 CORS 预检）
4. 浏览器自动附带 Cookie
5. 如果服务器没有 CSRF 防护，请求被执行
6. 攻击者在用户不知情的情况下执行了敏感操作
```

本项目虽然不使用 Cookie，但 Origin 验证和自定义头检查仍然有效地限制了跨域请求来源，作为纵深防御的重要组成部分。

### 本项目的 CSRF 防护实现

**实现文件**：`backend/app/middleware/security.py` — `SecurityMiddleware`

本项目采用**三层防御**策略：

#### 第一层：Origin 验证

对所有状态变更操作（POST、PUT、DELETE、PATCH），检查 `Origin` 头是否在白名单中：

```python
if origin and not self._is_origin_allowed(origin):
    # 403 Forbidden - Origin not allowed
```

- 浏览器发送跨域请求时会自动附带 `Origin` 头，且 JavaScript 无法伪造
- 如果 `Origin` 不在白名单中，请求被直接拒绝

#### 第二层：Referer 验证（可选）

验证 `Referer` 头中的来源是否合法：

```python
if self.enforce_referer and not self._validate_referer(request):
    # 403 Forbidden - Invalid referer
```

- 默认关闭（`enforce_referer=False`），因为某些客户端不发送 Referer
- 可作为额外的安全层启用

#### 第三层：自定义头（X-Requested-With）

要求浏览器请求必须携带 `X-Requested-With` 头或 `Authorization` 头：

```python
if self.require_custom_header and origin:
    has_auth_header = request.headers.get("authorization")
    has_custom_header = request.headers.get("x-requested-with")
    if not has_auth_header and not has_custom_header:
        # 403 Forbidden - Missing CSRF protection header
```

**为什么这能防止 CSRF？**

- HTML 表单和 `<img>` 标签无法设置自定义 HTTP 头
- 只有 JavaScript 的 `XMLHttpRequest` 或 `fetch` 可以添加自定义头
- 而跨域 JavaScript 请求会触发 CORS 预检，被 Origin 白名单拦截

**前端配合**（`frontend/src/boot/axios.ts`）：

```typescript
const api = axios.create({
  headers: {
    'X-Requested-With': 'XMLHttpRequest',  // CSRF 防护
  },
});
```

#### 豁免规则

以下请求不受 CSRF 检查：

| 条件 | 原因 |
|------|------|
| `GET`、`HEAD`、`OPTIONS` 方法 | 安全方法，不改变服务器状态 |
| `/health/*` 路径 | 公开的健康检查端点 |
| 无 `Origin` 头的请求 | 非浏览器客户端（curl、SDK），使用 Bearer Token 认证 |

---

## OAuth State 防护（OAuth 登录流程中的 CSRF）

### 为什么 OAuth 流程需要额外的 CSRF 防护？

前面介绍的 `SecurityMiddleware` 防护的是**通用 API 请求**中的 CSRF。但 OAuth 登录流程有一个独特的攻击面——**OAuth 回调端点**。

OAuth Authorization Code 流程中，用户在第三方（Microsoft / Cognito）完成登录后，会被重定向回本项目的 callback 端点，并附带一个 `code` 参数。如果攻击者能构造一个恶意的回调 URL 诱导用户点击，就可以：

- **登录 CSRF（Login CSRF）**：将受害者的会话绑定到攻击者的账户
- **授权码注入**：用攻击者获取的 code 替换受害者的 code，窃取用户账户

### 攻击场景

```
1. 攻击者发起 OAuth 登录，获取一个有效的授权码（code）
2. 攻击者构造回调 URL：
   https://api.kbp.kolya.fun/admin/auth/cognito/callback?code=ATTACKER_CODE&state=...
3. 攻击者诱导受害者（已登录管理员）点击该链接
4. 如果没有 state 验证，服务器接受攻击者的 code
5. 受害者的浏览器会话与攻击者的 OAuth 身份绑定
```

### 本项目的 OAuth State 实现

**核心文件**：
- `backend/app/services/oauth.py` — `OAuthService`（State 生成与验证）
- `backend/app/models/oauth_state.py` — `OAuthState`（数据库模型）
- `backend/app/api/admin/endpoints/auth.py` — 登录和回调端点

#### 流程

```
1. 用户点击登录 → /admin/auth/cognito/login
   │
   ├── 生成 state = secrets.token_urlsafe(32)  （加密安全随机字符串）
   ├── 存入数据库 oauth_states 表（含 provider、expires_at）
   └── 返回 authorization_url（包含 state 参数）

2. 用户在 Cognito/Microsoft 完成认证 → 重定向到 callback
   │
   ├── /admin/auth/cognito/callback?code=xxx&state=yyy
   │
   ├── 验证 state：
   │   ├── 数据库查询：state 值 + provider 必须匹配
   │   ├── 过期检查：state 创建后 10 分钟内有效
   │   ├── 一次性使用：验证后立即从数据库删除
   │   └── 任何一项失败 → 403 Forbidden
   │
   └── state 验证通过 → 用 code 换取 token → 登录成功
```

#### 安全特性

| 特性 | 实现方式 | 目的 |
|------|---------|------|
| **加密安全随机** | `secrets.token_urlsafe(32)`（256 位熵） | 防止 state 被猜测或暴力破解 |
| **服务端存储** | PostgreSQL `oauth_states` 表 | 防止客户端篡改 |
| **Provider 绑定** | `state` + `provider` 联合验证 | 防止跨 Provider 重放 |
| **10 分钟过期** | `expires_at = created_at + 10min` | 缩小攻击时间窗口 |
| **一次性使用** | 验证成功后立即删除 | 防止重放攻击 |
| **过期清理** | `cleanup_expired_states()` 定期清理 | 防止数据库膨胀 |

#### 关键代码

**生成 State**（`backend/app/services/oauth.py`）：

```python
async def generate_state(self, provider: str) -> str:
    state = secrets.token_urlsafe(32)
    oauth_state = OAuthState(state=state, provider=provider)
    self.db.add(oauth_state)
    await self.db.commit()
    return state
```

**验证 State**（`backend/app/services/oauth.py`）：

```python
async def validate_state(self, state: str, provider: str) -> bool:
    # 查询数据库
    query = select(OAuthState).where(
        OAuthState.state == state, OAuthState.provider == provider
    )
    oauth_state = result.scalar_one_or_none()

    if not oauth_state or oauth_state.is_expired():
        return False

    # 一次性使用：验证后删除
    await self.db.delete(oauth_state)
    await self.db.commit()
    return True
```

**回调端点验证**（`backend/app/api/admin/endpoints/auth.py`）：

```python
# Microsoft 和 Cognito 回调都执行相同的验证
if not await oauth_state_service.validate_state(state, "cognito"):
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid or expired state parameter",
    )
```

---

## 安全响应头

除了 CORS 和 CSRF 防护，`SecurityMiddleware` 还为每个响应添加安全头：

| 头 | 值 | 作用 |
|----|----|----|
| `X-Content-Type-Options` | `nosniff` | 防止浏览器 MIME 类型嗅探 |
| `X-Frame-Options` | `DENY` | 防止点击劫持（Clickjacking） |
| `X-XSS-Protection` | `1; mode=block` | 启用浏览器 XSS 过滤器 |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | 控制 Referer 信息泄露 |
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'` | 限制资源加载，防止注入攻击 |
| `Cache-Control` | `no-cache, no-store, must-revalidate` | 防止敏感数据被缓存 |

---

## AWS WAF（Web 应用防火墙）

### 为什么在 ALB 层部署 WAF？

应用层的 `SecurityMiddleware` 可以防护 CORS/CSRF 攻击，但无法抵御容量型滥用——高频请求会耗尽后端资源。在应用层做限流需要额外基础设施（如 Redis 用于分布式计数），且每个请求仍然消耗 Pod 资源。

AWS WAF 运行在 ALB 层，在恶意流量**到达 EKS Pod 之前**将其拦截：

```
客户端 → (可选 Global Accelerator) → ALB + WAF → EKS Pod
                                       │
                                       ├── 超过限流阈值？ → 403（在 ALB 层拦截）
                                       ├── 已知恶意输入？ → 403（在 ALB 层拦截）
                                       └── 通过所有规则 → 转发到 Pod
```

**相比应用层限流的优势：**

| 方面 | 应用层 | AWS WAF（ALB 层） |
|------|-------|-------------------|
| 流量是否到达 Pod | 是——消耗 CPU/内存 | 否——在 Pod 之前被拦截 |
| 分布式计数 | 需要 Redis 等 | 内置（AWS 托管） |
| 托管规则集 | 需手动实现 | AWS 维护（SQLi、XSS、已知恶意输入） |
| 可扩展性 | 受限于 Pod 资源 | 随 ALB 自动扩展 |

### WAF 规则

WAF WebACL 包含 5 条规则，按优先级顺序评估：

| 优先级 | 规则名 | 类型 | 阈值 / 动作 | 目的 |
|--------|-------|------|------------|------|
| 1 | `rate-limit-auth` | 限速（路径范围） | 单 IP 20 次 / 5 分钟，作用于 `/admin/auth/*` | 防止 OAuth 暴力破解 |
| 2 | `rate-limit-chat` | 限速（路径范围） | 单 IP 300 次 / 5 分钟，作用于 `/v1/chat/completions` | 防止 API 滥用 |
| 3 | `aws-managed-common` | AWS 托管规则组 | AWSManagedRulesCommonRuleSet | SQLi、XSS 等通用攻击防护 |
| 4 | `aws-managed-known-bad-inputs` | AWS 托管规则组 | AWSManagedRulesKnownBadInputsRuleSet | 已知恶意载荷（Log4j 等） |
| 5 | `rate-limit-global` | 限速（全局） | 单 IP 2000 次 / 5 分钟 | 全局滥用防护 |

**规则评估逻辑：**

- 按优先级数字从小到大依次评估
- 路径范围限速（auth、chat）优先检查，可对敏感端点施加更严格的限制
- AWS 托管规则捕获已知攻击模式（SQLi、XSS、Log4j 等），与速率无关
- 全局限速作为兜底，拦截超过总体阈值的任何 IP
- 默认动作为 **Allow** —— 只有匹配规则条件的请求才会被拦截

### 限流阈值设计依据

| 端点 | 限制 | 依据 |
|------|------|------|
| `/admin/auth/*` | 20 次 / 5 分钟 | OAuth 登录涉及重定向和令牌交换。合法用户每次会话最多进行几次登录。低阈值可有效阻止凭证填充和暴力破解尝试。 |
| `/v1/chat/completions` | 300 次 / 5 分钟 | 每个聊天完成请求都会调用 Bedrock 模型（成本较高）。300 次 / 5 分钟（平均 1 次/秒）足以满足正常使用，同时阻止失控的脚本。 |
| 全局 | 2000 次 / 5 分钟 | 覆盖所有端点，包括静态资源、健康检查和 API 调用。对合法浏览足够宽松，但能阻止自动化扫描器和 DDoS。 |

### WAF 关联

WAF WebACL 关联到两个 ALB（由 Kubernetes ALB Controller 创建，Terraform 通过 `data "aws_lb"` 按名称发现）：

| ALB | 默认名称 | 防护范围 |
|-----|---------|---------|
| Frontend ALB | `kolya-br-proxy-frontend-alb` | 管理面板（`/admin/*`） |
| API ALB | `kolya-br-proxy-api-alb` | API 端点（`/v1/*`、`/health/*`） |

### 基础设施配置

**Terraform 模块**：`iac-612674025488-us-west-2/modules/waf/`

| 文件 | 内容 |
|------|------|
| `main.tf` | `aws_wafv2_web_acl`（WebACL + 5 条规则）和 `aws_wafv2_web_acl_association` × 2 |
| `data.tf` | 按名称自动发现 ALB |
| `variables.tf` | ALB 名称、限流阈值、项目元数据 |
| `outputs.tf` | WebACL ARN、ID |

**根模块变量**（`iac-612674025488-us-west-2/variables.tf`）：

| 变量 | 类型 | 默认值 | 说明 |
|------|------|-------|------|
| `enable_waf` | bool | `true` | 启用/禁用整个 WAF 模块 |
| `waf_frontend_alb_name` | string | `kolya-br-proxy-frontend-alb` | Frontend ALB 名称（用于自动发现） |
| `waf_api_alb_name` | string | `kolya-br-proxy-api-alb` | API ALB 名称（用于自动发现） |
| `waf_rate_limit_global` | number | `2000` | 全局限流（次 / 5 分钟） |
| `waf_rate_limit_auth` | number | `20` | 认证端点限流（次 / 5 分钟） |
| `waf_rate_limit_chat` | number | `300` | 聊天端点限流（次 / 5 分钟） |

### 监控

所有规则均启用了 CloudWatch 指标（`cloudwatch_metrics_enabled = true`）和请求采样（`sampled_requests_enabled = true`）。指标可在 AWS WAF 控制台和 CloudWatch 中查看，指标名称如下：

- `kbr-proxy-rate-limit-auth`
- `kbr-proxy-rate-limit-chat`
- `kbr-proxy-aws-managed-common`
- `kbr-proxy-aws-managed-bad-inputs`
- `kbr-proxy-rate-limit-global`
- `kbr-proxy-waf-<workspace>`（WebACL 级别默认指标）

---

## 请求流程总览

```
浏览器请求 → ALB + WAF → SecurityMiddleware → CORS Middleware → 路由处理器
                │                │
                │                ├── /health/* → 跳过检查，直接放行
                │                ├── OPTIONS → 跳过检查（CORS 预检）
                │                ├── GET/HEAD → 跳过 CSRF 检查，添加安全头
                │                └── POST/PUT/DELETE/PATCH
                │                      │
                │                      ├── 1. Origin 不在白名单？ → 403
                │                      ├── 2. Referer 无效？（如果启用）→ 403
                │                      ├── 3. 浏览器请求缺少 Authorization 和 X-Requested-With？ → 403
                │                      └── 全部通过 → 添加安全头 → 继续处理
                │
                ├── 超过限流阈值？ → 403（在 ALB 层拦截，不到达 Pod）
                ├── 匹配 AWS 托管规则？ → 403（在 ALB 层拦截）
                └── 通过所有 WAF 规则 → 转发到 Pod
```

```
API 客户端请求（无 Origin 头）→ ALB + WAF → SecurityMiddleware → 路由处理器
                                   │               │
                                   │               └── 无 Origin → 跳过 CSRF 检查
                                   │                    → Bearer Token 由路由层验证
                                   │
                                   └── WAF 规则同样适用于 API 客户端
```

---

## 环境差异

| 防护措施 | 本地开发 | 非生产环境 | 生产环境 |
|---------|---------|-----------|---------|
| AWS WAF（限流 + 托管规则） | 不适用（无 ALB） | 启用（如 ALB 存在） | 启用 |
| CORS Origin 白名单 | localhost | 非生产域名 | 严格域名白名单 |
| CSRF Origin 验证 | 启用 | 启用 | 启用 |
| X-Requested-With 检查 | 启用 | 启用 | 启用 |
| Referer 验证 | 关闭 | 关闭 | 可选启用 |
| 安全响应头 | 启用 | 启用 | 启用 |
| Swagger UI | 启用（DEBUG） | 启用（DEBUG） | 关闭 |

---

## 关键源码文件

| 文件 | 职责 |
|------|------|
| `iac-612674025488-us-west-2/modules/waf/main.tf` | AWS WAF WebACL 定义（限流 + 托管规则）和 ALB 关联 |
| `iac-612674025488-us-west-2/modules/waf/data.tf` | 按名称自动发现 ALB |
| `iac-612674025488-us-west-2/modules/waf/variables.tf` | WAF 配置变量（限流阈值、ALB 名称） |
| `backend/app/middleware/security.py` | SecurityMiddleware（Origin/Referer/自定义头验证 + 安全响应头） |
| `backend/main.py` | CORS 中间件配置、SecurityMiddleware 注册 |
| `backend/app/core/config.py` | `ALLOWED_ORIGINS` 配置和生产环境校验 |
| `backend/app/core/security.py` | JWT/API Token 生成、验证、加密 |
| `backend/app/services/oauth.py` | OAuth State 生成与验证（OAuth 登录 CSRF 防护） |
| `backend/app/models/oauth_state.py` | OAuth State 数据库模型（10 分钟过期、一次性使用） |
| `backend/app/api/admin/endpoints/auth.py` | OAuth 登录和回调端点（State 验证入口） |
| `frontend/src/boot/axios.ts` | Axios 全局配置（`X-Requested-With` 头） |

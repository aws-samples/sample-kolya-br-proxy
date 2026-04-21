# Security Design: WAF, CORS, CSRF & Token Security

This document covers the security protection design in Kolya BR Proxy, including AWS WAF (rate limiting and managed rule sets at the ALB layer), Cross-Origin Resource Sharing (CORS), Cross-Site Request Forgery (CSRF) protection, API token hashing, refresh token hardening, and JWT library choices — how these attacks work, why an API gateway must defend against them, and the specific implementation in this project.

---

## Why Does an API Gateway Need Security Protection?

Kolya BR Proxy serves two types of clients:

1. **API clients** (Cline, Cursor, OpenAI SDK) — Call `/v1/*` endpoints with Bearer Tokens
2. **Browser clients** (Vue admin dashboard) — Call `/admin/*` endpoints with JWT (Bearer Token)

This project uses a **hybrid authentication approach**: access tokens are stored in `localStorage` and sent via `Authorization: Bearer <token>` headers, while **refresh tokens are stored in HttpOnly cookies** (`kbr_refresh_token`, `Path=/admin/auth`, `SameSite=None; Secure`) to prevent XSS theft of long-lived credentials. The OAuth login flow also uses **PKCE (Proof Key for Code Exchange, S256)** to prevent authorization code interception attacks.

This project implements full CORS and CSRF protection for the following reasons:

- **Defense in Depth** — Security should never rely on a single mechanism. The HttpOnly cookie for refresh tokens requires proper CSRF protection
- **Origin validation** blocks cross-origin requests from unauthorized domains regardless of the authentication method
- **Security response headers** prevent clickjacking, MIME sniffing, XSS, and other browser-side attacks
- **Industry best practice** — OWASP recommends these protections for all web APIs regardless of the current authentication scheme

---

## CORS (Cross-Origin Resource Sharing)

### What Is CORS?

The browser's **Same-Origin Policy** blocks web pages from making requests to a different origin (protocol + domain + port) by default. CORS is a set of HTTP headers that allow servers to declare which external origins may access their resources.

### Why Must This Project Configure CORS?

The frontend and backend in this project run on **different origins**, a typical cross-origin architecture:

| Environment | Frontend (Admin Dashboard) | Backend (API) | Cross-Origin? |
|-------------|--------------------------|---------------|---------------|
| Local dev | `http://localhost:9000` | `http://localhost:8000` | Yes (different port) |
| Production | `https://kbp.kolya.fun` | `https://api.kbp.kolya.fun` | Yes (different domain) |

Per the browser's Same-Origin Policy, if **any** of protocol, domain, or port differs, the request is cross-origin. Every request from the admin dashboard to the backend API is a cross-origin request. **If the backend does not configure a CORS allowlist, the browser blocks all API calls from the frontend, and the admin dashboard cannot function at all.**

CORS configuration is therefore a **fundamental requirement** for this project — not an optional security hardening measure, but a prerequisite for the separated frontend/backend architecture to work.

However, misconfigured CORS is equally dangerous:

- **`Access-Control-Allow-Origin: *`** — Any website can read API responses, potentially leaking sensitive data
- **Overly broad allowlists** — Attackers can leverage permitted domains to launch attacks

The correct approach is to **only allow your own frontend domain** and reject all other origins.

### Attack Scenario

```
1. Admin logs into the Kolya BR Proxy dashboard (browser holds JWT)
2. Admin opens attacker's malicious site evil.com in a new tab
3. evil.com's JavaScript sends a GET request to https://api.kbp.kolya.fun/admin/tokens
4. If CORS is configured as *, the browser allows evil.com to read the response
5. Attacker obtains the full API Token list
```

### CORS Implementation

**Configuration entry**: `backend/main.py`

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins(),  # Strict allowlist
    allow_credentials=True,                         # Allow credentials
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Per-environment policy**:

| Environment | `KBR_ALLOWED_ORIGINS` | Security Level |
|-------------|----------------------|----------------|
| Local development | `http://localhost:3000,http://localhost:9000` or `*` | Relaxed (only env that allows `*`) |
| Non-production | Non-prod domains only (no wildcards) | Moderate |
| Production | Production domains only (e.g., `https://kbp.kolya.fun`) | Strict |

**Wildcard validation** (`backend/app/core/config.py`):

```python
@validator("ALLOWED_ORIGINS")
def validate_allowed_origins(cls, v, values):
    env = os.getenv("KBR_ENV", "non-prod")
    if v == "*" and env != "local":
        raise ValueError(
            f"Wildcard CORS origins ('*') not allowed in {env} environment. "
            "Only KBR_ENV=local supports '*'."
        )
    return v
```

---

## CSRF (Cross-Site Request Forgery)

### What Is CSRF?

CSRF attacks exploit the browser's automatic cookie-sending behavior to make authenticated users unknowingly submit requests to a target site. Unlike CORS, CSRF does not need to read the response — the damage is done simply by the request being executed.

### Why Can't CORS Prevent CSRF?

This is a common misconception. CORS only controls **whether the browser allows reading the response**, not whether the request is sent:

| Scenario | CORS Behavior | CSRF Risk |
|----------|--------------|-----------|
| Simple POST (`Content-Type: application/x-www-form-urlencoded`) | Browser sends directly, no preflight | **High** — request reaches server and executes |
| JSON POST (`Content-Type: application/json`) | Triggers preflight (OPTIONS); actual request blocked if preflight fails | **Low** — but depends on correct CORS config |
| GET request | No preflight, sent directly | Depends on whether GET has side effects |

For this project's JSON API, the CORS preflight mechanism provides some protection. But relying on CORS alone is insufficient:
- CORS policies can be misconfigured
- Browser behavior varies in edge cases
- Defense-in-depth requires multiple layers

### Attack Scenario

This project stores refresh tokens in HttpOnly cookies (`kbr_refresh_token`, `Path=/admin/auth`), which means the browser automatically attaches them to matching requests. This makes CSRF protection directly relevant:

```
1. Admin is logged into the Kolya BR Proxy dashboard (browser holds HttpOnly refresh token cookie)
2. Admin opens a malicious page evil.com in another tab
3. evil.com submits a hidden form POST to https://api.kbp.kolya.fun/admin/auth/refresh
   (Content-Type: application/x-www-form-urlencoded, bypasses CORS preflight)
4. Browser automatically attaches the kbr_refresh_token cookie
5. Without CSRF protection, the server would issue a new access token to the attacker
```

The three-layer CSRF defense (Origin validation + Referer check + custom header requirement) prevents this attack. Additionally, the cookie is scoped to `Path=/admin/auth`, limiting the attack surface to auth endpoints only. Access tokens are stored in localStorage and sent via `Authorization: Bearer` headers, which browsers never attach automatically.

### CSRF Protection Implementation

**Implementation file**: `backend/app/middleware/security.py` — `SecurityMiddleware`

This project uses a **three-layer defense** strategy:

#### Layer 1: Origin Validation

For all state-changing operations (POST, PUT, DELETE, PATCH), verify the `Origin` header against the allowlist:

```python
if origin and not self._is_origin_allowed(origin):
    # 403 Forbidden - Origin not allowed
```

- Browsers automatically include the `Origin` header on cross-origin requests, and JavaScript cannot forge it
- Requests from unlisted origins are immediately rejected

#### Layer 2: Referer Validation (Optional)

Verify the origin in the `Referer` header is legitimate:

```python
if self.enforce_referer and not self._validate_referer(request):
    # 403 Forbidden - Invalid referer
```

- Disabled by default (`enforce_referer=False`) as some clients do not send Referer
- Can be enabled as an additional security layer

#### Layer 3: Custom Header (X-Requested-With)

Require browser requests to include either `X-Requested-With` or `Authorization`:

```python
if self.require_custom_header and origin:
    has_auth_header = request.headers.get("authorization")
    has_custom_header = request.headers.get("x-requested-with")
    if not has_auth_header and not has_custom_header:
        # 403 Forbidden - Missing CSRF protection header
```

**Why does this prevent CSRF?**

- HTML forms and `<img>` tags cannot set custom HTTP headers
- Only JavaScript's `XMLHttpRequest` or `fetch` can add custom headers
- Cross-origin JavaScript requests trigger CORS preflight, which is blocked by the origin allowlist

**Frontend counterpart** (`frontend/src/boot/axios.ts`):

```typescript
const api = axios.create({
  headers: {
    'X-Requested-With': 'XMLHttpRequest',  // CSRF protection
  },
});
```

#### Exemption Rules

The following requests bypass CSRF checks:

| Condition | Reason |
|-----------|--------|
| `GET`, `HEAD`, `OPTIONS` methods | Safe methods that do not change server state |
| `/health/*` paths | Public health-check endpoints |
| Requests without `Origin` header | Non-browser clients (curl, SDKs) authenticated via Bearer Token |

---

## OAuth State Protection (CSRF in OAuth Login Flow)

### Why Does the OAuth Flow Need Additional CSRF Protection?

The `SecurityMiddleware` described above protects **general API requests** from CSRF. However, the OAuth login flow has a unique attack surface — the **OAuth callback endpoint**.

In the OAuth Authorization Code flow, after the user completes authentication at a third party (Microsoft / Cognito), they are redirected back to this project's callback endpoint with a `code` parameter. If an attacker can craft a malicious callback URL and trick a user into clicking it, they can:

- **Login CSRF**: Bind the victim's session to the attacker's account
- **Authorization code injection**: Replace the victim's code with one obtained by the attacker, hijacking the user's account

### Attack Scenario

```
1. Attacker initiates OAuth login and obtains a valid authorization code
2. Attacker crafts a callback URL:
   https://api.kbp.kolya.fun/admin/auth/cognito/callback?code=ATTACKER_CODE&state=...
3. Attacker tricks the victim (a logged-in admin) into clicking the link
4. Without state validation, the server accepts the attacker's code
5. The victim's browser session is bound to the attacker's OAuth identity
```

### OAuth State Implementation

**Key files**:
- `backend/app/services/oauth.py` — `OAuthService` (state generation and validation)
- `backend/app/models/oauth_state.py` — `OAuthState` (database model)
- `backend/app/api/admin/endpoints/auth.py` — Login and callback endpoints

#### Flow

```
1. User clicks login → /admin/auth/cognito/login
   │
   ├── Generate state = secrets.token_urlsafe(32)  (cryptographically secure random)
   ├── Store in database oauth_states table (with provider, expires_at)
   └── Return authorization_url (includes state parameter)

2. User completes auth at Cognito/Microsoft → redirected to callback
   │
   ├── /admin/auth/cognito/callback?code=xxx&state=yyy
   │
   ├── Validate state:
   │   ├── Database lookup: state value + provider must match
   │   ├── Expiry check: valid for 10 minutes after creation
   │   ├── One-time use: deleted from database immediately after validation
   │   └── Any check fails → 403 Forbidden
   │
   └── State validated → exchange code for token → login success
```

#### Security Properties

| Property | Implementation | Purpose |
|----------|---------------|---------|
| **Cryptographically secure random** | `secrets.token_urlsafe(32)` (256 bits of entropy) | Prevent state guessing or brute force |
| **Server-side storage** | PostgreSQL `oauth_states` table | Prevent client-side tampering |
| **Provider binding** | `state` + `provider` joint validation | Prevent cross-provider replay |
| **10-minute expiry** | `expires_at = created_at + 10min` | Minimize attack time window |
| **One-time use** | Deleted immediately after successful validation | Prevent replay attacks |
| **Expired state cleanup** | `cleanup_expired_states()` periodic cleanup | Prevent database bloat |

#### Key Code

**Generate state** (`backend/app/services/oauth.py`):

```python
async def generate_state(self, provider: str) -> tuple[str, str]:
    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(96)  # PKCE
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    oauth_state = OAuthState(state=state, provider=provider, code_verifier=code_verifier)
    self.db.add(oauth_state)
    await self.db.commit()
    return state, code_challenge
```

**Validate state** (`backend/app/services/oauth.py`):

```python
async def validate_state(self, state: str, provider: str) -> tuple[bool, str | None]:
    # Query database
    query = select(OAuthState).where(
        OAuthState.state == state, OAuthState.provider == provider
    )
    oauth_state = result.scalar_one_or_none()

    if not oauth_state or oauth_state.is_expired():
        return False, None

    code_verifier = oauth_state.code_verifier  # PKCE
    # One-time use: delete after validation
    await self.db.delete(oauth_state)
    await self.db.commit()
    return True, code_verifier
```

**Callback endpoint validation** (`backend/app/api/admin/endpoints/auth.py`):

```python
# Both Microsoft and Cognito callbacks perform the same validation
is_valid, code_verifier = await oauth_state_service.validate_state(state, "cognito")
if not is_valid:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid or expired state parameter",
    )
# code_verifier is passed to the token exchange request
```

---

## PKCE (Proof Key for Code Exchange)

### Why PKCE?

PKCE is an OAuth 2.1 best practice that prevents authorization code interception attacks. Even if an attacker intercepts the authorization code (e.g., via a malicious browser extension or redirect), they cannot exchange it for tokens without the `code_verifier`.

### Implementation

This project uses the **S256** challenge method. The entire PKCE flow is handled server-side — the frontend does not need to participate.

| Step | Action | Location |
|------|--------|----------|
| 1. Generate | `code_verifier = secrets.token_urlsafe(96)` (~128 chars) | `OAuthService.generate_state()` |
| 2. Challenge | `code_challenge = BASE64URL(SHA256(code_verifier))` | `OAuthService.generate_state()` |
| 3. Store | `code_verifier` saved in `oauth_states` DB table | `OAuthState.code_verifier` column |
| 4. Authorize | `code_challenge` + `code_challenge_method=S256` sent in auth URL | `get_authorization_url()` |
| 5. Exchange | `code_verifier` sent in token exchange request | `exchange_code_for_token()` |
| 6. Verify | IdP verifies `SHA256(code_verifier) == code_challenge` | Microsoft / Cognito server |

### Key Design Decision

Since the backend handles both the authorization URL construction and the token exchange, the `code_verifier` is stored server-side in the `oauth_states` database table (alongside the CSRF `state` parameter). This means **the frontend requires zero changes** for PKCE support.

---

## Refresh Token HttpOnly Cookie

### Why HttpOnly Cookies for Refresh Tokens?

Refresh tokens are long-lived (7 days) credentials. Storing them in `localStorage` exposes them to XSS attacks — any injected JavaScript can read `localStorage` and exfiltrate the token. HttpOnly cookies cannot be accessed by JavaScript (`document.cookie` returns nothing), providing a strong defense against XSS theft.

### Cookie Configuration

| Attribute | Value | Purpose |
|-----------|-------|---------|
| `key` | `kbr_refresh_token` | Cookie name |
| `httponly` | `true` | Prevents JavaScript access |
| `secure` | `true` (non-local) | Only sent over HTTPS |
| `samesite` | `none` (non-local) / `lax` (local) | Cross-origin required for `api.kbp.kolya.fun` ↔ `kbp.kolya.fun` |
| `path` | `/admin/auth` | Only sent to auth endpoints, not `/v1/*` |
| `max_age` | 7 days | Matches refresh token lifetime |

### Cross-Origin Considerations

The frontend (`kbp.kolya.fun`) and backend (`api.kbp.kolya.fun`) are on different subdomains. This requires:
- `SameSite=None; Secure` on the cookie (browsers require `Secure` when `SameSite=None`)
- `withCredentials: true` on the Axios client (to send cookies cross-origin)
- `allow_credentials=True` in CORS configuration (already in place)

For local development over HTTP, the cookie uses `SameSite=Lax` since `SameSite=None` requires HTTPS.

### Implementation

- **Set cookie**: `backend/app/core/cookies.py` — `set_refresh_token_cookie()`
- **Read cookie**: `backend/app/core/cookies.py` — `get_refresh_token_from_cookie()`
- **Clear cookie**: `backend/app/core/cookies.py` — `clear_refresh_token_cookie()`
- **Backward compatibility**: The `/admin/auth/refresh` and `/admin/auth/revoke` endpoints accept refresh tokens from both cookies (preferred) and request body (legacy)

---

## Security Response Headers

In addition to CORS and CSRF protection, `SecurityMiddleware` adds security headers to every response:

| Header | Value | Purpose |
|--------|-------|---------|
| `X-Content-Type-Options` | `nosniff` | Prevent browser MIME-type sniffing |
| `X-Frame-Options` | `DENY` | Prevent clickjacking |
| `X-XSS-Protection` | `1; mode=block` | Enable browser XSS filter |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Control Referer information leakage |
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'` | Restrict resource loading, prevent injection |
| `Cache-Control` | `no-cache, no-store, must-revalidate` | Prevent caching of sensitive data |

---

## AWS WAF (Web Application Firewall)

### Why WAF at the ALB Layer?

The application-layer `SecurityMiddleware` protects against CORS/CSRF attacks, but it cannot defend against volumetric abuse — high-frequency requests that overwhelm backend resources. Rate limiting at the application layer requires additional infrastructure (e.g., Redis for distributed counters) and still consumes Pod resources for every request.

AWS WAF operates at the ALB layer, intercepting malicious traffic **before it reaches EKS Pods**:

```
Client → (Optional Global Accelerator) → ALB + WAF → EKS Pod
                                           │
                                           ├── Rate limit exceeded? → 403 (blocked at ALB)
                                           ├── Known bad input? → 403 (blocked at ALB)
                                           └── Passed all rules → Forward to Pod
```

**Advantages over application-layer rate limiting:**

| Aspect | Application Layer | AWS WAF (ALB Layer) |
|--------|------------------|---------------------|
| Traffic reaches Pod | Yes — consumes CPU/memory | No — blocked before Pod |
| Distributed counting | Requires Redis or similar | Built-in (AWS-managed) |
| Managed rule sets | Manual implementation | AWS-maintained (SQLi, XSS, known bad inputs) |
| Scalability | Limited by Pod resources | Scales with ALB |

### WAF Rules

The WAF WebACL contains five rules, evaluated in priority order:

| Priority | Rule | Type | Threshold / Action | Purpose |
|----------|------|------|--------------------|---------|
| 1 | `rate-limit-auth` | Rate-based (scoped) | 20 req / 5 min per IP on `/admin/auth/*` | Prevent OAuth brute force |
| 2 | `rate-limit-chat` | Rate-based (scoped) | 300 req / 5 min per IP on `/v1/chat/completions` | Prevent API abuse |
| 3 | `aws-managed-common` | AWS Managed Rule Group | AWSManagedRulesCommonRuleSet (some rules overridden to Count) | SQLi, XSS, and other common exploits |
| 4 | `aws-managed-known-bad-inputs` | AWS Managed Rule Group | AWSManagedRulesKnownBadInputsRuleSet | Known malicious payloads (Log4j, etc.) |
| 5 | `rate-limit-global` | Rate-based (global) | 2000 req / 5 min per IP | Global abuse prevention |

**Rule evaluation logic:**

- Rules are evaluated from lowest to highest priority number
- Path-scoped rate limits (auth, chat) are checked first so they can enforce tighter limits on sensitive endpoints
- AWS Managed Rules catch known attack patterns (SQLi, XSS, Log4j, etc.) regardless of rate
- The global rate limit acts as a catch-all for any IP exceeding overall thresholds
- Default action is **Allow** — only requests matching a rule's condition are blocked

#### Rule 3 Exclusions (`rule_action_override` → Count)

Certain rules in `AWSManagedRulesCommonRuleSet` produce false positives on legitimate LLM API traffic. The following rules are overridden to **Count** (log only, no block) via `rule_action_override`:

| Excluded Rule | False Positive Scenario | Rationale |
|--------------|------------------------|-----------|
| `SizeRestrictions_BODY` | Agent loop request bodies (system prompt + tool definitions + multi-turn conversation history) exceed the 8KB limit | LLM request bodies are inherently large; the 8KB threshold is unsuitable for this API |
| `CrossSiteScripting_BODY` | Code snippets in user messages contain `<script>` tags, triggering XSS false positives | Chat content containing code is a normal use case, and the API does not render HTML |
| `NoUserAgent_HEADER` | Some SDK clients (OpenCode, etc.) do not send a `User-Agent` header | API clients may not send User-Agent; requests are already authenticated via Bearer Token |

**Security assurance:** The `/v1/chat/completions` path is protected by Bearer Token authentication + IP rate limiting (300 req / 5 min). Downgrading these rules does not reduce actual security but prevents false-positive blocking of normal LLM traffic.

**Excluded rules still operate in Count mode**, so their trigger frequency can be monitored in CloudWatch metrics. If anomalous patterns are detected, they can be restored to Block at any time.

### Rate Limit Design Rationale

| Endpoint | Limit | Rationale |
|----------|-------|-----------|
| `/admin/auth/*` | 20 / 5 min | OAuth login involves redirects and token exchange. Legitimate users perform at most a few logins per session. A low limit effectively blocks credential-stuffing and brute-force attempts. |
| `/v1/chat/completions` | 300 / 5 min | Each chat completion request invokes a Bedrock model call (costly). 300 per 5 minutes (1 req/sec average) is sufficient for normal usage while preventing runaway scripts. |
| Global | 2000 / 5 min | Covers all endpoints including static assets, health checks, and API calls. Generous enough for legitimate browsing but blocks automated scanners and DDoS. |

### WAF Association

The WAF WebACL is associated with two ALBs (created by Kubernetes ALB Controller, discovered by name via Terraform `data "aws_lb"`):

| ALB | Default Name | Protects |
|-----|-------------|----------|
| Frontend ALB | `kolya-br-proxy-frontend-alb` | Admin dashboard (`/admin/*`) |
| API ALB | `kolya-br-proxy-api-alb` | API endpoints (`/v1/*`, `/health/*`) |

### Infrastructure Configuration

**Terraform module**: `iac/modules/waf/`

| File | Contents |
|------|----------|
| `main.tf` | `aws_wafv2_web_acl` (WebACL + 5 rules) and `aws_wafv2_web_acl_association` × 2 |
| `data.tf` | ALB auto-discovery by name |
| `variables.tf` | ALB names, rate limit thresholds, project metadata |
| `outputs.tf` | WebACL ARN, ID |

**Root module variables** (`iac/variables.tf`):

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `enable_waf` | bool | `true` | Enable/disable the entire WAF module |
| `waf_frontend_alb_name` | string | `kolya-br-proxy-frontend-alb` | Frontend ALB name for auto-discovery |
| `waf_api_alb_name` | string | `kolya-br-proxy-api-alb` | API ALB name for auto-discovery |
| `waf_rate_limit_global` | number | `2000` | Global rate limit (req / 5 min) |
| `waf_rate_limit_auth` | number | `20` | Auth endpoint rate limit (req / 5 min) |
| `waf_rate_limit_chat` | number | `300` | Chat endpoint rate limit (req / 5 min) |

### Monitoring

All rules have CloudWatch metrics enabled (`cloudwatch_metrics_enabled = true`) and request sampling (`sampled_requests_enabled = true`). Metrics are available in the AWS WAF Console and CloudWatch under the following metric names:

- `kbr-proxy-rate-limit-auth`
- `kbr-proxy-rate-limit-chat`
- `kbr-proxy-aws-managed-common`
- `kbr-proxy-aws-managed-bad-inputs`
- `kbr-proxy-rate-limit-global`
- `kbr-proxy-waf-<workspace>` (WebACL-level default metric)

---

## Request Flow Overview

```
Browser Request → ALB + WAF → SecurityMiddleware → CORS Middleware → Route Handler
                    │                │
                    │                ├── /health/* → Skip checks, pass through
                    │                ├── OPTIONS → Skip checks (CORS preflight)
                    │                ├── GET/HEAD → Skip CSRF checks, add security headers
                    │                └── POST/PUT/DELETE/PATCH
                    │                      │
                    │                      ├── 1. Origin not in allowlist? → 403
                    │                      ├── 2. Invalid Referer? (if enabled) → 403
                    │                      ├── 3. Browser request missing Authorization and X-Requested-With? → 403
                    │                      └── All passed → Add security headers → Continue processing
                    │
                    ├── Rate limit exceeded? → 403 (blocked at ALB, never reaches Pod)
                    ├── Matches AWS Managed Rule? → 403 (blocked at ALB)
                    └── Passed all WAF rules → Forward to Pod
```

```
API Client Request (no Origin header) → ALB + WAF → SecurityMiddleware → Route Handler
                                           │               │
                                           │               └── No Origin → Skip CSRF checks
                                           │                    → Bearer Token validated at route layer
                                           │
                                           └── WAF rules apply equally to API clients
```

---

## Environment Differences

| Protection | Local Dev | Non-Production | Production |
|-----------|-----------|---------------|------------|
| AWS WAF (rate limiting + managed rules) | N/A (no ALB) | Enabled (if ALB exists) | Enabled |
| CORS Origin allowlist | localhost | Non-prod domains | Strict domain allowlist |
| CSRF Origin validation | Enabled | Enabled | Enabled |
| X-Requested-With check | Enabled | Enabled | Enabled |
| Referer validation | Disabled | Disabled | Optionally enabled |
| Security response headers | Enabled | Enabled | Enabled |
| Swagger UI | Enabled (DEBUG) | Enabled (DEBUG) | Disabled |

---

## Secrets Management

### Architecture

Secrets are managed through **AWS Secrets Manager** with **External Secrets Operator (ESO)** syncing them into Kubernetes. This replaces local `secrets.yaml` files and ensures secrets never exist in version control.

### How It Works

```
deploy-all.sh
  ├── aws secretsmanager put-secret-value  →  AWS Secrets Manager
  │                                              (single source of truth)
  │
  └── kubectl apply ExternalSecret CRDs
        ↓
      External Secrets Operator (ESO)
        ├── Authenticates via Pod Identity (no static AWS creds)
        ├── Reads secrets from AWS Secrets Manager
        ├── Creates/updates Kubernetes Secrets (refreshInterval: 1h)
        └── Backend Pods consume secrets via envFrom / env references
```

### Security Properties

| Property | Implementation |
|----------|---------------|
| **No secrets in Git** | Secrets stored in AWS Secrets Manager, not in `secrets.yaml` or Helm values |
| **Automatic sync** | ESO refreshes every 1 hour (`refreshInterval: 1h`), picking up rotations automatically |
| **IAM-based access** | ESO authenticates via EKS Pod Identity -- no static `AWS_ACCESS_KEY_ID` needed |
| **Deployment push** | `deploy-all.sh` pushes secrets via `aws secretsmanager put-secret-value` |
| **Least privilege** | ESO IAM role only has `secretsmanager:GetSecretValue` for specific secret ARNs |

### Managed Secrets

| Secret | Contents |
|--------|----------|
| Database credentials | `DATABASE_URL` (Aurora PostgreSQL connection string) |
| JWT signing key | `KBR_JWT_SECRET_KEY` (Fernet encryption + JWT signing) |
| OAuth client secrets | Cognito and Microsoft OAuth client secrets |
| Token encryption key | Used for API token Fernet encryption/decryption |

---

## API Token Hashing

### Design

API tokens are hashed before storage using **PBKDF2-HMAC-SHA256** with **600,000 iterations**, keyed with `JWT_SECRET_KEY`. This approach evolved through several iterations (SHA256 → HMAC-SHA256 → BLAKE2b → SHA3 → PBKDF2) to balance security and performance.

The hashing scheme serves two purposes:

1. **Secure storage** — Even if the database is compromised, the original tokens cannot be recovered from the hashes
2. **Fast lookup** — The hash is deterministic (same input always produces the same output), so it is indexed in the database for O(1) lookup by hash

Additionally, tokens are **encrypted with Fernet** (AES-128-CBC) using a key derived from `JWT_SECRET_KEY`. This allows administrators to retrieve the original token value when needed (e.g., for display in the admin dashboard), while the hash is used for authentication lookups.

### Dual Storage Strategy

| Field | Algorithm | Purpose |
|-------|-----------|---------|
| `token_hash` | PBKDF2-HMAC-SHA256 (600k iterations, keyed) | Authentication lookup (indexed) |
| `encrypted_token` | Fernet (AES-128-CBC) | Admin retrieval of original token |

### Why PBKDF2 Over Plain SHA256?

Plain SHA256 is fast — an attacker with a leaked database can brute-force token hashes at billions of attempts per second. PBKDF2 with 600,000 iterations makes each attempt computationally expensive, increasing the cost of offline attacks by orders of magnitude. The `JWT_SECRET_KEY` as salt adds a server-side secret that an attacker must also possess to mount an offline attack.

### Key Files

- `backend/app/core/security.py` — `hash_token()`, `verify_token()`, `encrypt_token()`, `decrypt_token()`
- `backend/app/core/redis.py` — `RedisCache` wrapper with JSON serialization and graceful degradation
- `backend/app/services/token.py` — Token creation and validation service
- `backend/app/services/token_cache.py` — `CachedTokenService` with Redis cache (TTL 300s) and DB fallback

---

## Refresh Token Security Hardening

### PBKDF2 Hashing for Refresh Tokens

Refresh tokens (JWT strings) are hashed with **PBKDF2-HMAC-SHA256** using **100,000 iterations** before storage. This was increased from 1 iteration to 100,000 to provide meaningful resistance against offline brute-force attacks if the database is compromised.

The hash is deterministic and keyed with `JWT_SECRET_KEY`, allowing efficient lookup while preventing offline attacks without the server secret.

### Row-Level Locking for Token Rotation

Refresh token rotation (issuing a new refresh token and invalidating the old one) uses **row-level locking** (`SELECT ... FOR UPDATE`) to prevent race conditions. Without this, concurrent requests using the same refresh token could both succeed, creating duplicate active tokens and breaking the rotation chain.

The locking ensures that only one concurrent request can rotate a given refresh token — subsequent requests using the same token see it as already consumed and are rejected.

### Key Files

- `backend/app/core/security.py` — `hash_refresh_token()`
- `backend/app/api/admin/endpoints/auth.py` — Refresh endpoint with row-level locking

---

## JWT Library Migration

### python-jose → PyJWT

The project migrated from **python-jose** to **PyJWT** for JWT encoding and decoding. The primary reasons:

| Aspect | python-jose | PyJWT |
|--------|------------|-------|
| **Maintenance** | Largely unmaintained | Actively maintained |
| **Security** | Known ecdsa timing attack vulnerability | No known vulnerabilities |
| **Compatibility** | Lagging behind Python versions | Up-to-date |

The migration was a drop-in replacement at the API level. The project enforces an **algorithm whitelist** (`HS256`, `HS384`, `HS512`) to prevent algorithm confusion attacks, regardless of library.

### Key Files

- `backend/app/core/security.py` — JWT encoding/decoding with PyJWT (`import jwt`)

---

## Key Source Files

| File | Responsibility |
|------|---------------|
| `iac/modules/waf/main.tf` | AWS WAF WebACL definition (rate limiting + managed rules) and ALB association |
| `iac/modules/waf/data.tf` | ALB auto-discovery by name |
| `iac/modules/waf/variables.tf` | WAF configuration variables (rate limits, ALB names) |
| `backend/app/middleware/security.py` | SecurityMiddleware (Origin/Referer/custom header validation + security response headers) |
| `backend/main.py` | CORS middleware configuration, SecurityMiddleware registration |
| `backend/app/core/config.py` | `ALLOWED_ORIGINS` configuration and production validation |
| `backend/app/core/security.py` | JWT/API Token generation, PBKDF2 hashing, verification, Fernet encryption |
| `backend/app/services/token.py` | API Token CRUD service (hash + encrypt on create, hash lookup on validate) |
| `backend/app/services/token_cache.py` | Cached token validation by hash |
| `backend/app/services/oauth.py` | OAuth State generation and validation (CSRF + PKCE) |
| `backend/app/models/oauth_state.py` | OAuth State database model (10-minute expiry, one-time use, PKCE code_verifier) |
| `backend/app/core/cookies.py` | HttpOnly cookie utilities for refresh token storage |
| `backend/app/api/admin/endpoints/auth.py` | OAuth login and callback endpoints (PKCE + cookie handling) |
| `frontend/src/boot/axios.ts` | Axios global config (`X-Requested-With` header, `withCredentials: true`) |

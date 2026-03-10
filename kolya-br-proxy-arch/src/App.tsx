import React, { useState } from "react";

const COLORS = {
  bg: "#0f1117",
  surface: "#1a1d27",
  border: "#2e3248",
  accent: "#6c8aff",
  accentSoft: "#2a3260",
  green: "#4ade80",
  greenSoft: "#1a3a2a",
  amber: "#fbbf24",
  amberSoft: "#3a2e10",
  red: "#f87171",
  redSoft: "#3a1a1a",
  cyan: "#22d3ee",
  cyanSoft: "#0f2d35",
  purple: "#c084fc",
  purpleSoft: "#2a1a40",
  orange: "#fb923c",
  orangeSoft: "#3a2010",
  text: "#e2e8f0",
  textMuted: "#94a3b8",
  textDim: "#64748b",
};

type LayerKey = "client" | "ingress" | "frontend" | "backend" | "infra" | "aws";

const LAYERS: { key: LayerKey; label: string; color: string; soft: string }[] = [
  { key: "client", label: "Client / End User", color: COLORS.accent, soft: COLORS.accentSoft },
  { key: "ingress", label: "Kubernetes Ingress", color: COLORS.cyan, soft: COLORS.cyanSoft },
  { key: "frontend", label: "Frontend (Vue / Quasar)", color: COLORS.green, soft: COLORS.greenSoft },
  { key: "backend", label: "Backend (FastAPI)", color: COLORS.purple, soft: COLORS.purpleSoft },
  { key: "infra", label: "Infrastructure (Terraform / EKS)", color: COLORS.amber, soft: COLORS.amberSoft },
  { key: "aws", label: "AWS Services", color: COLORS.red, soft: COLORS.redSoft },
];

// ─── Detail panels ────────────────────────────────────────────────────────────

function Card({ color, title, children }: { color: string; title: string; children: React.ReactNode }) {
  return (
    <div style={{ background: COLORS.bg, padding: 10, borderRadius: 6, border: `1px solid ${COLORS.border}` }}>
      <div style={{ color, fontWeight: 600, fontSize: 13, marginBottom: 6 }}>{title}</div>
      <div style={{ color: COLORS.textMuted, fontSize: 12, lineHeight: 1.6 }}>{children}</div>
    </div>
  );
}

function Tag({ color, children }: { color: string; children: React.ReactNode }) {
  return (
    <span style={{
      display: "inline-block",
      background: COLORS.bg,
      border: `1px solid ${color}55`,
      color,
      borderRadius: 4,
      padding: "1px 6px",
      fontSize: 11,
      marginRight: 4,
      marginBottom: 3,
    }}>{children}</span>
  );
}

const DETAIL: Record<LayerKey, React.ReactNode> = {
  client: (
    <div>
      <h3 style={{ color: COLORS.accent, marginBottom: 8 }}>Client / End User</h3>
      <p style={{ color: COLORS.textMuted, marginBottom: 12, fontSize: 13 }}>
        任何 OpenAI 兼容客户端（curl、Python SDK、IDE 插件等）通过 HTTPS 连接。
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <Card color={COLORS.accent} title="API 客户端">
          发送 <code>POST /v1/chat/completions</code><br/>
          Header: <code>Authorization: Bearer &lt;token&gt;</code><br/>
          支持 SSE 流式响应 / JSON 响应
        </Card>
        <Card color={COLORS.accent} title="Admin 浏览器">
          访问前端 SPA 管理界面<br/>
          使用 Cognito / Microsoft OAuth 登录<br/>
          发送 <code>X-Requested-With: XMLHttpRequest</code>
        </Card>
      </div>
    </div>
  ),

  ingress: (
    <div>
      <h3 style={{ color: COLORS.cyan, marginBottom: 8 }}>Kubernetes Ingress (AWS ALB)</h3>
      <p style={{ color: COLORS.textMuted, marginBottom: 12, fontSize: 13 }}>
        AWS ALB Ingress Controller 处理 TLS 终止和路由分发。
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <Card color={COLORS.cyan} title="ingress-api.yaml">
          路由 <code>/v1/*</code> → backend:8000<br/>
          路由 <code>/admin/*</code> → backend:8000<br/>
          路由 <code>/health</code> → backend:8000<br/>
          TLS 由 ACM 证书终止
        </Card>
        <Card color={COLORS.cyan} title="ingress-frontend.yaml">
          路由 <code>/*</code> → frontend:80<br/>
          Nginx 静态文件服务<br/>
          SPA fallback → index.html
        </Card>
        <Card color={COLORS.red} title="AWS Global Accelerator">
          Anycast IP，全球低延迟接入<br/>
          健康检查自动故障转移<br/>
          流量引导至 ALB
        </Card>
        <Card color={COLORS.cyan} title="HPA 弹性扩缩">
          Backend HPA：按 CPU/内存扩缩<br/>
          Frontend HPA：按流量扩缩<br/>
          Karpenter 自动添加节点
        </Card>
      </div>
    </div>
  ),

  frontend: (
    <div>
      <h3 style={{ color: COLORS.green, marginBottom: 8 }}>Frontend — Vue 3 + Quasar</h3>
      <p style={{ color: COLORS.textMuted, marginBottom: 12, fontSize: 13 }}>
        Admin SPA，Nginx 容器运行在 Kubernetes 中。
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <Card color={COLORS.green} title="Pages">
          LoginPage · DashboardPage<br/>
          ModelsPage · MonitorPage<br/>
          PlaygroundPage · TokensPage · SettingsPage<br/>
          CognitoCallbackPage · MicrosoftCallbackPage
        </Card>
        <Card color={COLORS.green} title="Stores (Pinia)">
          auth — 登录状态 / JWT token<br/>
          dashboard — 用量统计<br/>
          models — 模型列表<br/>
          monitor — 系统监控<br/>
          tokens — API key 管理
        </Card>
        <Card color={COLORS.green} title="OAuth 登录流">
          1. 跳转 Cognito / Microsoft 授权页<br/>
          2. 回调携带 code<br/>
          3. 前端 callback page 发送 code → 后端<br/>
          4. 后端换取 JWT，存入 auth store
        </Card>
        <Card color={COLORS.green} title="CSRF 防护（前端侧）">
          所有 axios 请求自动携带<br/>
          <code>X-Requested-With: XMLHttpRequest</code><br/>
          告知后端这是合法 AJAX 请求
        </Card>
      </div>
    </div>
  ),

  backend: (
    <div>
      <h3 style={{ color: COLORS.purple, marginBottom: 8 }}>Backend — FastAPI (Python)</h3>
      <p style={{ color: COLORS.textMuted, marginBottom: 12, fontSize: 13 }}>
        核心 AI 网关。OpenAI 兼容 API，代理至 AWS Bedrock Claude。
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <Card color={COLORS.purple} title="API 路由">
          <code>/v1/chat/completions</code> — AI 聊天<br/>
          <code>/v1/models</code> — 模型列表<br/>
          <code>/admin/tokens</code> — API key 管理<br/>
          <code>/admin/usage</code> — 用量统计<br/>
          <code>/admin/pricing</code> — 定价管理<br/>
          <code>/admin/monitor</code> · <code>/admin/audit</code>
        </Card>
        <Card color={COLORS.purple} title="核心服务">
          BedrockClient — AWS Bedrock 代理<br/>
          Translator — OpenAI ↔ Bedrock 格式转换<br/>
          AuthService — API token 验证<br/>
          CognitoOAuth / MicrosoftOAuth<br/>
          PricingUpdater — AWS 定价同步<br/>
          AuditLog · UsageStats · TokenCache
        </Card>
        <Card color={COLORS.purple} title="数据模型 (SQLAlchemy)">
          User · Token · RefreshToken<br/>
          Usage · AuditLog<br/>
          ModelPricing · SystemConfig · OAuthState
        </Card>
        <Card color={COLORS.purple} title="后台任务">
          APScheduler 定时任务<br/>
          每日同步 AWS Pricing API<br/>
          更新 ModelPricing 表<br/>
          Alembic 管理 DB schema 迁移
        </Card>
      </div>

      {/* SecurityMiddleware 内嵌在 Backend 详情里 */}
      <div style={{ marginTop: 14, border: `1px solid ${COLORS.orange}44`, borderRadius: 8, padding: 12 }}>
        <div style={{ color: COLORS.orange, fontWeight: 700, fontSize: 13, marginBottom: 10 }}>
          SecurityMiddleware — <code style={{ fontSize: 11 }}>app/middleware/security.py</code>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
          {/* CORS */}
          <div>
            <div style={{ color: COLORS.orange, fontWeight: 600, fontSize: 12, marginBottom: 6 }}>CORS 跨域防护</div>
            <div style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, borderRadius: 6, padding: 8, fontSize: 12, color: COLORS.textMuted, lineHeight: 1.7 }}>
              <code>KBR_ALLOWED_ORIGINS</code> 白名单控制<br/>
              不匹配 Origin → 403<br/>
              <br/>
              <span style={{ color: COLORS.green, fontSize: 11 }}>✓ prod：</span><br/>
              <span style={{ fontSize: 11 }}><code>https://kbp.kolya.fun</code></span><br/>
              <span style={{ fontSize: 11 }}><code>https://api.kbp.kolya.fun</code></span><br/>
              <br/>
              <span style={{ color: COLORS.amber, fontSize: 11 }}>⚠ non-prod：上述两个 + <code>*</code></span><br/>
              <span style={{ color: COLORS.amber, fontSize: 11 }}>允许所有来源，仅用于调试</span>
            </div>
          </div>
          {/* CSRF */}
          <div>
            <div style={{ color: COLORS.orange, fontWeight: 600, fontSize: 12, marginBottom: 6 }}>CSRF 伪造防护</div>
            <div style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, borderRadius: 6, padding: 8, fontSize: 12, color: COLORS.textMuted, lineHeight: 1.7 }}>
              CSRF 层：有其一即通过<br/>
              <code>Authorization: Bearer token</code><br/>
              或 <code>X-Requested-With: XMLHttpRequest</code><br/>
              <br/>
              <span style={{ color: COLORS.amber, fontSize: 11 }}>⚠ 注意：X-Requested-With 仅能绕过</span><br/>
              <span style={{ color: COLORS.amber, fontSize: 11 }}>CSRF 这一层，后续 AuthService</span><br/>
              <span style={{ color: COLORS.amber, fontSize: 11 }}>仍会要求 Bearer token，否则 401</span>
            </div>
          </div>
        </div>

        <div style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, borderRadius: 6, padding: 8 }}>
          <div style={{ color: COLORS.textDim, fontSize: 11, marginBottom: 6 }}>dispatch() 检查流程（POST / PUT / DELETE / PATCH）</div>
          {[
            [COLORS.orange, "① Origin 白名单检查 — 不在列表 → 403"],
            [COLORS.orange, "② Referer 验证（enforce_referer=True 时启用）"],
            [COLORS.orange, "③ 有 Origin 时：需有 Authorization 或 X-Requested-With，否则 → 403"],
            [COLORS.green,  "④ CSRF 通过 → 放行至 route handler"],
            [COLORS.purple, "⑤ AuthService 验证 Bearer token — 无论③走哪条路，此处都必须有效 token"],
          ].map(([color, text]) => (
            <div key={text as string} style={{ display: "flex", gap: 6, marginBottom: 4, alignItems: "flex-start" }}>
              <div style={{ width: 6, height: 6, borderRadius: "50%", background: color as string, flexShrink: 0, marginTop: 5 }} />
              <div style={{ color: COLORS.textMuted, fontSize: 11 }}>{text as string}</div>
            </div>
          ))}
        </div>

        <div style={{ marginTop: 8, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <div style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, borderRadius: 6, padding: 8 }}>
            <div style={{ color: COLORS.textDim, fontSize: 11, marginBottom: 4 }}>安全响应头</div>
            <div style={{ fontSize: 11, color: COLORS.textMuted, lineHeight: 1.7 }}>
              <code>X-Frame-Options: DENY</code><br/>
              <code>X-Content-Type-Options: nosniff</code><br/>
              <code>X-XSS-Protection: 1; mode=block</code><br/>
              <code>Content-Security-Policy: default-src 'none'</code>
            </div>
          </div>
          <div style={{ background: COLORS.amberSoft, border: `1px solid ${COLORS.amber}44`, borderRadius: 6, padding: 8 }}>
            <div style={{ color: COLORS.amber, fontSize: 11, fontWeight: 600, marginBottom: 4 }}>⚠ non-prod 有 * 风险</div>
            <div style={{ fontSize: 11, color: COLORS.textMuted, lineHeight: 1.7 }}>
              <code>.env.non-prod</code> 末尾含 <code>*</code><br/>
              <code>KBR_ENV=prod</code> + <code>*</code> 时触发<br/>
              <code>logger.error</code> 安全告警<br/>
              确保 non-prod 配置不流入生产
            </div>
          </div>
        </div>
      </div>
    </div>
  ),

  infra: (
    <div>
      <h3 style={{ color: COLORS.amber, marginBottom: 8 }}>Infrastructure — Terraform + EKS</h3>
      <p style={{ color: COLORS.textMuted, marginBottom: 12, fontSize: 13 }}>
        AWS 账号 612674025488 / us-west-2。IaC 由 Terraform 管理。
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <Card color={COLORS.amber} title="Terraform 模块">
          vpc — VPC、子网、NAT GW<br/>
          eks-karpenter — 节点自动扩缩<br/>
          eks-addons — ALB controller、CoreDNS<br/>
          cognito — User Pool & App Client<br/>
          rds-aurora-postgresql — DB 集群<br/>
          global-accelerator — Anycast IP
        </Card>
        <Card color={COLORS.amber} title="Kubernetes 资源">
          Namespace: kolya-br-proxy<br/>
          Backend Deployment + HPA<br/>
          Frontend Deployment + HPA<br/>
          ConfigMaps · Secrets · Services<br/>
          Karpenter NodePool 自动节点调度
        </Card>
        <Card color={COLORS.amber} title="AWS Pod Identity">
          Backend Pod 通过 Pod Identity<br/>
          获取 IAM Role 凭证<br/>
          无需硬编码 AWS_ACCESS_KEY_ID<br/>
          最小权限访问 Bedrock / RDS
        </Card>
        <Card color={COLORS.amber} title="镜像构建">
          build-and-push.sh → ECR<br/>
          push-to-ecr.sh 推送镜像<br/>
          deploy-all.sh 一键部署<br/>
          k8s/deploy.sh 更新 Deployment
        </Card>
      </div>
    </div>
  ),

  aws: (
    <div>
      <h3 style={{ color: COLORS.red, marginBottom: 8 }}>AWS Services</h3>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <Card color={COLORS.red} title="Bedrock (Claude)">
          Anthropic Claude 3.x / 3.5 / 等模型<br/>
          InvokeModelWithResponseStream API<br/>
          IAM Role（Pod Identity）访问<br/>
          Semaphore 限制并发（默认 50）
        </Card>
        <Card color={COLORS.red} title="Aurora PostgreSQL">
          用户、Token、RefreshToken<br/>
          Usage 用量记录、AuditLog 审计<br/>
          ModelPricing 定价表、SystemConfig<br/>
          AsyncPG 异步驱动，连接池 10+20
        </Card>
        <Card color={COLORS.red} title="Cognito">
          OAuth2 / OIDC 用户池<br/>
          支持社交身份联合登录<br/>
          发放 JWT access / refresh token<br/>
          Terraform 模块管理 User Pool
        </Card>
        <Card color={COLORS.red} title="EKS">
          托管 Kubernetes 控制平面<br/>
          Karpenter 节点自动扩缩<br/>
          Fargate 运行系统工作负载<br/>
          ALB Ingress Controller 插件
        </Card>
        <Card color={COLORS.red} title="ECR">
          Docker 镜像仓库<br/>
          Backend + Frontend 镜像<br/>
          build-and-push.sh 自动构建推送
        </Card>
        <Card color={COLORS.red} title="Global Accelerator">
          Anycast IP 全球接入<br/>
          低延迟全球路由<br/>
          健康检查自动故障转移
        </Card>
      </div>
    </div>
  ),
};

// ─── Sub-components ───────────────────────────────────────────────────────────

function Arrow({ label }: { label: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", margin: "4px 0" }}>
      {label && <div style={{ color: COLORS.textDim, fontSize: 11, marginBottom: 2 }}>{label}</div>}
      <svg width="14" height="20" viewBox="0 0 14 20">
        <line x1="7" y1="0" x2="7" y2="14" stroke={COLORS.textDim} strokeWidth="1.5" />
        <polygon points="7,20 3,12 11,12" fill={COLORS.textDim} />
      </svg>
    </div>
  );
}

function Box({
  layer, title, items, active, onClick,
}: {
  layer: LayerKey; title: string; items: string[]; active: boolean; onClick: () => void;
}) {
  const meta = LAYERS.find((l) => l.key === layer)!;
  return (
    <div onClick={onClick} style={{
      background: active ? meta.soft : COLORS.surface,
      border: `1.5px solid ${active ? meta.color : COLORS.border}`,
      borderRadius: 10, padding: "11px 14px", cursor: "pointer",
      transition: "all 0.15s",
      boxShadow: active ? `0 0 0 2px ${meta.color}44` : "none",
    }}>
      <div style={{ color: meta.color, fontWeight: 700, fontSize: 13, marginBottom: 6 }}>{title}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
        {items.map((item) => (
          <span key={item} style={{
            background: COLORS.bg, border: `1px solid ${COLORS.border}`,
            borderRadius: 4, padding: "2px 6px", fontSize: 11, color: COLORS.textMuted,
          }}>{item}</span>
        ))}
      </div>
    </div>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

export default function App() {
  const [active, setActive] = useState<LayerKey | null>(null);
  const toggle = (key: LayerKey) => setActive((prev) => (prev === key ? null : key));

  return (
    <div style={{ background: COLORS.bg, minHeight: "100vh", fontFamily: "'JetBrains Mono', 'Fira Code', monospace", color: COLORS.text }}>
      <div style={{ maxWidth: 1020, margin: "0 auto", padding: "28px 16px" }}>

        {/* Header */}
        <div style={{ marginBottom: 24 }}>
          <h1 style={{ fontSize: 20, fontWeight: 800, color: COLORS.text, margin: 0 }}>kolya-br-proxy</h1>
          <p style={{ color: COLORS.textMuted, fontSize: 12, margin: "3px 0 0" }}>
            AI Gateway — OpenAI-compatible proxy for AWS Bedrock Claude models
          </p>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: 20 }}>

          {/* Left: Architecture diagram */}
          <div>
            <div style={{ fontSize: 10, color: COLORS.textDim, marginBottom: 8, letterSpacing: "0.08em", textTransform: "uppercase" }}>
              点击层级查看详情
            </div>

            <Box layer="client" title="Client / End User"
              items={["OpenAI SDK", "curl", "IDE plugin", "Admin Browser"]}
              active={active === "client"} onClick={() => toggle("client")} />

            <Arrow label="HTTPS / TLS" />

            {/* Global Accelerator inline */}
            <div onClick={() => toggle("aws")} style={{
              background: active === "aws" ? COLORS.redSoft : COLORS.surface,
              border: `1.5px solid ${active === "aws" ? COLORS.red : COLORS.border}`,
              borderRadius: 10, padding: "7px 14px", cursor: "pointer", textAlign: "center",
            }}>
              <span style={{ color: COLORS.red, fontSize: 12, fontWeight: 600 }}>AWS Global Accelerator</span>
              <span style={{ color: COLORS.textDim, fontSize: 11, marginLeft: 8 }}>anycast IPs</span>
            </div>

            <Arrow label="ALB routing" />

            <Box layer="ingress" title="Kubernetes Ingress (ALB)"
              items={["ingress-api.yaml", "ingress-frontend.yaml", "TLS / ACM"]}
              active={active === "ingress"} onClick={() => toggle("ingress")} />

            <Arrow label="" />

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 0 }}>
              <Box layer="frontend" title="Frontend"
                items={["Vue 3", "Quasar", "Nginx", "Pinia"]}
                active={active === "frontend"} onClick={() => toggle("frontend")} />
              <Box layer="backend" title="Backend"
                items={["FastAPI", "Uvicorn", "SQLAlchemy", "SecurityMiddleware"]}
                active={active === "backend"} onClick={() => toggle("backend")} />
            </div>

            <Arrow label="AWS SDK / boto3" />

            <Box layer="infra" title="Kubernetes (EKS) + Terraform IaC"
              items={["EKS", "Karpenter", "HPA", "ECR", "Terraform"]}
              active={active === "infra"} onClick={() => toggle("infra")} />

            <Arrow label="" />

            <Box layer="aws" title="AWS Services"
              items={["Bedrock (Claude)", "Aurora PostgreSQL", "Cognito", "ECR"]}
              active={active === "aws"} onClick={() => toggle("aws")} />

            {/* Legend */}
            <div style={{ marginTop: 14, display: "flex", flexWrap: "wrap", gap: 6 }}>
              {LAYERS.map((l) => (
                <div key={l.key} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <div style={{ width: 7, height: 7, borderRadius: 2, background: l.color }} />
                  <span style={{ fontSize: 9, color: COLORS.textDim }}>{l.label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Right: Detail + Flow */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

            {/* Detail panel */}
            <div>
              <div style={{ fontSize: 10, color: COLORS.textDim, marginBottom: 8, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                详细信息
              </div>
              <div style={{
                background: COLORS.surface, border: `1px solid ${COLORS.border}`,
                borderRadius: 10, padding: 16,
                maxHeight: 480, overflowY: "auto",
              }}>
                {active ? DETAIL[active] : (
                  <div style={{ color: COLORS.textDim, fontSize: 13, paddingTop: 40, textAlign: "center" }}>
                    ← 点击左侧任意层级
                  </div>
                )}
              </div>
            </div>

            {/* Request flow */}
            <div>
              <div style={{ fontSize: 10, color: COLORS.textDim, marginBottom: 8, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                请求链路 — chat completion
              </div>
              <div style={{ background: COLORS.surface, border: `1px solid ${COLORS.border}`, borderRadius: 10, padding: 14 }}>
                {[
                  [COLORS.accent,  "Client", "POST /v1/chat/completions + Authorization: Bearer <token>"],
                  [COLORS.cyan,    "Ingress", "ALB 路由至 backend Service :8000"],
                  [COLORS.orange,  "CORS",   "SecurityMiddleware 检查 Origin 是否在白名单"],
                  [COLORS.orange,  "CSRF",   "SecurityMiddleware: Authorization 或 X-Requested-With 有其一即通过（仅绕过 CSRF 层）"],
                  [COLORS.purple,  "Auth",   "AuthService: Bearer token 必须有效，X-Requested-With 无法替代 → 无 token 则 401"],
                  [COLORS.purple,  "Translate", "Translator 将 OpenAI schema 转换为 Bedrock InvokeModel 格式"],
                  [COLORS.red,     "Bedrock", "BedrockClient 调用 AWS Bedrock Claude 模型（Semaphore 限流）"],
                  [COLORS.purple,  "Stream", "SSE 流式响应，Translator 将 Bedrock 格式转换回 OpenAI 格式"],
                  [COLORS.purple,  "Audit",  "UsageStats + AuditLog 写入 Aurora PostgreSQL"],
                  [COLORS.accent,  "Client", "客户端收到流式响应"],
                ].map(([color, tag, text], i) => (
                  <div key={i} style={{ display: "flex", gap: 8, marginBottom: 7, alignItems: "flex-start" }}>
                    <div style={{
                      minWidth: 18, height: 18, borderRadius: "50%",
                      background: color as string, color: "#000",
                      fontSize: 10, fontWeight: 700,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      flexShrink: 0, marginTop: 1,
                    }}>{i + 1}</div>
                    <Tag color={color as string}>{tag as string}</Tag>
                    <div style={{ color: COLORS.textMuted, fontSize: 12, lineHeight: "1.5" }}>{text as string}</div>
                  </div>
                ))}
              </div>
            </div>

          </div>
        </div>
      </div>
    </div>
  );
}

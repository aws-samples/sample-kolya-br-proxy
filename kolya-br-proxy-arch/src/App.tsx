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

type PageKey = "arch" | "translation";
type LayerKey = "client" | "ingress" | "frontend" | "backend" | "infra" | "aws";
type TranslationPhase = "phase1" | "phase2a" | "phase2b" | "phase3" | "stream-anthropic" | "stream-converse" | "auto-fixes";

const LAYERS: { key: LayerKey; label: string; color: string; soft: string }[] = [
  { key: "client", label: "Client / End User", color: COLORS.accent, soft: COLORS.accentSoft },
  { key: "ingress", label: "Kubernetes Ingress", color: COLORS.cyan, soft: COLORS.cyanSoft },
  { key: "frontend", label: "Frontend (Vue / Quasar)", color: COLORS.green, soft: COLORS.greenSoft },
  { key: "backend", label: "Backend (FastAPI)", color: COLORS.purple, soft: COLORS.purpleSoft },
  { key: "infra", label: "Infrastructure (Terraform / EKS)", color: COLORS.amber, soft: COLORS.amberSoft },
  { key: "aws", label: "AWS Services", color: COLORS.red, soft: COLORS.redSoft },
];

// ─── Shared sub-components ──────────────────────────────────────────────────

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

function LinkSpan({ onClick, color, children }: { onClick: () => void; color: string; children: React.ReactNode }) {
  return (
    <span
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      style={{ color, cursor: "pointer", textDecoration: "underline", textDecorationStyle: "dotted", textUnderlineOffset: 2 }}
    >{children}</span>
  );
}

function MappingTable({ rows, headers }: { rows: string[][]; headers: string[] }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
        <thead>
          <tr>
            {headers.map((h) => (
              <th key={h} style={{ textAlign: "left", padding: "5px 8px", borderBottom: `1px solid ${COLORS.border}`, color: COLORS.textDim, fontWeight: 600 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j} style={{ padding: "4px 8px", borderBottom: `1px solid ${COLORS.border}22`, color: COLORS.textMuted, fontFamily: "'JetBrains Mono', monospace" }}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Tab Navigation ─────────────────────────────────────────────────────────

function TabNav({ page, setPage }: { page: PageKey; setPage: (p: PageKey) => void }) {
  const tabs: { key: PageKey; label: string }[] = [
    { key: "arch", label: "Architecture" },
    { key: "translation", label: "Request Translation" },
  ];
  return (
    <div style={{ display: "flex", gap: 0, marginBottom: 20, borderBottom: `1px solid ${COLORS.border}` }}>
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => setPage(t.key)}
          style={{
            background: "none",
            border: "none",
            borderBottom: page === t.key ? `2px solid ${COLORS.accent}` : "2px solid transparent",
            color: page === t.key ? COLORS.text : COLORS.textDim,
            fontWeight: page === t.key ? 700 : 400,
            fontSize: 13,
            padding: "8px 18px",
            cursor: "pointer",
            fontFamily: "inherit",
            transition: "all 0.15s",
          }}
        >{t.label}</button>
      ))}
    </div>
  );
}

// ─── Architecture Page Detail Panels ────────────────────────────────────────

function archDetail(navigateTo: (page: PageKey, phase?: TranslationPhase) => void): Record<LayerKey, React.ReactNode> {
  return {
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
          核心 AI 网关。OpenAI 兼容 API，代理至 AWS Bedrock 多模型（Claude、Nova、DeepSeek 等）。
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
            <LinkSpan onClick={() => navigateTo("translation", "phase2a")} color={COLORS.red}>BedrockClient</LinkSpan> — AWS Bedrock 代理<br/>
            <LinkSpan onClick={() => navigateTo("translation", "phase1")} color={COLORS.cyan}>Translator</LinkSpan> — OpenAI ↔ Bedrock 格式转换<br/>
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

        {/* SecurityMiddleware */}
        <div style={{ marginTop: 14, border: `1px solid ${COLORS.orange}44`, borderRadius: 8, padding: 12 }}>
          <div style={{ color: COLORS.orange, fontWeight: 700, fontSize: 13, marginBottom: 10 }}>
            SecurityMiddleware — <code style={{ fontSize: 11 }}>app/middleware/security.py</code>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
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
          <Card color={COLORS.red} title="Bedrock (Multi-Model)">
            Anthropic Claude — <LinkSpan onClick={() => navigateTo("translation", "phase2a")} color={COLORS.cyan}>InvokeModel API</LinkSpan><br/>
            Nova / DeepSeek / Mistral / Llama — <LinkSpan onClick={() => navigateTo("translation", "phase2b")} color={COLORS.cyan}>Converse API</LinkSpan><br/>
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
}

// ─── Architecture Page ──────────────────────────────────────────────────────

function ArchitecturePage({ navigateTo }: { navigateTo: (page: PageKey, phase?: TranslationPhase) => void }) {
  const [active, setActive] = useState<LayerKey | null>(null);
  const toggle = (key: LayerKey) => setActive((prev) => (prev === key ? null : key));
  const DETAIL = archDetail(navigateTo);

  return (
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
          items={["Bedrock (Multi-Model)", "Aurora PostgreSQL", "Cognito", "ECR"]}
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
              [COLORS.accent,  "Client", "POST /v1/chat/completions + Authorization: Bearer <token>", null],
              [COLORS.cyan,    "Ingress", "ALB 路由至 backend Service :8000", null],
              [COLORS.orange,  "CORS",   "SecurityMiddleware 检查 Origin 是否在白名单", null],
              [COLORS.orange,  "CSRF",   "SecurityMiddleware: Authorization 或 X-Requested-With 有其一即通过（仅绕过 CSRF 层）", null],
              [COLORS.purple,  "Auth",   "AuthService: Bearer token 必须有效，X-Requested-With 无法替代 → 无 token 则 401", null],
              [COLORS.purple,  "Translate", "Translator 将 OpenAI schema 转换为 BedrockRequest；Anthropic 模型走 InvokeModel，其他走 Converse API", "phase1" as TranslationPhase],
              [COLORS.red,     "Bedrock", "BedrockClient 调用 AWS Bedrock 模型（Semaphore 限流，自动路由 API）", "phase2a" as TranslationPhase],
              [COLORS.purple,  "Stream", "SSE 流式响应，Translator 将 Bedrock 格式转换回 OpenAI 格式", "stream-anthropic" as TranslationPhase],
              [COLORS.purple,  "Audit",  "UsageStats + AuditLog 写入 Aurora PostgreSQL", null],
              [COLORS.accent,  "Client", "客户端收到流式响应", null],
            ].map(([color, tag, text, linkPhase], i) => (
              <div key={i} style={{ display: "flex", gap: 8, marginBottom: 7, alignItems: "flex-start" }}>
                <div style={{
                  minWidth: 18, height: 18, borderRadius: "50%",
                  background: color as string, color: "#000",
                  fontSize: 10, fontWeight: 700,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  flexShrink: 0, marginTop: 1,
                }}>{i + 1}</div>
                <Tag color={color as string}>{tag as string}</Tag>
                <div style={{ color: COLORS.textMuted, fontSize: 12, lineHeight: "1.5" }}>
                  {linkPhase ? (
                    <LinkSpan onClick={() => navigateTo("translation", linkPhase as TranslationPhase)} color={COLORS.cyan}>
                      {text as string}
                    </LinkSpan>
                  ) : (text as string)}
                </div>
              </div>
            ))}
          </div>
        </div>

      </div>
    </div>
  );
}

// ─── Request Translation: Detail Panels ─────────────────────────────────────

const TRANSLATION_DETAIL: Record<TranslationPhase, { title: string; color: string; content: (nav: (page: PageKey, phase?: TranslationPhase) => void) => React.ReactNode }> = {
  phase1: {
    title: "Phase 1: OpenAI → BedrockRequest",
    color: COLORS.accent,
    content: (nav) => {
      const codeBox: React.CSSProperties = {
        background: COLORS.bg, border: `1px solid ${COLORS.border}`,
        borderRadius: 4, padding: 8, fontSize: 11, fontFamily: "'JetBrains Mono', monospace",
        lineHeight: 1.7, whiteSpace: "pre", overflowX: "auto",
      };
      const hl = (c: string, t: string) => <span style={{ color: c }}>{t}</span>;
      const dim = (t: string) => hl(COLORS.textDim, t);

      return (
      <div>
        <div style={{ color: COLORS.textDim, fontSize: 11, marginBottom: 8 }}>
          <code>translator.py</code> — <code>RequestTranslator.openai_to_bedrock()</code>
        </div>

        {/* ── 消息转换：完整 JSON 对比 ──────────────────── */}

        <Card color={COLORS.accent} title="消息转换 — 完整 JSON 对比">
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>

            {/* 1. system */}
            <div>
              <div style={{ color: COLORS.amber, fontSize: 11, fontWeight: 700, marginBottom: 4 }}>
                ① system 消息 → 提取到顶层 <code>BedrockRequest.system</code>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 28px 1fr", gap: 0, alignItems: "center" }}>
                <div style={codeBox}>
                  <div style={{ color: COLORS.accent, marginBottom: 2 }}>// OpenAI messages 数组中</div>
{`{
  `}{hl(COLORS.accent, '"role"')}{`: "system",
  `}{hl(COLORS.accent, '"content"')}{`: "You are a helpful
    assistant that speaks Chinese"
}`}
                </div>
                <div style={{ textAlign: "center", color: COLORS.amber, fontWeight: 700, fontSize: 16 }}>→</div>
                <div style={codeBox}>
                  <div style={{ color: COLORS.purple, marginBottom: 2 }}>// BedrockRequest 顶层字段</div>
{`{
  `}{hl(COLORS.purple, '"system"')}{`: "You are a helpful
    assistant that speaks Chinese",
  `}{hl(COLORS.purple, '"messages"')}{`: [...]  `}{dim("// 不含 system")}{`
}`}
                </div>
              </div>
              <div style={{ color: COLORS.amber, fontSize: 10, marginTop: 3 }}>仅使用最后一条 system 消息；从 messages 数组移除，放到顶层 system 字段</div>
            </div>

            {/* 2. user string */}
            <div>
              <div style={{ color: COLORS.green, fontSize: 11, fontWeight: 700, marginBottom: 4 }}>
                ② user 消息（纯文本）→ 直接传递
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 28px 1fr", gap: 0, alignItems: "center" }}>
                <div style={codeBox}>
{`{
  `}{hl(COLORS.accent, '"role"')}{`: "user",
  `}{hl(COLORS.accent, '"content"')}{`: "Hello, what's the
    weather in London?"
}`}
                </div>
                <div style={{ textAlign: "center", color: COLORS.green, fontWeight: 700, fontSize: 16 }}>→</div>
                <div style={codeBox}>
{`{
  `}{hl(COLORS.purple, '"role"')}{`: "user",
  `}{hl(COLORS.purple, '"content"')}{`: "Hello, what's the
    weather in London?"
}`}
                </div>
              </div>
              <div style={{ color: COLORS.green, fontSize: 10, marginTop: 3 }}>结构相同，直接传递</div>
            </div>

            {/* 3. user multimodal */}
            <div>
              <div style={{ color: COLORS.cyan, fontSize: 11, fontWeight: 700, marginBottom: 4 }}>
                ③ user 消息（多模态数组）→ 转换内容块格式
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 28px 1fr", gap: 0, alignItems: "center" }}>
                <div style={codeBox}>
{`{
  "role": "user",
  `}{hl(COLORS.accent, '"content"')}{`: [
    {
      "type": "text",
      "text": "What's in this image?"
    },
    {
      "type": `}{hl(COLORS.cyan, '"image_url"')}{`,
      "image_url": {
        "url": "data:image/png;base64,
          iVBOR..."
      }
    }
  ]
}`}
                </div>
                <div style={{ textAlign: "center", color: COLORS.cyan, fontWeight: 700, fontSize: 16 }}>→</div>
                <div style={codeBox}>
{`{
  "role": "user",
  `}{hl(COLORS.purple, '"content"')}{`: [
    {
      "type": "text",
      "text": "What's in this image?"
    },
    {
      "type": `}{hl(COLORS.cyan, '"image"')}{`,
      "source": {
        "type": "base64",
        "media_type": "image/png",
        "data": "iVBOR..."
      }
    }
  ]
}`}
                </div>
              </div>
              <div style={{ color: COLORS.cyan, fontSize: 10, marginTop: 3 }}>
                image_url → image + source 格式；URL 类型图片会先下载再 base64 编码
              </div>
            </div>

            {/* 4. assistant plain */}
            <div>
              <div style={{ color: COLORS.green, fontSize: 11, fontWeight: 700, marginBottom: 4 }}>
                ④ assistant 消息（纯文本）→ 直接传递
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 28px 1fr", gap: 0, alignItems: "center" }}>
                <div style={codeBox}>
{`{
  `}{hl(COLORS.accent, '"role"')}{`: "assistant",
  `}{hl(COLORS.accent, '"content"')}{`: "I can help with that."
}`}
                </div>
                <div style={{ textAlign: "center", color: COLORS.green, fontWeight: 700, fontSize: 16 }}>→</div>
                <div style={codeBox}>
{`{
  `}{hl(COLORS.purple, '"role"')}{`: "assistant",
  `}{hl(COLORS.purple, '"content"')}{`: "I can help with that."
}`}
                </div>
              </div>
            </div>

            {/* 5. assistant with tool_calls */}
            <div>
              <div style={{ color: COLORS.purple, fontSize: 11, fontWeight: 700, marginBottom: 4 }}>
                ⑤ assistant 消息（含 tool_calls）→ function 转换为 tool_use 内容块
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 28px 1fr", gap: 0, alignItems: "center" }}>
                <div style={codeBox}>
{`{
  "role": "assistant",
  "content": null,
  `}{hl(COLORS.accent, '"tool_calls"')}{`: [
    {
      "id": "call_abc123",
      "type": "function",
      `}{hl(COLORS.accent, '"function"')}{`: {
        "name": "get_weather",
        "arguments": `}{hl(COLORS.green, '"{\\"city\\":\\"London\\"}"')}{`
      }
    }
  ]
}`}
                </div>
                <div style={{ textAlign: "center", color: COLORS.purple, fontWeight: 700, fontSize: 16 }}>→</div>
                <div style={codeBox}>
{`{
  "role": "assistant",
  `}{hl(COLORS.purple, '"content"')}{`: [
    {
      "type": `}{hl(COLORS.purple, '"tool_use"')}{`,
      "id": "call_abc123",
      "name": "get_weather",
      "input": `}{hl(COLORS.green, '{"city": "London"}')}{`
    }
  ]
}`}
                  <div style={{ marginTop: 4, color: COLORS.amber, fontSize: 10 }}>
                    ⚠ arguments 是 JSON 字符串 → input 是解析后的对象
                  </div>
                </div>
              </div>
            </div>

            {/* 6. tool → user */}
            <div>
              <div style={{ color: COLORS.red, fontSize: 11, fontWeight: 700, marginBottom: 4 }}>
                ⑥ tool 消息 → 转为 user 消息 + tool_result 内容块 <span style={{ background: COLORS.redSoft, padding: "1px 4px", borderRadius: 3 }}>role 变更!</span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 28px 1fr", gap: 0, alignItems: "center" }}>
                <div style={codeBox}>
{dim("// 可能有多条连续 tool 消息")}{`
{
  `}{hl(COLORS.accent, '"role"')}{`: `}{hl(COLORS.red, '"tool"')}{`,
  "tool_call_id": "call_abc123",
  "content": "London: 晴，22°C"
}
{
  `}{hl(COLORS.accent, '"role"')}{`: `}{hl(COLORS.red, '"tool"')}{`,
  "tool_call_id": "call_def456",
  "content": "Paris: 多云，18°C"
}`}
                </div>
                <div style={{ textAlign: "center", color: COLORS.red, fontWeight: 700, fontSize: 16 }}>→</div>
                <div style={codeBox}>
{dim("// 合并为一条 user 消息")}{`
{
  `}{hl(COLORS.purple, '"role"')}{`: `}{hl(COLORS.red, '"user"')}{`,
  "content": [
    {
      "type": `}{hl(COLORS.purple, '"tool_result"')}{`,
      "tool_use_id": "call_abc123",
      "content": "London: 晴，22°C"
    },
    {
      "type": `}{hl(COLORS.purple, '"tool_result"')}{`,
      "tool_use_id": "call_def456",
      "content": "Paris: 多云，18°C"
    }
  ]
}`}
                </div>
              </div>
              <div style={{ color: COLORS.red, fontSize: 10, marginTop: 3 }}>
                role 从 "tool" 变为 "user"；多条连续 tool 消息合并到同一个 user 消息的 content 数组中；tool_call_id → tool_use_id
              </div>
            </div>

          </div>
        </Card>

        <div style={{ height: 10 }} />

        {/* ── 工具定义转换 ──────────────────── */}

        <Card color={COLORS.green} title="工具定义转换 (tools)">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 28px 1fr", gap: 0, alignItems: "center" }}>
            <div style={codeBox}>
              <div style={{ color: COLORS.accent, marginBottom: 2 }}>// OpenAI tools[]</div>
{`{
  "type": "function",
  "function": {
    "name": "get_weather",
    "description": "Get weather",
    `}{hl(COLORS.accent, '"parameters"')}{`: {
      "type": "object",
      "properties": {
        "city": {
          "type": "string"
        }
      },
      "required": ["city"]
    }
  }
}`}
            </div>
            <div style={{ textAlign: "center", color: COLORS.green, fontWeight: 700, fontSize: 16 }}>→</div>
            <div style={codeBox}>
              <div style={{ color: COLORS.purple, marginBottom: 2 }}>// BedrockRequest tools[]</div>
{`{
  "name": "get_weather",
  "description": "Get weather",
  `}{hl(COLORS.purple, '"input_schema"')}{`: {
    "type": "object",
    "properties": {
      "city": {
        "type": "string"
      }
    },
    "required": ["city"]
  }
}`}
            </div>
          </div>
          <div style={{ color: COLORS.green, fontSize: 10, marginTop: 4 }}>
            去掉外层 type + function 包装；parameters 重命名为 input_schema；JSON Schema 内容不变
          </div>
        </Card>

        <div style={{ height: 10 }} />

        {/* ── tool_choice 转换 ──────────────────── */}

        <Card color={COLORS.amber} title="tool_choice 转换 — 完整请求 JSON 对比">
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

            {/* auto */}
            <div>
              <div style={{ color: COLORS.green, fontSize: 11, fontWeight: 700, marginBottom: 4 }}>
                ① "auto" — 模型自行决定是否调用工具
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 28px 1fr", gap: 0, alignItems: "center" }}>
                <div style={codeBox}>
                  <div style={{ color: COLORS.accent, marginBottom: 2 }}>// OpenAI 请求</div>
{`{
  "model": "claude-sonnet-4-20250514",
  "messages": [...],
  "tools": [...],
  `}{hl(COLORS.accent, '"tool_choice"')}{`: `}{hl(COLORS.green, '"auto"')}{`
}`}
                </div>
                <div style={{ textAlign: "center", color: COLORS.green, fontWeight: 700, fontSize: 16 }}>→</div>
                <div style={codeBox}>
                  <div style={{ color: COLORS.purple, marginBottom: 2 }}>// Anthropic body (InvokeModel)</div>
{`{
  "anthropic_version": "bedrock-2023-05-31",
  "messages": [...],
  "tools": [...],
  `}{hl(COLORS.purple, '"tool_choice"')}{`: {
    "type": `}{hl(COLORS.green, '"auto"')}{`
  }
}`}
                </div>
              </div>
              <div style={{ color: COLORS.textDim, fontSize: 10, marginTop: 2 }}>字符串 "auto" → 对象 {`{"type": "auto"}`}</div>
            </div>

            {/* required → any */}
            <div>
              <div style={{ color: COLORS.amber, fontSize: 11, fontWeight: 700, marginBottom: 4 }}>
                ② "required" → "any" — 必须调用某个工具
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 28px 1fr", gap: 0, alignItems: "center" }}>
                <div style={codeBox}>
                  <div style={{ color: COLORS.accent, marginBottom: 2 }}>// OpenAI 请求</div>
{`{
  "model": "claude-sonnet-4-20250514",
  "messages": [...],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get weather",
        "parameters": {...}
      }
    }
  ],
  `}{hl(COLORS.accent, '"tool_choice"')}{`: `}{hl(COLORS.amber, '"required"')}{`
}`}
                </div>
                <div style={{ textAlign: "center", color: COLORS.amber, fontWeight: 700, fontSize: 16 }}>→</div>
                <div style={codeBox}>
                  <div style={{ color: COLORS.purple, marginBottom: 2 }}>// Anthropic body (InvokeModel)</div>
{`{
  "anthropic_version": "bedrock-2023-05-31",
  "messages": [...],
  "tools": [
    {
      "name": "get_weather",
      "description": "Get weather",
      "input_schema": {...}
    }
  ],
  `}{hl(COLORS.purple, '"tool_choice"')}{`: {
    "type": `}{hl(COLORS.amber, '"any"')}{`
  }
}`}
                </div>
              </div>
              <div style={{ color: COLORS.amber, fontSize: 10, marginTop: 2 }}>
                ⚠ 关键差异：OpenAI 叫 "required"，Anthropic 叫 "any"，含义相同 — 强制模型调用 tools 中的某一个
              </div>
            </div>

            {/* none */}
            <div>
              <div style={{ color: COLORS.red, fontSize: 11, fontWeight: 700, marginBottom: 4 }}>
                ③ "none" — 禁止调用任何工具
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 28px 1fr", gap: 0, alignItems: "center" }}>
                <div style={codeBox}>
                  <div style={{ color: COLORS.accent, marginBottom: 2 }}>// OpenAI 请求</div>
{`{
  "model": "claude-sonnet-4-20250514",
  "messages": [...],
  "tools": [...],
  `}{hl(COLORS.accent, '"tool_choice"')}{`: `}{hl(COLORS.red, '"none"')}{`
}`}
                </div>
                <div style={{ textAlign: "center", color: COLORS.red, fontWeight: 700, fontSize: 16 }}>→</div>
                <div style={codeBox}>
                  <div style={{ color: COLORS.purple, marginBottom: 2 }}>// Anthropic body (InvokeModel)</div>
{`{
  "anthropic_version": "bedrock-2023-05-31",
  "messages": [...],
  "tools": [...],
  `}{hl(COLORS.purple, '"tool_choice"')}{`: {
    "type": `}{hl(COLORS.red, '"none"')}{`
  }
}`}
                </div>
              </div>
              <div style={{ color: COLORS.textDim, fontSize: 10, marginTop: 2 }}>即使 tools 已定义，也不会调用</div>
            </div>

            {/* 指定函数 */}
            <div>
              <div style={{ color: COLORS.purple, fontSize: 11, fontWeight: 700, marginBottom: 4 }}>
                ④ 指定函数名 — 强制调用指定的某一个工具
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 28px 1fr", gap: 0, alignItems: "center" }}>
                <div style={codeBox}>
                  <div style={{ color: COLORS.accent, marginBottom: 2 }}>// OpenAI 请求</div>
{`{
  "model": "claude-sonnet-4-20250514",
  "messages": [...],
  "tools": [...],
  `}{hl(COLORS.accent, '"tool_choice"')}{`: {
    "type": `}{hl(COLORS.accent, '"function"')}{`,
    `}{hl(COLORS.accent, '"function"')}{`: {
      "name": "get_weather"
    }
  }
}`}
                </div>
                <div style={{ textAlign: "center", color: COLORS.purple, fontWeight: 700, fontSize: 16 }}>→</div>
                <div style={codeBox}>
                  <div style={{ color: COLORS.purple, marginBottom: 2 }}>// Anthropic body (InvokeModel)</div>
{`{
  "anthropic_version": "bedrock-2023-05-31",
  "messages": [...],
  "tools": [...],
  `}{hl(COLORS.purple, '"tool_choice"')}{`: {
    "type": `}{hl(COLORS.purple, '"tool"')}{`,
    "name": "get_weather"
  }
}`}
                </div>
              </div>
              <div style={{ color: COLORS.purple, fontSize: 10, marginTop: 2 }}>
                type: "function" → "tool"；去掉嵌套的 function 包装，name 提升到顶层
              </div>
            </div>

          </div>
        </Card>

        <div style={{ height: 10 }} />

        {/* ── 标量参数 ──────────────────── */}

        <Card color={COLORS.amber} title="标量参数映射">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 28px 1fr", gap: 0, alignItems: "center", marginBottom: 8 }}>
            <div style={codeBox}>
              <div style={{ color: COLORS.accent, marginBottom: 2 }}>// OpenAI 请求</div>
{`{
  "model": "claude-sonnet-4-20250514",
  "temperature": 0.7,
  "max_tokens": 2048,
  "stop": "END",
  "top_p": 0.9,
  "n": 1,
  "presence_penalty": 0,
  "frequency_penalty": 0
}`}
            </div>
            <div style={{ textAlign: "center", color: COLORS.amber, fontWeight: 700, fontSize: 16 }}>→</div>
            <div style={codeBox}>
              <div style={{ color: COLORS.purple, marginBottom: 2 }}>// BedrockRequest</div>
{`{
  "temperature": 0.7,
  "max_tokens": 2048,
  "stop_sequences": [`}{hl(COLORS.green, '"END"')}{`],
  `}{dim('// top_p: 被忽略 (temperature 已设置)')}{`
  `}{dim('// n: 被忽略 (仅支持 n=1)')}{`
  `}{dim('// presence_penalty: 被忽略')}{`
  `}{dim('// frequency_penalty: 被忽略')}{`
}`}
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 10, color: COLORS.textMuted }}>
            <div>• <code style={{ color: COLORS.amber }}>stop</code>: 字符串 <code>"END"</code> 自动包装为数组 <code>["END"]</code>；已是数组则直接传递</div>
            <div>• <code style={{ color: COLORS.amber }}>top_p</code>: Bedrock 上与 temperature 互斥，设置了 temperature 时 top_p 被忽略</div>
            <div>• <code style={{ color: COLORS.amber }}>max_tokens</code>: 未设置时默认 4096</div>
            <div>• <code style={{ color: COLORS.textDim }}>n / presence_penalty / frequency_penalty</code>: 不支持，非默认值时记录 warning 日志</div>
          </div>
        </Card>

        <div style={{ height: 10 }} />

        {/* ── 扩展字段透传 ──────────────────── */}

        <Card color={COLORS.orange} title="Bedrock 扩展字段透传">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 28px 1fr", gap: 0, alignItems: "center", marginBottom: 8 }}>
            <div style={codeBox}>
              <div style={{ color: COLORS.accent, marginBottom: 2 }}>// OpenAI 请求体（扩展字段）</div>
{`{
  "model": "...",
  "messages": [...],
  `}{hl(COLORS.orange, '"bedrock_guardrail_config"')}{`: {
    "guardrailIdentifier": "abc123",
    "guardrailVersion": "1"
  },
  `}{hl(COLORS.orange, '"bedrock_trace"')}{`: "ENABLED",
  `}{hl(COLORS.orange, '"bedrock_additional_model_request_fields"')}{`: {
    "thinking": {
      "type": "enabled",
      "budget_tokens": 5000
    }
  }
}`}
            </div>
            <div style={{ textAlign: "center", color: COLORS.orange, fontWeight: 700, fontSize: 16 }}>→</div>
            <div style={codeBox}>
              <div style={{ color: COLORS.purple, marginBottom: 2 }}>// BedrockRequest（去掉 bedrock_ 前缀）</div>
{`{
  "messages": [...],
  `}{hl(COLORS.purple, '"guardrail_config"')}{`: {
    "guardrailIdentifier": "abc123",
    "guardrailVersion": "1"
  },
  `}{hl(COLORS.purple, '"trace"')}{`: "ENABLED",
  `}{hl(COLORS.purple, '"additional_model_request_fields"')}{`: {
    "thinking": {
      "type": "enabled",
      "budget_tokens": 5000
    }
  }
}`}
            </div>
          </div>
          <MappingTable
            headers={["OpenAI 请求字段", "BedrockRequest 字段"]}
            rows={[
              ["bedrock_guardrail_config", "guardrail_config"],
              ["bedrock_additional_model_request_fields", "additional_model_request_fields"],
              ["bedrock_trace", "trace"],
              ["bedrock_performance_config", "performance_config"],
              ["bedrock_prompt_caching", "prompt_caching"],
              ["bedrock_prompt_variables", "prompt_variables"],
              ["bedrock_additional_model_response_field_paths", "additional_model_response_field_paths"],
              ["bedrock_request_metadata", "request_metadata"],
            ]}
          />
          <div style={{ marginTop: 8, fontSize: 11 }}>
            也可通过 <code>X-Bedrock-*</code> HTTP 请求头设置（请求头优先于请求体）。例如：<br/>
            <code style={{ color: COLORS.orange }}>X-Bedrock-Guardrail-Id: abc123</code> + <code style={{ color: COLORS.orange }}>X-Bedrock-Guardrail-Version: 1</code><br/>
            <code style={{ color: COLORS.orange }}>X-Bedrock-Additional-Fields: {`{"thinking":{"type":"enabled","budget_tokens":5000}}`}</code>
          </div>
        </Card>

        <div style={{ marginTop: 12, textAlign: "right" }}>
          <LinkSpan onClick={() => nav("translation", "phase2a")} color={COLORS.purple}>下一步：Anthropic InvokeModel →</LinkSpan>
        </div>
      </div>
    );},
  },

  phase2a: {
    title: "Phase 2a: Anthropic InvokeModel",
    color: COLORS.purple,
    content: (nav) => (
      <div>
        <div style={{ color: COLORS.textDim, fontSize: 11, marginBottom: 8 }}>
          <code>bedrock.py</code> — <code>_build_anthropic_body()</code> + <code>_build_invoke_kwargs()</code>
        </div>

        <Card color={COLORS.purple} title="Body 构建示例">
          <div style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: 8, fontSize: 11, fontFamily: "monospace", lineHeight: 1.7 }}>
            {`{`}<br/>
            &nbsp;&nbsp;{`"anthropic_version": "bedrock-2023-05-31",`}<br/>
            &nbsp;&nbsp;{`"max_tokens": 4096,`}<br/>
            &nbsp;&nbsp;{`"messages": [...],`}<br/>
            &nbsp;&nbsp;<span style={{ color: COLORS.textDim }}>// 可选</span><br/>
            &nbsp;&nbsp;{`"system": "You are...",`}<br/>
            &nbsp;&nbsp;{`"temperature": 0.7,`}<br/>
            &nbsp;&nbsp;{`"tools": [...],`}<br/>
            &nbsp;&nbsp;{`"tool_choice": {"type": "auto"},`}<br/>
            &nbsp;&nbsp;<span style={{ color: COLORS.textDim }}>// additional_model_request_fields 合并</span><br/>
            &nbsp;&nbsp;{`"thinking": {"type": "enabled", "budget_tokens": 5000},`}<br/>
            &nbsp;&nbsp;<span style={{ color: COLORS.textDim }}>// effort 自动转换</span><br/>
            &nbsp;&nbsp;{`"anthropic_beta": ["effort-2025-11-24"],`}<br/>
            &nbsp;&nbsp;{`"output_config": {"effort": "medium"}`}<br/>
            {`}`}
          </div>
        </Card>

        <div style={{ height: 10 }} />

        <Card color={COLORS.red} title="invoke_model 顶层参数 (invoke_kwargs)">
          <div style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: 8, fontSize: 11, fontFamily: "monospace", lineHeight: 1.7 }}>
            {`{`}<br/>
            &nbsp;&nbsp;{`"modelId": "global.anthropic.claude-opus-4-6-v1",`}<br/>
            &nbsp;&nbsp;{`"contentType": "application/json",`}<br/>
            &nbsp;&nbsp;{`"accept": "application/json",`}<br/>
            &nbsp;&nbsp;<span style={{ color: COLORS.textDim }}>// guardrail_config →</span><br/>
            &nbsp;&nbsp;{`"guardrailIdentifier": "abc123",`}<br/>
            &nbsp;&nbsp;{`"guardrailVersion": "1",`}<br/>
            &nbsp;&nbsp;{`"trace": "ENABLED",`}<br/>
            &nbsp;&nbsp;{`"performanceConfig": {...}`}<br/>
            {`}`}
          </div>
        </Card>

        <div style={{ height: 10 }} />

        <Card color={COLORS.amber} title="为何 Anthropic 模型使用 InvokeModel">
          <MappingTable
            headers={["方面", "Converse API", "InvokeModel API"]}
            rows={[
              ["Body 格式", "AWS 特有 (camelCase)", "Anthropic Messages API (snake_case)"],
              ["thinking 支持", "通过 additionalModelRequestFields (受限)", "直接作为 body 字段"],
              ["effort 支持", "不支持", "通过 output_config + beta 标志"],
              ["响应格式", "inputTokens, stopReason", "input_tokens, stop_reason"],
              ["工具调用", "toolUse / toolResult (camelCase)", "tool_use / tool_result (snake_case)"],
              ["流式事件", "contentBlockStart, contentBlockDelta", "content_block_start, content_block_delta"],
            ]}
          />
        </Card>

        <div style={{ marginTop: 12, display: "flex", justifyContent: "space-between" }}>
          <LinkSpan onClick={() => nav("translation", "phase1")} color={COLORS.accent}>← Phase 1</LinkSpan>
          <LinkSpan onClick={() => nav("translation", "phase2b")} color={COLORS.cyan}>Phase 2b: Converse →</LinkSpan>
        </div>
      </div>
    ),
  },

  phase2b: {
    title: "Phase 2b: Converse API (Non-Anthropic)",
    color: COLORS.cyan,
    content: (nav) => (
      <div>
        <div style={{ color: COLORS.textDim, fontSize: 11, marginBottom: 8 }}>
          <code>bedrock.py</code> — <code>_build_converse_params()</code>
          <br/>非 Anthropic 模型（Amazon Nova、DeepSeek、Mistral、Llama 等）使用 Converse API。
        </div>

        <Card color={COLORS.cyan} title="Converse API 参数映射">
          <div style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: 8, fontSize: 11, fontFamily: "monospace", lineHeight: 1.7 }}>
            {`{`}<br/>
            &nbsp;&nbsp;{`"modelId": "us.amazon.nova-pro-v1:0",`}<br/>
            &nbsp;&nbsp;{`"messages": [{"role":"user","content":[{"text":"Hello!"}]}],`}<br/>
            &nbsp;&nbsp;{`"system": [{"text": "You are..."}],`}<br/>
            &nbsp;&nbsp;{`"inferenceConfig": {`}<br/>
            &nbsp;&nbsp;&nbsp;&nbsp;{`"maxTokens": 4096,`}<br/>
            &nbsp;&nbsp;&nbsp;&nbsp;{`"temperature": 0.7,`}<br/>
            &nbsp;&nbsp;&nbsp;&nbsp;{`"topP": 0.9,`}<br/>
            &nbsp;&nbsp;&nbsp;&nbsp;{`"stopSequences": ["END"]`}<br/>
            &nbsp;&nbsp;{`},`}<br/>
            &nbsp;&nbsp;{`"toolConfig": {`}<br/>
            &nbsp;&nbsp;&nbsp;&nbsp;{`"tools": [{"toolSpec": {...}}],`}<br/>
            &nbsp;&nbsp;&nbsp;&nbsp;{`"toolChoice": {"auto": {}}`}<br/>
            &nbsp;&nbsp;{`},`}<br/>
            &nbsp;&nbsp;{`"guardrailConfig": {...},`}<br/>
            &nbsp;&nbsp;{`"additionalModelRequestFields": {...}`}<br/>
            {`}`}
          </div>
        </Card>

        <div style={{ height: 10 }} />

        <Card color={COLORS.amber} title="内容块格式差异">
          <MappingTable
            headers={["内容类型", "Anthropic (InvokeModel)", "Converse API"]}
            rows={[
              ["文本", '{"type":"text","text":"..."}', '{"text":"..."}'],
              ["图片", '{"type":"image","source":{...base64}}', '{"image":{"format":"png","source":{"bytes":...}}}'],
              ["工具调用", '{"type":"tool_use","id":"...","name":"...","input":{}}', '{"toolUse":{"toolUseId":"...","name":"...","input":{}}}'],
              ["工具结果", '{"type":"tool_result","tool_use_id":"...","content":"..."}', '{"toolResult":{"toolUseId":"...","content":[{"text":"..."}]}}'],
            ]}
          />
        </Card>

        <div style={{ height: 10 }} />

        <Card color={COLORS.green} title="Converse API 响应映射">
          <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", gap: 8, alignItems: "center" }}>
            <div style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: 8, fontSize: 11, fontFamily: "monospace", lineHeight: 1.6 }}>
              <div style={{ color: COLORS.cyan, marginBottom: 4 }}>Converse 响应</div>
              output.message.content[...]<br/>
              stopReason: "end_turn"<br/>
              usage.inputTokens: 100<br/>
              usage.outputTokens: 50
            </div>
            <div style={{ color: COLORS.textDim, fontSize: 16 }}>→</div>
            <div style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: 8, fontSize: 11, fontFamily: "monospace", lineHeight: 1.6 }}>
              <div style={{ color: COLORS.purple, marginBottom: 4 }}>BedrockResponse</div>
              content=[BedrockContentBlock...]<br/>
              stop_reason="end_turn"<br/>
              usage.input_tokens=100<br/>
              usage.output_tokens=50
            </div>
          </div>
        </Card>

        <div style={{ marginTop: 12, display: "flex", justifyContent: "space-between" }}>
          <LinkSpan onClick={() => nav("translation", "phase2a")} color={COLORS.purple}>← Phase 2a: InvokeModel</LinkSpan>
          <LinkSpan onClick={() => nav("translation", "phase3")} color={COLORS.green}>Phase 3: Response →</LinkSpan>
        </div>
      </div>
    ),
  },

  phase3: {
    title: "Phase 3: Response → OpenAI",
    color: COLORS.green,
    content: (nav) => (
      <div>
        <div style={{ color: COLORS.textDim, fontSize: 11, marginBottom: 8 }}>
          <code>bedrock.py</code> — <code>_invoke_inner()</code> &nbsp;|&nbsp;
          <code>translator.py</code> — <code>ResponseTranslator.bedrock_to_openai()</code>
        </div>

        <Card color={COLORS.green} title="非流式响应解析 (Anthropic)">
          <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", gap: 8, alignItems: "center" }}>
            <div style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: 8, fontSize: 11, fontFamily: "monospace", lineHeight: 1.6 }}>
              <div style={{ color: COLORS.red, marginBottom: 4 }}>Anthropic JSON</div>
              id: "msg_..."<br/>
              content: [text, tool_use, thinking]<br/>
              stop_reason: "end_turn"<br/>
              usage.input_tokens: 100<br/>
              usage.output_tokens: 50
            </div>
            <div style={{ color: COLORS.textDim, fontSize: 16 }}>→</div>
            <div style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: 8, fontSize: 11, fontFamily: "monospace", lineHeight: 1.6 }}>
              <div style={{ color: COLORS.purple, marginBottom: 4 }}>BedrockResponse</div>
              id="msg_..."<br/>
              content=[text, tool_use, thinking]<br/>
              stop_reason="end_turn"<br/>
              usage=BedrockUsage(100, 50)
            </div>
          </div>
        </Card>

        <div style={{ height: 10 }} />

        <Card color={COLORS.accent} title="BedrockResponse → OpenAI ChatCompletionResponse 字段映射">
          <MappingTable
            headers={["Bedrock", "OpenAI", "说明"]}
            rows={[
              ['content[type="text"]', "choices[0].message.content", "多个文本块拼接"],
              ['content[type="tool_use"]', "choices[0].message.tool_calls[]", "input → JSON 字符串 arguments"],
              ['content[type="thinking"]', "跳过", "不属于 OpenAI 格式"],
              ['stop_reason="end_turn"', 'finish_reason="stop"', ""],
              ['stop_reason="tool_use"', 'finish_reason="tool_calls"', ""],
              ['stop_reason="max_tokens"', 'finish_reason="length"', ""],
              ["usage.input_tokens", "usage.prompt_tokens", ""],
              ["usage.output_tokens", "usage.completion_tokens", ""],
            ]}
          />
        </Card>

        <div style={{ marginTop: 12, display: "flex", justifyContent: "space-between" }}>
          <LinkSpan onClick={() => nav("translation", "phase2b")} color={COLORS.cyan}>← Phase 2b: Converse</LinkSpan>
          <LinkSpan onClick={() => nav("translation", "stream-anthropic")} color={COLORS.red}>Streaming →</LinkSpan>
        </div>
      </div>
    ),
  },

  "stream-anthropic": {
    title: "Streaming: Anthropic (Phase 2a+3 流式版)",
    color: COLORS.red,
    content: (nav) => (
      <div>
        {/* ── 与非流式的关系说明 ── */}
        <div style={{
          background: COLORS.redSoft, border: `1px solid ${COLORS.red}44`,
          borderRadius: 6, padding: 10, marginBottom: 12,
        }}>
          <div style={{ color: COLORS.red, fontSize: 12, fontWeight: 700, marginBottom: 6 }}>
            与上方 Phase 2a + Phase 3 的关系
          </div>
          <div style={{ color: COLORS.textMuted, fontSize: 11, lineHeight: 1.7 }}>
            当客户端发送 <code style={{ color: COLORS.text }}>"stream": true</code> 时，Phase 2a 和 Phase 3 不再是"等完整响应 → 一次性转换"，而是变为：
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 0, marginTop: 8 }}>
            {[
              [COLORS.accent,  "客户端", 'POST /v1/chat/completions  { "stream": true, ... }'],
              [COLORS.purple,  "bedrock.py", "invoke_model_with_response_stream() — 建立流式连接"],
              [COLORS.red,     "AWS Bedrock", "开始逐个推送 SSE 事件（不等生成完毕）"],
              [COLORS.purple,  "bedrock.py", "每收到 1 个 Anthropic SSE 事件 → 立即转为 1 个 BedrockStreamEvent"],
              [COLORS.green,   "chat.py", "每收到 1 个 BedrockStreamEvent → 立即转为 1 个 OpenAI SSE chunk"],
              [COLORS.accent,  "客户端", "实时收到 data: {...} 逐字输出"],
            ].map(([color, tag, text], i) => (
              <div key={i} style={{ display: "flex", gap: 8, marginBottom: 5, alignItems: "flex-start" }}>
                <div style={{
                  minWidth: 18, height: 18, borderRadius: "50%",
                  background: color as string, color: "#000",
                  fontSize: 10, fontWeight: 700,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  flexShrink: 0, marginTop: 1,
                }}>{i + 1}</div>
                <Tag color={color as string}>{tag as string}</Tag>
                <div style={{ color: COLORS.textMuted, fontSize: 11, lineHeight: "1.5" }}>{text as string}</div>
              </div>
            ))}
          </div>
          <div style={{ color: COLORS.text, fontSize: 11, marginTop: 6, fontWeight: 600, lineHeight: 1.6 }}>
            关键：没有"攒一批再发"的步骤。整个链路是 1 事件 → 1 转换 → 1 chunk 发回，延迟取决于 Bedrock 生成速度。
          </div>
        </div>

        {/* ── 非流式 vs 流式 对比图 ── */}
        <Card color={COLORS.amber} title="非流式 vs 流式 — 对比">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div style={{
              background: COLORS.bg, border: `1px solid ${COLORS.border}`,
              borderRadius: 4, padding: 8, fontSize: 10, fontFamily: "monospace", lineHeight: 1.8,
            }}>
              <div style={{ color: COLORS.green, fontWeight: 700, marginBottom: 4, fontSize: 11 }}>stream: false（非流式）</div>
              <span style={{ color: COLORS.accent }}>Client</span> ──req──▶ <span style={{ color: COLORS.purple }}>Proxy</span> ──▶ <span style={{ color: COLORS.red }}>Bedrock</span><br/>
              <span style={{ color: COLORS.textDim }}>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;（等待生成完毕...）</span><br/>
              <span style={{ color: COLORS.accent }}>Client</span> ◀──resp── <span style={{ color: COLORS.purple }}>Proxy</span> ◀── <span style={{ color: COLORS.red }}>Bedrock</span><br/>
              <br/>
              <span style={{ color: COLORS.textDim }}>一次性返回完整 JSON</span>
            </div>
            <div style={{
              background: COLORS.bg, border: `1px solid ${COLORS.red}44`,
              borderRadius: 4, padding: 8, fontSize: 10, fontFamily: "monospace", lineHeight: 1.8,
            }}>
              <div style={{ color: COLORS.red, fontWeight: 700, marginBottom: 4, fontSize: 11 }}>stream: true（流式）</div>
              <span style={{ color: COLORS.accent }}>Client</span> ──req──▶ <span style={{ color: COLORS.purple }}>Proxy</span> ──▶ <span style={{ color: COLORS.red }}>Bedrock</span><br/>
              <span style={{ color: COLORS.accent }}>Client</span> ◀ chunk1 ◀ <span style={{ color: COLORS.purple }}>Proxy</span> ◀ event1 ◀ <span style={{ color: COLORS.red }}>BR</span><br/>
              <span style={{ color: COLORS.accent }}>Client</span> ◀ chunk2 ◀ <span style={{ color: COLORS.purple }}>Proxy</span> ◀ event2 ◀ <span style={{ color: COLORS.red }}>BR</span><br/>
              <span style={{ color: COLORS.accent }}>Client</span> ◀ chunk3 ◀ <span style={{ color: COLORS.purple }}>Proxy</span> ◀ event3 ◀ <span style={{ color: COLORS.red }}>BR</span><br/>
              <span style={{ color: COLORS.accent }}>Client</span> ◀ [DONE] ◀ <span style={{ color: COLORS.purple }}>Proxy</span> ◀ &nbsp;stop &nbsp;◀ <span style={{ color: COLORS.red }}>BR</span><br/>
              <span style={{ color: COLORS.textDim }}>每个事件实时转换、立即发回</span>
            </div>
          </div>
        </Card>

        <div style={{ height: 10 }} />

        {/* ── 事件映射 ── */}
        <div style={{ color: COLORS.textDim, fontSize: 11, marginBottom: 8 }}>
          <code>bedrock.py</code> — <code>_anthropic_event_to_bedrock()</code>
          <br/><code>invoke_model_with_response_stream</code> 返回字节流，每个 chunk 解码为 JSON 后<b style={{ color: COLORS.textMuted }}>立即</b>映射为 BedrockStreamEvent。
        </div>

        <Card color={COLORS.red} title="第一跳：Anthropic SSE → BedrockStreamEvent（逐事件）">
          <MappingTable
            headers={["Anthropic 事件", "BedrockStreamEvent.type", "关键数据"]}
            rows={[
              ["message_start", "message_start", "usage.input_tokens"],
              ["content_block_start", "content_block_start", "content_block.type: text / tool_use / thinking"],
              ["content_block_delta (text_delta)", "content_block_delta", "delta.text"],
              ["content_block_delta (input_json_delta)", "content_block_delta", "delta.partial_json"],
              ["content_block_delta (thinking_delta)", "content_block_delta", "delta.thinking"],
              ["content_block_stop", "content_block_stop", "index"],
              ["message_delta", "message_delta", "usage.output_tokens, delta.stop_reason"],
              ["message_stop", "message_stop", "—"],
              ["ping", "跳过", "—"],
            ]}
          />
        </Card>

        <div style={{ height: 10 }} />

        <Card color={COLORS.accent} title="第二跳：BedrockStreamEvent → OpenAI SSE Chunk（逐事件）">
          <div style={{ color: COLORS.textMuted, fontSize: 11, marginBottom: 8, lineHeight: 1.6 }}>
            每个 BedrockStreamEvent 被<b style={{ color: COLORS.text }}>立即</b>转换为一个 <code>data: {`{...}`}\n\n</code> SSE chunk 发回客户端。部分事件不产生输出（仅内部记录 token 数），部分事件被完全跳过（thinking 块）。
          </div>
          <MappingTable
            headers={["BedrockStreamEvent", "OpenAI SSE 输出", "说明"]}
            rows={[
              ["message_start", "（无输出）", "仅捕获 input_tokens，不发 chunk"],
              ["content_block_start (text)", "（无输出）", "文本块开始标记，不发 chunk"],
              ["content_block_start (tool_use)", 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_abc","type":"function","function":{"name":"get_weather","arguments":""}}]}}]}', "发送工具调用 ID + 名称"],
              ["content_block_start (thinking)", "完全跳过", "thinking 块对客户端不可见"],
              ["content_block_delta (text)", 'data: {"choices":[{"delta":{"content":"Hello"}}]}', "逐词文本输出"],
              ["content_block_delta (partial_json)", 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"ci"}}]}}]}', "工具参数逐片段输出"],
              ["content_block_delta (thinking)", "完全跳过", "—"],
              ["message_delta", "（无输出）", "仅捕获 output_tokens + stop_reason"],
              ["message_stop", 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}', "最终 chunk，携带 finish_reason"],
              ["—", "data: [DONE]", "流结束标记"],
            ]}
          />
        </Card>

        <div style={{ height: 10 }} />

        <Card color={COLORS.amber} title="流式 Token 计数">
          <div style={{ color: COLORS.textMuted, fontSize: 11, marginBottom: 6, lineHeight: 1.6 }}>
            流式模式下，token 数不在每个 chunk 中返回，而是在特定事件中捕获后统一记录：
          </div>
          <div style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: 8, fontSize: 11, fontFamily: "monospace", lineHeight: 1.8 }}>
            message_start  ──▶  捕获 <span style={{ color: COLORS.amber }}>input_tokens</span> &nbsp;&nbsp;（流开始时，第一个事件）<br/>
            message_delta  ──▶  捕获 <span style={{ color: COLORS.amber }}>output_tokens</span> （流接近结束时）<br/>
            message_stop &nbsp; ──▶  最终 chunk 发回客户端<br/>
            &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;↓<br/>
            record_usage(<span style={{ color: COLORS.green }}>prompt_tokens</span>=input_tokens, <span style={{ color: COLORS.green }}>completion_tokens</span>=output_tokens)
          </div>
        </Card>

        <div style={{ marginTop: 12, display: "flex", justifyContent: "space-between" }}>
          <LinkSpan onClick={() => nav("translation", "phase3")} color={COLORS.green}>← Phase 3（非流式版）</LinkSpan>
          <LinkSpan onClick={() => nav("translation", "stream-converse")} color={COLORS.cyan}>Converse Streaming →</LinkSpan>
        </div>
      </div>
    ),
  },

  "stream-converse": {
    title: "Streaming: Converse (Phase 2b+3 流式版)",
    color: COLORS.cyan,
    content: (nav) => (
      <div>
        {/* ── 关系说明 ── */}
        <div style={{
          background: COLORS.cyanSoft, border: `1px solid ${COLORS.cyan}44`,
          borderRadius: 6, padding: 10, marginBottom: 12,
        }}>
          <div style={{ color: COLORS.cyan, fontSize: 12, fontWeight: 700, marginBottom: 4 }}>
            与上方 Phase 2b + Phase 3 的关系
          </div>
          <div style={{ color: COLORS.textMuted, fontSize: 11, lineHeight: 1.7 }}>
            和 Anthropic Streaming 同理 — 当 <code style={{ color: COLORS.text }}>"stream": true</code> 时，Phase 2b 改为调用 <code>converse_stream()</code>，
            Bedrock 逐个推送事件，代理<b style={{ color: COLORS.text }}>每收到一个 Converse 事件就实时转为一个 OpenAI chunk 发回客户端</b>。
          </div>
          <div style={{ color: COLORS.textDim, fontSize: 10, marginTop: 4 }}>
            区别仅在于：Converse API 的事件名用 camelCase（<code>contentBlockDelta</code>），Anthropic 用 snake_case（<code>content_block_delta</code>）。转为 BedrockStreamEvent 后格式统一，后续到 OpenAI chunk 的转换完全相同。
          </div>
        </div>

        <div style={{ color: COLORS.textDim, fontSize: 11, marginBottom: 8 }}>
          <code>bedrock.py</code> — <code>_converse_stream_event_to_bedrock()</code>
          <br/><code>converse_stream</code> API 返回的事件为字典，每个事件包含一个键，<b style={{ color: COLORS.textMuted }}>逐个</b>映射为 BedrockStreamEvent。
        </div>

        <Card color={COLORS.cyan} title="第一跳：Converse Stream → BedrockStreamEvent（逐事件）">
          <MappingTable
            headers={["Converse 事件", "BedrockStreamEvent.type", "关键数据"]}
            rows={[
              ["messageStart", "message_start", "role"],
              ["contentBlockStart (text)", "content_block_start", 'content_block.type: "text"'],
              ["contentBlockStart (toolUse)", "content_block_start", 'content_block: {type:"tool_use", id:"call_abc", name:"get_weather"}'],
              ["contentBlockDelta (text)", "content_block_delta", 'delta.text: "Hello"'],
              ["contentBlockDelta (toolUse)", "content_block_delta", 'delta.partial_json: "{\\"ci"'],
              ["contentBlockStop", "content_block_stop", "index: 0"],
              ["messageStop", "message_delta", 'delta.stop_reason: "end_turn"'],
              ["metadata", "message_delta", "usage: {input_tokens: 100, output_tokens: 50}"],
            ]}
          />
          <div style={{ color: COLORS.textDim, fontSize: 10, marginTop: 6 }}>
            转为 BedrockStreamEvent 后，后续到 OpenAI SSE chunk 的转换和 Anthropic Streaming 完全相同（见上一节 "第二跳"）。
          </div>
        </Card>

        <div style={{ marginTop: 12, display: "flex", justifyContent: "space-between" }}>
          <LinkSpan onClick={() => nav("translation", "stream-anthropic")} color={COLORS.red}>← Anthropic Streaming</LinkSpan>
          <LinkSpan onClick={() => nav("translation", "auto-fixes")} color={COLORS.amber}>Auto-fixes →</LinkSpan>
        </div>
      </div>
    ),
  },

  "auto-fixes": {
    title: "Auto-fixes & Extension Pass-through",
    color: COLORS.amber,
    content: (nav) => (
      <div>
        <Card color={COLORS.amber} title="max_tokens vs budget_tokens 自动修正">
          <div style={{ fontSize: 12, lineHeight: 1.8 }}>
            Anthropic 要求 <code>max_tokens {'>'} thinking.budget_tokens</code>。代理自动调整：
          </div>
          <div style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: 8, fontSize: 11, fontFamily: "monospace", lineHeight: 1.8, marginTop: 6 }}>
            修正前：max_tokens=2000, budget_tokens=2000 &nbsp;<span style={{ color: COLORS.red }}>（无效）</span><br/>
            修正后：max_tokens=4000, budget_tokens=2000 &nbsp;<span style={{ color: COLORS.green }}>（auto-fix）</span>
          </div>
        </Card>

        <div style={{ height: 10 }} />

        <Card color={COLORS.orange} title="temperature / top_p 互斥">
          <div style={{ fontSize: 12, lineHeight: 1.8 }}>
            Anthropic 不允许在同一请求中同时设置 <code>temperature</code> 和 <code>top_p</code>。
          </div>
          <div style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: 8, fontSize: 11, fontFamily: "monospace", lineHeight: 1.8, marginTop: 6 }}>
            如果设置了 temperature → <span style={{ color: COLORS.amber }}>忽略 top_p</span><br/>
            如果未设置 temperature → <span style={{ color: COLORS.green }}>传递 top_p</span>
          </div>
        </Card>

        <div style={{ height: 10 }} />

        <Card color={COLORS.purple} title="effort 参数自动转换（仅 Anthropic）">
          <div style={{ fontSize: 12, lineHeight: 1.8, marginBottom: 8 }}>
            用户发送 <code>{`"effort": "medium"`}</code>，代理自动包装为 Bedrock 所需格式：
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", gap: 8, alignItems: "center" }}>
            <div style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: 8, fontSize: 11, fontFamily: "monospace", lineHeight: 1.6 }}>
              <div style={{ color: COLORS.accent, marginBottom: 4 }}>用户发送：</div>
              additional_model_request_fields:<br/>
              &nbsp;&nbsp;thinking: {`{...}`}<br/>
              &nbsp;&nbsp;effort: "medium"
            </div>
            <div style={{ color: COLORS.textDim, fontSize: 16 }}>→</div>
            <div style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: 8, fontSize: 11, fontFamily: "monospace", lineHeight: 1.6 }}>
              <div style={{ color: COLORS.purple, marginBottom: 4 }}>实际发送：</div>
              thinking: {`{...}`}<br/>
              anthropic_beta: ["effort-..."]<br/>
              output_config: {`{"effort":"medium"}`}
            </div>
          </div>
        </Card>

        <div style={{ height: 10 }} />

        <Card color={COLORS.red} title="Bedrock 扩展参数透传完整链路">
          <div style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: 8, fontSize: 11, fontFamily: "monospace", lineHeight: 1.8 }}>
            客户端 body / X-Bedrock-* 请求头<br/>
            &nbsp;&nbsp;&nbsp;&nbsp;↓<br/>
            chat.py：提取请求头 → request_data<br/>
            &nbsp;&nbsp;&nbsp;&nbsp;↓<br/>
            translator.py：openai_to_bedrock()<br/>
            → BedrockRequest.additional_model_request_fields<br/>
            &nbsp;&nbsp;&nbsp;&nbsp;↓<br/>
            bedrock.py：_build_anthropic_body()<br/>
            → body.update(additional_model_request_fields)<br/>
            &nbsp;&nbsp;&nbsp;&nbsp;↓<br/>
            invoke_model(body=json.dumps(body))<br/>
            → Anthropic Messages API 接收原生字段
          </div>
        </Card>

        <div style={{ marginTop: 12 }}>
          <LinkSpan onClick={() => nav("translation", "stream-converse")} color={COLORS.cyan}>← Converse Streaming</LinkSpan>
        </div>
      </div>
    ),
  },
};

// ─── Pipeline Box ───────────────────────────────────────────────────────────

function PipelineBox({
  label, sublabel, color, active, onClick, style: extraStyle,
}: {
  label: string; sublabel: string; color: string; active: boolean; onClick: () => void; style?: React.CSSProperties;
}) {
  const softColor = color + "22";
  return (
    <div onClick={onClick} style={{
      background: active ? softColor : COLORS.surface,
      border: `1.5px solid ${active ? color : COLORS.border}`,
      borderRadius: 8, padding: "10px 14px", cursor: "pointer",
      transition: "all 0.15s",
      boxShadow: active ? `0 0 0 2px ${color}44` : "none",
      ...extraStyle,
    }}>
      <div style={{ color, fontWeight: 700, fontSize: 12, marginBottom: 3 }}>{label}</div>
      <div style={{ color: COLORS.textDim, fontSize: 10 }}>{sublabel}</div>
    </div>
  );
}

// ─── Request Translation Page ───────────────────────────────────────────────

function RequestTranslationPage({ activePhase, setActivePhase, navigateTo }: {
  activePhase: TranslationPhase | null;
  setActivePhase: (p: TranslationPhase) => void;
  navigateTo: (page: PageKey, phase?: TranslationPhase) => void;
}) {
  const toggle = (p: TranslationPhase) => setActivePhase(p);
  const detail = activePhase ? TRANSLATION_DETAIL[activePhase] : null;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: 20 }}>
      {/* Left: Pipeline diagram */}
      <div>
        <div style={{ fontSize: 10, color: COLORS.textDim, marginBottom: 4, letterSpacing: "0.08em", textTransform: "uppercase" }}>
          单个请求的转换流程
        </div>
        <div style={{ fontSize: 9, color: COLORS.textDim, marginBottom: 8, lineHeight: 1.5 }}>
          每次 POST /v1/chat/completions 经历以下三阶段（点击查看详情）
        </div>

        {/* Phase 1 */}
        <PipelineBox
          label="OpenAI Request"
          sublabel="ChatCompletionRequest"
          color={COLORS.accent}
          active={activePhase === "phase1"}
          onClick={() => toggle("phase1")}
        />

        <Arrow label="openai_to_bedrock()" />

        {/* Internal schema */}
        <div style={{
          background: COLORS.surface, border: `1px dashed ${COLORS.border}`,
          borderRadius: 8, padding: "8px 14px", textAlign: "center",
        }}>
          <div style={{ color: COLORS.textMuted, fontWeight: 600, fontSize: 12 }}>BedrockRequest</div>
          <div style={{ color: COLORS.textDim, fontSize: 10 }}>Internal Schema</div>
        </div>

        <Arrow label="" />

        {/* Dual path */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          <PipelineBox
            label="Anthropic"
            sublabel="invoke_model"
            color={COLORS.purple}
            active={activePhase === "phase2a"}
            onClick={() => toggle("phase2a")}
          />
          <PipelineBox
            label="Converse API"
            sublabel="Non-Anthropic"
            color={COLORS.cyan}
            active={activePhase === "phase2b"}
            onClick={() => toggle("phase2b")}
          />
        </div>

        <Arrow label="" />

        {/* BedrockResponse */}
        <div style={{
          background: COLORS.surface, border: `1px dashed ${COLORS.border}`,
          borderRadius: 8, padding: "8px 14px", textAlign: "center",
        }}>
          <div style={{ color: COLORS.textMuted, fontWeight: 600, fontSize: 12 }}>BedrockResponse</div>
          <div style={{ color: COLORS.textDim, fontSize: 10 }}>Unified Response</div>
        </div>

        <Arrow label="bedrock_to_openai()" />

        {/* Phase 3 */}
        <PipelineBox
          label="OpenAI Response"
          sublabel="ChatCompletionResponse"
          color={COLORS.green}
          active={activePhase === "phase3"}
          onClick={() => toggle("phase3")}
        />

        {/* Separator */}
        <div style={{ borderTop: `1px solid ${COLORS.border}`, margin: "14px 0" }} />

        {/* Streaming sections */}
        <div style={{ fontSize: 10, color: COLORS.textDim, marginBottom: 4, letterSpacing: "0.08em", textTransform: "uppercase" }}>
          stream: true 时的流式变体
        </div>
        <div style={{ fontSize: 9, color: COLORS.textDim, marginBottom: 8, lineHeight: 1.5 }}>
          上方 Phase 2→3 是等完整响应再返回；<br/>
          下方是 <code style={{ color: COLORS.textMuted }}>stream: true</code> 时的替代路径 —<br/>
          Bedrock 逐个推送 SSE 事件，代理<b style={{ color: COLORS.textMuted }}>每收到一个事件就实时转换为一个 OpenAI chunk 发回客户端</b>。
        </div>

        <PipelineBox
          label="Streaming (Anthropic)"
          sublabel="Phase 2a+3 流式版：逐事件转换"
          color={COLORS.red}
          active={activePhase === "stream-anthropic"}
          onClick={() => toggle("stream-anthropic")}
          style={{ marginBottom: 8 }}
        />

        <PipelineBox
          label="Streaming (Converse)"
          sublabel="Phase 2b+3 流式版：逐事件转换"
          color={COLORS.cyan}
          active={activePhase === "stream-converse"}
          onClick={() => toggle("stream-converse")}
          style={{ marginBottom: 8 }}
        />

        <PipelineBox
          label="Auto-fixes & Extensions"
          sublabel="max_tokens, temperature/top_p, effort"
          color={COLORS.amber}
          active={activePhase === "auto-fixes"}
          onClick={() => toggle("auto-fixes")}
        />

        {/* Back link */}
        <div style={{ marginTop: 14 }}>
          <LinkSpan onClick={() => navigateTo("arch")} color={COLORS.purple}>
            ← 返回 Architecture（Backend 层）
          </LinkSpan>
        </div>

        {/* File reference */}
        <div style={{ marginTop: 14, fontSize: 10, color: COLORS.textDim }}>
          <div style={{ marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.08em" }}>文件参考</div>
          <div style={{ lineHeight: 1.8, color: COLORS.textMuted, fontSize: 10 }}>
            <code>api/v1/endpoints/chat.py</code> — 入口点<br/>
            <code>services/translator.py</code> — OpenAI ↔ Bedrock<br/>
            <code>services/bedrock.py</code> — AWS API 调用<br/>
            <code>schemas/openai.py</code> — OpenAI 模型<br/>
            <code>schemas/bedrock.py</code> — Bedrock 模型
          </div>
        </div>
      </div>

      {/* Right: Detail panel */}
      <div>
        <div style={{ fontSize: 10, color: COLORS.textDim, marginBottom: 8, letterSpacing: "0.08em", textTransform: "uppercase" }}>
          详细信息
        </div>
        <div style={{
          background: COLORS.surface, border: `1px solid ${COLORS.border}`,
          borderRadius: 10, padding: 16,
          maxHeight: "calc(100vh - 160px)", overflowY: "auto",
        }}>
          {detail ? (
            <div>
              <h3 style={{ color: detail.color, marginBottom: 10 }}>{detail.title}</h3>
              {detail.content(navigateTo)}
            </div>
          ) : (
            <div style={{ color: COLORS.textDim, fontSize: 13, paddingTop: 40, textAlign: "center" }}>
              ← 点击左侧任意阶段查看详情
            </div>
          )}
        </div>

        {/* Bottom: Request flow animation */}
        <div style={{ marginTop: 16 }}>
          <div style={{ fontSize: 10, color: COLORS.textDim, marginBottom: 8, letterSpacing: "0.08em", textTransform: "uppercase" }}>
            数据格式转换链路
          </div>
          <div style={{ background: COLORS.surface, border: `1px solid ${COLORS.border}`, borderRadius: 10, padding: 14 }}>
            {[
              [COLORS.accent,  "Client", "POST /v1/chat/completions (OpenAI 格式)", "phase1"],
              [COLORS.purple,  "chat.py", "提取 X-Bedrock-* 请求头", null],
              [COLORS.accent,  "Translator", "openai_to_bedrock() → BedrockRequest (内部 schema)", "phase1"],
              [COLORS.purple,  "BedrockClient", "Anthropic: _build_anthropic_body() | 其他: _build_converse_params()", "phase2a"],
              [COLORS.red,     "AWS", "invoke_model() / converse() → AWS Bedrock", null],
              [COLORS.green,   "Parse", "Anthropic JSON / Converse 响应 → BedrockResponse", "phase3"],
              [COLORS.accent,  "Translator", "bedrock_to_openai() → ChatCompletionResponse", "phase3"],
              [COLORS.accent,  "Client", "OpenAI JSON 响应 / SSE 流式响应", null],
            ].map(([color, tag, text, linkPhase], i) => (
              <div key={i} style={{ display: "flex", gap: 8, marginBottom: 7, alignItems: "flex-start" }}>
                <div style={{
                  minWidth: 18, height: 18, borderRadius: "50%",
                  background: color as string, color: "#000",
                  fontSize: 10, fontWeight: 700,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  flexShrink: 0, marginTop: 1,
                }}>{i + 1}</div>
                <Tag color={color as string}>{tag as string}</Tag>
                <div style={{ color: COLORS.textMuted, fontSize: 12, lineHeight: "1.5" }}>
                  {linkPhase ? (
                    <LinkSpan onClick={() => setActivePhase(linkPhase as TranslationPhase)} color={COLORS.cyan}>
                      {text as string}
                    </LinkSpan>
                  ) : (text as string)}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Main App ───────────────────────────────────────────────────────────────

export default function App() {
  const [page, setPage] = useState<PageKey>("arch");
  const [translationPhase, setTranslationPhase] = useState<TranslationPhase | null>(null);

  const navigateTo = (targetPage: PageKey, phase?: TranslationPhase) => {
    setPage(targetPage);
    if (targetPage === "translation" && phase) {
      setTranslationPhase(phase);
    }
    if (targetPage === "arch") {
      setTranslationPhase(null);
    }
  };

  return (
    <div style={{ background: COLORS.bg, minHeight: "100vh", fontFamily: "'JetBrains Mono', 'Fira Code', monospace", color: COLORS.text }}>
      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "28px 16px" }}>

        {/* Header */}
        <div style={{ marginBottom: 4 }}>
          <h1 style={{ fontSize: 20, fontWeight: 800, color: COLORS.text, margin: 0 }}>kolya-br-proxy</h1>
          <p style={{ color: COLORS.textMuted, fontSize: 12, margin: "3px 0 0" }}>
            AI Gateway — OpenAI-compatible proxy for AWS Bedrock models (Claude, Nova, DeepSeek, etc.)
          </p>
        </div>

        {/* Tab navigation */}
        <TabNav page={page} setPage={(p) => { setPage(p); if (p === "arch") setTranslationPhase(null); }} />

        {/* Page content */}
        {page === "arch" && <ArchitecturePage navigateTo={navigateTo} />}
        {page === "translation" && (
          <RequestTranslationPage
            activePhase={translationPhase}
            setActivePhase={setTranslationPhase}
            navigateTo={navigateTo}
          />
        )}
      </div>
    </div>
  );
}

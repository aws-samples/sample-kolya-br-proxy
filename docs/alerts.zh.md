# 用量告警

用量告警监控 API Token 和团队的消费情况，当超过阈值时通知管理员。

## 架构

```
API 请求 → record_usage() → check_alerts_for_usage() → AlertNotification (应用内)
                                                       → SES 邮件 (可选)
```

告警检查在每次使用量记录提交后**同步执行** — 不是定时任务，确保实时检测零延迟。

## 告警类型

### 软告警（绝对金额）

当消费达到绝对金额时触发。**所有 token** 均可使用，无需配额配置。

| 规则 Key | 标签 | 单位 | 时间窗口 |
|----------|------|------|---------|
| `monthly_cost` | 月费用达到 | $ | 本月1号 00:00 → 当前 |
| `daily_cost` | 日费用达到 | $ | 今天 00:00 → 当前 |
| `hourly_cost` | 时费用达到 | $ | 当前整点 XX:00 → 当前 |
| `lifetime_cost` | 总费用达到 | $ | 全部历史 |

所有时间窗口均为**固定窗口**（非滑动），到边界自动重置。

### 硬告警（配额百分比）

当消费达到配额百分比时触发。仅对**有配额的 token** 可用。

| 规则 Key | 标签 | 单位 | 前提条件 |
|----------|------|------|---------|
| `lifetime_quota_pct` | 总配额使用 | % | Token 设置了 `quota_usd` |
| `monthly_quota_pct` | 月配额使用 | % | Token 属于团队（有 `allocated_usd`） |
| `daily_limit_pct` | 日限额使用 | % | 团队 Key + 团队开启 `daily_limit_enabled` |
| `team_budget_pct` | 团队预算使用 | % | 团队范围规则（基于 `monthly_budget_usd`） |

## 按 Token 类型显示的规则

前端根据 token 配置动态展示可用规则：

| Token 类型 | 可选规则 |
|-----------|---------|
| 独立 Key，无配额 | `monthly_cost`、`daily_cost`、`hourly_cost`、`lifetime_cost` |
| 独立 Key，有 `quota_usd` | 仅 `lifetime_quota_pct` |
| 团队 Key | `monthly_quota_pct` + `lifetime_quota_pct` |
| 团队 Key + 开启日限额 | `monthly_quota_pct` + `lifetime_quota_pct` + `daily_limit_pct` |
| 团队范围规则（Teams 页面） | `team_budget_pct` |

## 通知渠道

每条规则独立配置通知方式：

- **应用内通知**（默认启用）— 创建 `AlertNotification` 记录，通过顶部铃铛图标查看
- **邮件**（可选）— 通过 AWS SES 发送到逗号分隔的邮箱地址列表

邮件同样用于 **API Key 分发** 功能（Tokens 页面 → 邮件动作），把某个 Key 的明文值
发送给其关联收件人。两者共用下方的同一套 SES 配置。

## 冷却机制

每条规则有 `cooldown_hours` 设置（默认 24 小时）。触发后，同一规则在冷却期内不会重复触发，防止通知风暴。

## 数据模型

### AlertRule（告警规则）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `user_id` | UUID FK | 所属用户 |
| `token_id` | UUID FK (可空) | Token 范围（删除时级联） |
| `team_id` | UUID FK (可空) | 团队范围（删除时级联） |
| `alert_type` | VARCHAR(20) | `soft` 或 `hard` |
| `rule_key` | VARCHAR(50) | 规则标识 |
| `threshold_value` | NUMERIC(12,4) | 触发阈值 |
| `cooldown_hours` | INTEGER | 通知间隔小时数 |
| `notify_email` | TEXT | 逗号分隔的邮箱地址 |
| `notify_in_app` | BOOLEAN | 是否创建应用内通知 |
| `is_active` | BOOLEAN | 启用/停用（不删除规则） |

约束：`token_id` 和 `team_id` 互斥。

### AlertNotification（告警通知）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `user_id` | UUID FK | 接收用户 |
| `alert_rule_id` | UUID FK (可空) | 来源规则（规则删除时置空） |
| `rule_key` | VARCHAR(50) | 反范式化，便于展示 |
| `scope_type` | VARCHAR(20) | `token` 或 `team` |
| `scope_name` | VARCHAR(255) | 触发时的 Token/团队名称 |
| `current_value` | NUMERIC(12,4) | 触发时的当前值 |
| `threshold_value` | NUMERIC(12,4) | 配置的阈值 |
| `message` | TEXT | 可读消息 |
| `is_read` | BOOLEAN | 已读状态 |

## API 接口

所有接口需要 `manage_api_keys` 权限。

```
POST   /admin/alerts/rules                          — 创建规则
GET    /admin/alerts/rules?token_id=&team_id=       — 列出规则
PUT    /admin/alerts/rules/{rule_id}                — 更新规则
DELETE /admin/alerts/rules/{rule_id}                — 删除规则
GET    /admin/alerts/notifications?unread_only=&limit= — 通知列表
GET    /admin/alerts/notifications/unread-count      — 未读计数
POST   /admin/alerts/notifications/{id}/read        — 标记已读
POST   /admin/alerts/notifications/read-all         — 全部已读
```

## 前端集成

- **Token 页面**：每个 token 的告警铃铛图标 → 弹窗管理该 token 的规则
- **Team 页面**：每个团队的告警铃铛图标 → 弹窗管理团队范围规则
- **顶部栏**：通知铃铛 + 未读角标，每 15 秒轮询
- **通知面板**：显示未读告警，点击标记已读，支持"全部已读"

## 告警检查流程

```python
async def check_alerts_for_usage(token_id, user_id, db):
    # 1. 加载该 token 的活跃规则
    # 2. 如果 token 属于团队，也加载团队范围规则
    # 3. 无规则则跳过
    # 4. 批量冷却检查 — 单条 SQL 查所有规则最近通知时间
    # 5. 单条聚合 SQL：total、monthly、daily、hourly 费用
    # 6. 团队规则：聚合团队全部成员使用量
    # 7. 为每条规则计算当前值（$ 或 %）
    # 8. 超阈值 + 过冷却 → 触发通知
    # 9. 批量插入通知记录，邮件通过 asyncio.to_thread 异步发送
```

## 配置项

| 变量 | 说明 |
|------|------|
| `KBR_ALERT_SES_SENDER_EMAIL` | SES 验证发件人（如 `noreply@kbp.kolya.fun`） |
| `KBR_ALERT_SES_REGION` | SES 的 AWS 区域（默认使用 `AWS_REGION`） |

如果未配置 `ALERT_SES_SENDER_EMAIL`，邮件通知会静默跳过（后端日志打印
`SES sender not configured, cannot send email`，API Key 通知接口返回 `502`）。

## 开启邮件发送（SES 配置）

以下命令均针对后端所在区域（生产环境为 `us-east-1`）。先执行
`export AWS_PROFILE=<admin-profile>`。步骤 1–3 每个 AWS 账号/区域只需做一次，
步骤 4 每次部署执行。

### 1. 将 SES 移出 sandbox（申请 production access）

新的 SES 账号处于 **sandbox** 模式 —— 只能发给预先验证过的地址。每个区域申请一次
production access：

```bash
aws sesv2 put-account-details \
  --production-access-enabled \
  --mail-type TRANSACTIONAL \
  --website-url "https://kbp.kolya.icu" \
  --contact-language EN \
  --use-case-description "Internal transactional emails: delivering API keys to colleagues and usage/quota alerts. Internal recipients only, <50 emails/day." \
  --region us-east-1
```

查看状态（AWS 审核需几小时到约一个工作日）：

```bash
aws sesv2 get-account --region us-east-1 \
  --query '{ProductionAccessEnabled:ProductionAccessEnabled,SendingEnabled:SendingEnabled,ReviewStatus:Details.ReviewDetails.Status}'
```

`ProductionAccessEnabled: true` 且 `ReviewStatus: GRANTED` 即通过。

> 测试**不一定**需要 production access —— 如果只发给已验证的地址（步骤 2），可以跳过此步。
> 要给任意收件人发邮件时才需要。

### 2. 验证发件身份

发件地址（`KBR_ALERT_SES_SENDER_EMAIL`）必须是已验证的 SES 身份，即使 production
access 已通过也是如此：

```bash
aws ses verify-email-identity --email-address <sender@example.com> --region us-east-1
```

该命令会发一封确认邮件 —— 点击其中的链接。然后确认：

```bash
aws sesv2 get-email-identity --email-identity <sender@example.com> --region us-east-1 \
  --query '{Type:IdentityType,Verified:VerifiedForSendingStatus}'
```

`Verified: true` 即就绪。（也支持用 `verify-domain-identity` + DNS 记录验证整个域名，
而非单个地址。）

> 企业域名（如 `@amazon.com`）的邮件网关可能拦截 AWS 验证邮件 —— 留意垃圾箱，
> 或改用你能在外部收信的地址。

### 3. 确认 IAM 权限

后端 pod 的角色（EKS Pod Identity，命名空间 `kbp` 下的 SA `backend`）需要
`ses:SendEmail` / `ses:SendRawEmail`。本项目中它已包含在 `*-backend-bedrock` 策略里。
验证方式：

```bash
ASSOC=$(aws eks list-pod-identity-associations --cluster-name <cluster> --region us-east-1 \
  --query "associations[?serviceAccount=='backend'&&namespace=='kbp'].associationId | [0]" --output text)
ROLE=$(aws eks describe-pod-identity-association --cluster-name <cluster> --region us-east-1 \
  --association-id "$ASSOC" --query 'association.roleArn' --output text)
# 检查该角色附加的策略中是否含 ses:SendEmail
```

### 4. 配置后端并重启

把已验证的发件人加到后端 ConfigMap 源文件
（`k8s/application/backend-configmap.yaml`）：

```yaml
data:
  KBR_ALERT_SES_SENDER_EMAIL: "<sender@example.com>"
```

应用并滚动重启：

```bash
kubectl apply -f k8s/application/backend-configmap.yaml
kubectl rollout restart deploy/backend -n kbp
kubectl rollout status deploy/backend -n kbp
# 确认变量进入新 pod
kubectl exec -n kbp deploy/backend -- printenv KBR_ALERT_SES_SENDER_EMAIL
```

邮件发送即生效。触发一条告警，或用 Tokens 页面的邮件动作测试。

# Kolya BR Proxy — 部署 SOP

本文档涵盖 AWS EKS 上的完整部署和销毁流程。

本地开发环境搭建请参考 [README 快速开始](../README.zh.md#快速开始)。

---

## 架构概览

| 组件 | 技术 | 说明 |
|------|------|------|
| **计算** | EKS（Standard 或 Auto Mode） | Standard：Managed Node Groups + Karpenter；Auto：完全 AWS 托管 |
| **数据库** | Aurora PostgreSQL 16（Provisioned 或 Serverless v2） | Provisioned：`db.r6g.large`；Serverless：0.5–8 ACU 自动扩缩 |
| **认证** | AWS Cognito 和/或 Microsoft Entra ID | 支持双 SSO — 部署时选择一种或两种 |
| **RBAC** | Entra ID Group Sync | Azure AD 安全组 → 角色/权限映射 |
| **密钥** | AWS Secrets Manager + ExternalSecret Operator | 零密钥入库；ESO 同步到 K8s Pod |
| **网络** | ALB（AWS LB Controller）+ 可选 Global Accelerator | ALB 就绪后自动启用 WAF |

---

## 前置条件

| 工具 | 安装方式 |
|------|---------|
| AWS CLI v2 | `brew install awscli` |
| Terraform >= 1.0 | `brew install terraform` |
| kubectl | `brew install kubectl` |
| Helm | `brew install helm` |
| Docker | Docker Desktop / OrbStack |
| jq | `brew install jq` |

`deploy-all.sh` 会在执行前自动检查所有工具是否已安装。

### AWS 账户

- 需要拥有创建 VPC、EKS、RDS、IAM、ACM、Route 53 和 ECR 资源权限的 AWS 账户
- AWS CLI 已配置有效凭证（`aws configure`、SSO 或环境变量）
- 已注册并通过 Route 53 管理的域名（默认：`kolya.fun`）

### 认证（部署时选择）

| 选项 | 说明 |
|------|------|
| **AWS Cognito** | 托管用户池，支持邮箱/密码自注册。适合自助注册场景。 |
| **Microsoft Entra ID** | 企业 SSO（Azure AD）。支持 Group Sync RBAC 实现组织级访问控制。 |
| **两者都用** | Cognito 对外部用户 + Entra ID 对内部团队。用户可关联账户。 |

`deploy-all.sh` 步骤 0 会提示选择认证方式。后续可通过 `./deploy-all.sh --configure auth` 修改。

---

## A. 首次部署（新账户或新区域）

### 1. 配置 AWS 凭证

```bash
# 方式一：SSO 配置文件
aws sso login --profile <your-profile>
export AWS_PROFILE=<your-profile>

# 方式二：环境变量
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...

# 设置目标区域
export AWS_REGION=us-west-1   # 或其他区域
```

### 2. 创建 ACM 证书

**一张证书**通过 SAN（主题备用名称）同时覆盖两个域名（`kbp.kolya.fun` 和 `api.kbp.kolya.fun`）。证书必须与 ALB 在**同一区域**。

#### 2a. 申请证书

```bash
CERT_ARN=$(aws acm request-certificate \
  --region $AWS_REGION \
  --domain-name kbp.kolya.fun \
  --subject-alternative-names "api.kbp.kolya.fun" \
  --validation-method DNS \
  --query 'CertificateArn' \
  --output text)

echo "证书 ARN：$CERT_ARN"
```

#### 2b. 获取 DNS 验证 CNAME 记录

ACM 会为每个域名生成一条 CNAME 验证记录，执行以下命令查看：

```bash
aws acm describe-certificate \
  --region $AWS_REGION \
  --certificate-arn $CERT_ARN \
  --query 'Certificate.DomainValidationOptions[*].{域名:DomainName,记录名:ResourceRecord.Name,记录值:ResourceRecord.Value}' \
  --output table
```

输出示例（每个域名一条记录）：

```
-----------------------------------------------------------------------
|                       DescribeCertificate                           |
+---------------------+----------------------+------------------------+
|        域名         |        记录名        |        记录值          |
+---------------------+----------------------+------------------------+
|  kbp.kolya.fun      |  _abc123.kbp...      |  _def456.acm-...       |
|  api.kbp.kolya.fun  |  _abc123.api.kbp...  |  _ghi789.acm-...       |
+---------------------+----------------------+------------------------+
```

> **提示：** 如果两个域名属于同一根域名，ACM 可能只生成一条 CNAME 记录，只需添加一条即可。

#### 2c. 在 Route 53 中添加 CNAME 记录

先获取托管区域 ID：

```bash
ZONE_ID=$(aws route53 list-hosted-zones-by-name \
  --dns-name kolya.fun \
  --query 'HostedZones[0].Id' \
  --output text | cut -d'/' -f3)

echo "托管区域 ID：$ZONE_ID"
```

将上一步表格中的每条 CNAME 记录添加到 Route 53（每条记录执行一次）：

```bash
aws route53 change-resource-record-sets \
  --hosted-zone-id $ZONE_ID \
  --change-batch '{
    "Changes": [
      {
        "Action": "UPSERT",
        "ResourceRecordSet": {
          "Name": "<上表中的记录名>",
          "Type": "CNAME",
          "TTL": 300,
          "ResourceRecords": [{"Value": "<上表中的记录值>"}]
        }
      }
    ]
  }'
```

#### 2d. 等待证书签发

DNS 传播通常需要 1–5 分钟。轮询直到状态变为 `ISSUED`：

```bash
while true; do
  STATUS=$(aws acm describe-certificate \
    --region $AWS_REGION \
    --certificate-arn $CERT_ARN \
    --query 'Certificate.Status' \
    --output text)
  echo "$(date '+%H:%M:%S')  状态：$STATUS"
  [[ "$STATUS" == "ISSUED" ]] && break
  sleep 15
done
echo "证书已签发：$CERT_ARN"
```

#### 2e. 保存证书 ARN

记录 `$CERT_ARN`，步骤 4（K8s 应用部署）中 `deploy-all.sh` 会提示输入。

```bash
echo $CERT_ARN
# arn:aws:acm:us-west-1:612674025488:certificate/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

### 3. 创建 Terraform 状态 S3 存储桶

```bash
aws s3 mb s3://tf-state-<account-id>-${AWS_REGION}-kolya --region $AWS_REGION
```

### 4. 执行部署

```bash
./deploy-all.sh --region $AWS_REGION
```

脚本将交互式引导你完成：

| 步骤 | 操作内容 |
|------|---------|
| 预检 | 验证 AWS 凭证，检查工具安装 |
| **步骤 0** | 配置 `terraform.tfvars` — 自动检测账户/区域，选择**认证方式**（Cognito / Entra ID / 两者），选择**运维模式**（Standard / Low-Ops），设置域名 |
| S3 后端 | 提示 bucket 名称，从模板生成 `iac/providers.tf` |
| Workspace | 选择或创建 Terraform workspace |
| **步骤 1** | `terraform init` + `plan` + `apply`（VPC、EKS、Aurora PostgreSQL、Cognito、IAM） |
| **步骤 2** | 部署 Helm charts（ALB Controller、Karpenter、Metrics Server、ESO、Redis）。Low-Ops 模式下 EKS 内置组件自动跳过。 |
| **步骤 3** | 构建并推送 Docker 镜像到 ECR |
| **步骤 4** | 部署 K8s 应用（ConfigMap、ExternalSecrets、Deployments、Ingress）。ALB 就绪后自动启用 WAF。 |
| **步骤 5** | （可选）Global Accelerator 开关 |

#### 步骤依赖关系

```
步骤 0 ─── 写入 ──→ terraform.tfvars（唯一配置源）
  │
  ├──→ 步骤 1 读取 tfvars ──→ terraform apply ──→ 产出 state + outputs
  │         │
  │         ├──→ 步骤 2 读取 tfvars（EKS 模式）+ terraform output（cluster_name）
  │         │         │
  │         │         └──→ 步骤 4 读取 terraform output（ECR URI、域名等）
  │         │
  │         └──→ 步骤 3 读取 terraform output（ECR 仓库地址）
  │
  └──→ 步骤 5 读写 tfvars + 执行 terraform apply
```

- **步骤 0 → 所有后续步骤**：步骤 0 将 `ops_low`、`enable_cognito`、`region` 等写入 `terraform.tfvars`，后续步骤均从此文件读取配置。
- **步骤 1 → 步骤 2/3/4**：步骤 1 产出 Terraform state。步骤 2 从 `terraform output` 读取 `cluster_name` 配置 kubectl；步骤 3 读取 ECR 仓库地址；步骤 4 读取域名、数据库端点等。
- **步骤 2 → 步骤 4**：Helm charts（ESO、Redis、ALB Controller）必须先运行，应用才能部署。
- **单独运行某步骤**：`--step N` 会跳过之前的步骤，但假定它们已成功完成。如果步骤 0 的配置有变更，需先重新运行步骤 1，再运行步骤 2。

部署完成后，如需配置 Microsoft Entra ID SSO：

```bash
./deploy-all.sh --configure auth
```

### 5.（可选）启用 Global Accelerator

```bash
./deploy-all.sh --step 5
```

---

## B. 部署到新区域（已有其他区域在运行）

每个区域使用独立的 Terraform state，不会冲突。资源名称包含区域信息，不会重叠。

**关键步骤：重置 `providers.tf`**

如果 `iac/providers.tf` 已存在（指向旧区域的 state bucket），需要先删除：

```bash
rm iac/providers.tf
```

`deploy-all.sh` 会提示你配置新区域的 S3 后端。

然后按照[章节 A](#a-首次部署新账户或新区域) 从步骤 1 开始。

---

## C. 日常运维

```bash
# 执行单个步骤
./deploy-all.sh --step 0       # 配置 terraform.tfvars
./deploy-all.sh --step 1       # 仅 Terraform
./deploy-all.sh --step 2       # 仅 Helm
./deploy-all.sh --step 3       # 仅 Docker 构建
./deploy-all.sh --step 4       # 仅应用部署
./deploy-all.sh --step 5       # Global Accelerator 开关

# 交互式配置认证提供商
./deploy-all.sh --configure auth       # 添加/更新 Microsoft 或 Cognito OAuth
./deploy-all.sh --configure secrets    # 更新 Secrets Manager 中的单个密钥
./deploy-all.sh --configure view       # 查看当前配置状态

# 跳过确认提示（CI/CD 场景）
./deploy-all.sh --yes

# K8s 管理
cd k8s && ./deploy.sh status   # 查看应用状态
cd k8s && ./deploy.sh logs     # 查看日志
cd k8s && ./deploy.sh update   # 更新应用配置
```

### 添加或切换认证提供商

部署后可随时添加或切换认证提供商：

```bash
./deploy-all.sh --configure auth
# 选项：
#   1) 添加/更新 Microsoft Entra ID (SSO)  → 提示输入 Client ID、Secret、Tenant ID
#   2) 开关 Cognito                        → 更新 terraform.tfvars + 执行 terraform apply
#   3) 查看当前认证状态
```

脚本将凭证写入 AWS Secrets Manager → ExternalSecret 同步到 Pod → 重启后端：

```bash
kubectl rollout restart deploy/backend -n kbp
```

> **首次配置 Entra ID？** 需要先在 Azure Portal 注册应用。参见下方 [Microsoft Entra ID 配置](#microsoft-entra-id-配置) 的完整步骤（约 3 分钟）。

---

## D. 切换区域

`iac/providers.tf` 决定 Terraform 操作哪个区域的 state。切换方法：

```bash
# 1. 删除当前 providers.tf
rm iac/providers.tf

# 2. 对目标区域重新执行 deploy-all.sh
./deploy-all.sh --region <target-region>
# 会提示配置新的 S3 后端
```

或手动操作：

```bash
# 1. 删除当前 providers.tf
rm iac/providers.tf

# 2. 从模板重新生成 providers.tf
cd iac
# 输入目标区域的 S3 bucket 和 region

# 3. 重新初始化 Terraform
terraform init -reconfigure
```

---

## E. `deploy-all.sh` 自动处理的事项

| 关注点 | 处理方式 |
|--------|---------|
| 账户/区域变量 | 由步骤 0 写入 `terraform.tfvars`（唯一配置来源） |
| 域名 | 由步骤 0 写入 `terraform.tfvars`；后续所有步骤从中读取 |
| Terraform 后端 | 首次运行时从 `providers.tf.template` 生成 |
| Terraform workspace | 每个步骤都会交互式选择并确认 |
| WAF / GA / Cognito 开关 | 持久化在 `terraform.tfvars` 中；步骤 0 从 state 自动检测 |
| WAF 顺序 | 步骤 4 ALB 就绪后自动写入 `terraform.tfvars` 并启用 |
| Global Accelerator | 默认禁用，通过 `--step 5` 切换（更新 `terraform.tfvars`） |
| Cognito 回调 URL | 从 `terraform.tfvars` 中的 `frontend_domain` 自动派生 |
| ESO 凭证 | Pod Identity → `external-secrets` 命名空间中的 ESO 控制器 |

---

## F. 销毁（Teardown）

使用 `destroy.sh` 安全地销毁指定账户、区域和 workspace 的所有资源。

### 用法

```bash
# 交互式模式（提示所有参数）
./destroy.sh

# 指定账户和区域
./destroy.sh --account 123456789012 --region us-west-1

# 指定所有参数
./destroy.sh --account 123456789012 --region us-west-1 --workspace kolya
```

### 执行流程

1. **验证 AWS 身份** — 校验凭证，确认账户 ID、区域和 workspace
2. **检查 EKS 集群** — 如果集群存在，连接并列出 `kbp` 命名空间中的所有资源
3. **清理 K8s 资源** — 先删除 Ingress（触发 ALB 清理），等待 30 秒，再删除 ExternalSecrets、剩余资源和命名空间
4. **配置 Terraform 后端** — 如果 `providers.tf` 不存在，提示输入 S3 bucket
5. **验证 workspace** — 确保 workspace 在后端中存在
6. **执行 `terraform plan -destroy`** — 显示将要销毁的资源
7. **最终确认** — 需要输入 `destroy` 才能继续
8. **执行 `terraform destroy`** — 销毁所有基础设施

### 注意事项

- K8s 资源（特别是 Ingress/ALB）**必须**在 Terraform destroy 之前删除，否则 ALB 和 target group 会阻塞 Terraform
- 脚本会自动先清理 K8s 资源
- 如果 EKS 集群不存在（已被销毁），K8s 清理会被跳过
- `--account` 和 `--region` 具有最高优先级；提供后跳过自动检测，但仍会验证是否与当前凭证匹配

### 示例：完整销毁

```bash
# 1. 确保 AWS 凭证已配置为目标账户
export AWS_PROFILE=my-profile
aws sso login --profile my-profile

# 2. 执行销毁
./destroy.sh --account 123456789012 --region us-west-1 --workspace kolya

# 3.（可选）如果不再需要，删除 S3 state bucket
aws s3 rb s3://tf-state-123456789012-us-west-1-kolya --force --region us-west-1
```

---

## 生产环境与非生产环境配置差异

Terraform workspace（`prod` vs 其他）决定资源规格：

| 类别 | 配置项 | 非生产环境 | 生产环境 |
|------|--------|----------|---------|
| **Backend Pod** | CPU 请求/限制 | 250m / 500m | 500m / 1000m |
| | 内存请求/限制 | 384Mi / 768Mi | 512Mi / 1024Mi |
| | HPA 副本范围 | 2–5 | 3–16 |
| **Frontend Pod** | CPU 请求/限制 | 30m / 100m | 50m / 200m |
| | 内存请求/限制 | 64Mi / 128Mi | 128Mi / 256Mi |
| | HPA 副本范围 | 1–2 | 2–4 |
| **EKS 核心节点（Standard）** | 实例类型 | `t4g.small` | `t4g.medium` |
| | EBS 卷大小 | 30 GB | 100 GB |
| **Karpenter 节点（Standard）** | 实例类别 | `t`（t4g） | `m`（m7g） |
| | EBS 卷大小 | 30 GB | 100 GB |
| | CPU 上限 | 100 | 1000 |
| | 内存上限 | 100 Gi | 1000 Gi |
| **EKS Auto Mode NodePool** | 架构 | arm64（Graviton） | arm64（Graviton） |
| | 实例类别 | `c`, `m`, `r`（gen > 4） | `c`, `m`, `r`（gen > 4） |
| | CPU 上限 | 1000 | 1000 |
| | 内存上限 | 1000 Gi | 1000 Gi |
| | 容量类型 | On-Demand | On-Demand |
| **RDS Aurora PostgreSQL** | 实例规格（Standard） | `db.r6g.large`（2 vCPU / 16 GB） | `db.r6g.large`（2 vCPU / 16 GB） |
| | 实例规格（Low-Ops） | `db.serverless`（0.5–4 ACU） | `db.serverless`（0.5–8 ACU） |
| | 存储 | 自动扩展（10 GB → 128 TB） | 自动扩展（10 GB → 128 TB） |
| | Performance Insights | 开启 | 开启 |
| | 删除保护 | 关闭 | 开启 |
| | 备份保留天数 | 1 天 | 7 天 |
| | 备份时间窗口 | 未设置 | 03:00-04:00 UTC |
| | 快照标签复制 | 否 | 是 |
| | 跳过最终快照 | 是 | 否 |
| | 立即应用变更 | 是 | 否 |
| | CloudWatch 日志导出 | 无 | `["postgresql"]` |
| | 监控间隔（秒） | 0（关闭） | 60 |
| **Cognito** | 高级安全模式 | `AUDIT` | `ENFORCED` |
| | 删除保护 | 关闭 | 开启 |
| **Global Accelerator** | 流日志 | 关闭 | 开启 |

---

## Aurora PostgreSQL 存储与容量

部署支持两种 Aurora 模式，通过步骤 0 的**运维模式**选择：

| 模式 | 实例 | 扩缩方式 | 特点 |
|------|------|---------|------|
| **Provisioned**（Standard） | `db.r6g.large`（2 vCPU，16 GB） | 固定 | 稳定负载，固定成本 |
| **Serverless v2**（Low-Ops） | `db.serverless`（0.5–8 ACU） | 秒级自动扩缩 | 弹性负载，空闲低成本 |

### 存储

两种模式下 Aurora 存储均为**全托管自动扩展** — 无需配置磁盘大小：

- 起始 10 GB，自动按 10 GB 增量扩展
- 最大：128 TB
- 计费：$0.10/GB/月（仅按实际使用量计费）
- 对于 AI Gateway 工作负载（元数据 + 使用记录），预计数年内 < 10 GB

### 成本对比（us-west-2）

| 模式 | 空闲成本 | 活跃成本 |
|------|---------|---------|
| Provisioned `db.r6g.large` | ~$185/月（常开） | ~$185/月 |
| Serverless v2（最低 0.5 ACU） | ~$44/月 | 随负载扩展（8 ACU 时约 ~$350/月） |

### Provisioned：何时需要升级实例

| 指标 | 当前（`db.r6g.large`） | 考虑升级 |
|------|----------------------|---------|
| 并发数据库连接 | 舒适支撑 ~500 | > 500 → `db.r6g.xlarge` |
| CPU 利用率（CloudWatch） | < 70% 持续 | > 70% 持续 |
| 可用内存 | > 4 GB | < 2 GB |

对于 AI Gateway 场景（轻量 CRUD，大部分延迟在 Bedrock 侧），`db.r6g.large` 足以支撑到数千并发用户。

### Serverless v2：ACU 配置

| 环境 | 最低 ACU | 最高 ACU | 说明 |
|------|---------|---------|------|
| 非生产 | 0.5 | 4 | 空闲时缩到接近零 |
| 生产 | 0.5 | 8 | 更高上限应对流量尖峰 |

1 ACU ≈ 2 GB RAM + 对应 CPU。扩缩自动完成，秒级响应。

---

## Microsoft Entra ID 配置

完整 OAuth 配置指南参见 [OAuth Setup Guide](oauth-setup.md#microsoft-entra-id-azure-ad)。

### 快速配置（3 分钟）

**1. Azure Portal — 注册应用：**

```
Azure Portal > App registrations > New registration
  Name:              Kolya BR Proxy
  Account types:     Multi-tenant (any org + personal)
  Redirect URI:      Web → https://<frontend-domain>/auth/microsoft/callback
```

**2. 创建 Client Secret：**

```
Certificates & secrets > New client secret
  Description:   Kolya BR Proxy
  Expiry:        24 months
  → 立即复制 Value（仅显示一次）
```

**3. API 权限（关键）：**

```
API permissions > Add permission > Microsoft Graph > Delegated
  添加: openid, profile, email, User.Read, GroupMember.Read.All
  → 点击 "Grant admin consent for [tenant]"
```

> **如果不授予 `GroupMember.Read.All` 的 admin consent**，Entra Group Sync 会返回 403。

**4. 注入到集群：**

```bash
./deploy-all.sh --configure auth
# 选择 "Add/Update Microsoft Entra ID (SSO)"
# 输入: Client ID、Client Secret、Tenant ID
# 脚本写入 AWS Secrets Manager → ESO 同步到 Pod
```

**5. 重启后端以加载密钥：**

```bash
kubectl rollout restart deploy/backend -n kbp
```

### Entra ID Group Sync（通过 Azure 组实现 RBAC）

Group Sync 将 Azure AD 安全组映射为角色和权限。启用后，访问由组成员关系控制：

```bash
# 启用 Group Sync
KBR_MICROSOFT_ENABLE_GROUP_SYNC=true
```

**首次登录（引导）：** 第一个通过 Microsoft 登录的用户自动获得 `super_admin` — 解决鸡生蛋问题。引导窗口在此之后立即关闭。

**配置流程：**
1. 在 Azure Portal 创建安全组（如 `KBP-Admins`、`KBP-Users`）
2. 在 Azure Portal 将成员添加到组
3. 首次登录 KBP → 获得 super_admin
4. 进入管理面板 > **Entra Groups** > 添加映射：

| Entra Group ID (Object ID) | 显示名称 | 角色 | 优先级 |
|-----------------------------|---------|------|--------|
| `aaaaaaaa-bbbb-...` | KBP-Admins | `super_admin` | 100 |
| `cccccccc-dddd-...` | KBP-Users | `admin` | 50 |

**行为规则：**
- 用户在已映射的组中 → 每次登录分配该组角色
- 用户不在任何映射组中 → 403 拒绝
- Graph API 不可达 → 503 拒绝（fail-closed 设计）
- 用户在多个组中 → 最高优先级生效

详细行为矩阵和故障排查参见 [OAuth Setup — Entra ID Group Sync](oauth-setup.md#entra-id-group-sync)。

---

## 后端环境变量

以下环境变量控制后端运行时行为，可在 K8s ConfigMap 或通过 ESO 管理的 secrets 中设置。

| 变量 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `KBR_STREAM_FIRST_CONTENT_TIMEOUT` | int | `600` | 流式请求开始后，等待首个内容块的超时秒数。超时后自动故障转移到下一个区域/模型。设为 `0` 禁用故障转移。 |
| `KBR_STREAM_MODEL_FALLBACK_CHAIN` | string | `""` | 逗号分隔的模型降级链，用于二级降级。示例：`anthropic.claude-opus-4-0-20250514-v1:0,anthropic.claude-sonnet-4-20250514-v1:0`。空字符串表示禁用模型降级。 |

---

## 日志格式

日志包含 `[token_name]` 字段，标识每条日志对应的 API Key，支持按 Key 过滤。

```
%(asctime)s - %(name)s - %(levelname)s - [%(token_name)s] %(message)s
```

无 token 上下文时该字段显示为 `[-]`。

输出示例：

```
2026-04-11 08:23:01,234 - app.api.v1.endpoints.chat - INFO - [my-team-key] streaming request to us-west-2
2026-04-11 08:23:05,678 - app.api.v1.endpoints.chat - WARNING - [-] health check from unknown caller
```

> **注意**：所有模块使用 `logging.getLogger(__name__)` 获取日志记录器，因此日志名称与模块路径一致（如 `app.api.v1.endpoints.chat`、`app.services.bedrock` 等）。

---

## Global Accelerator（步骤 5）

AWS Global Accelerator 通过 AWS 骨干网络转发流量，可将远距离用户的访问延迟降低 40-60%。

> **重要：** Global Accelerator 依赖步骤 4 创建的 ALB。务必先完成步骤 1-4。

### 启用 / 禁用

```bash
./deploy-all.sh --step 5
```

脚本会自动检测当前 GA 状态并提供相应操作（启用或禁用）。

### 端口映射

| 服务 | GA 端口 | ALB 端口 | 协议 |
|------|---------|----------|------|
| Frontend | 443 | 443 | HTTPS |
| Frontend | 80 | 80 | HTTP |
| API | 8443 | 443 | HTTPS |
| API | 8080 | 80 | HTTP |

### 配合 Global Accelerator 的 DNS 配置

```bash
GA_DNS=$(terraform output -raw global_accelerator_dns_name)

# kbp.kolya.fun         CNAME  $GA_DNS
# ga-api.kbp.kolya.fun  CNAME  $GA_DNS
```

### 费用参考

| 项目 | 月费用 |
|------|--------|
| 固定费用 | $18.00 |
| 数据传输（100 GB） | $1.50 |
| **合计（典型场景）** | **约 $19.50** |

---

## DNS 配置

Ingress 资源创建 ALB 后，配置 DNS 记录：

```bash
# 获取 ALB 地址
kubectl get ingress -n kbp
```

| 记录 | 类型 | 值 |
|------|------|---|
| `kbp.kolya.fun` | CNAME | Frontend ALB 主机名 |
| `api.kbp.kolya.fun` | CNAME | API ALB 主机名 |

如果启用了 Global Accelerator，两条记录都应指向 GA DNS 名称（参见[配合 Global Accelerator 的 DNS 配置](#配合-global-accelerator-的-dns-配置)）。

### 配置位置

| DNS 服务商 | 操作方式 |
|-----------|---------|
| **Route 53** | 在托管区域中创建 CNAME 记录（zone apex 可使用 Alias 记录） |
| **Cloudflare** | 在 Cloudflare 控制台添加 CNAME 记录。代理状态设为 "DNS only"（灰色云朵），避免与 ALB 双重代理 |
| **其他服务商** | 在 DNS 管理控制台中添加 CNAME 记录，指向 ALB 主机名（或 GA DNS 名称） |

> **注意：** CNAME 记录不能用于 zone apex（如不带子域名的 `example.com`）。如果你的域名是裸域名，请使用服务商提供的 ALIAS/ANAME 记录，或添加子域名前缀。

---

## 数据库迁移

```bash
# 本地执行
cd backend && uv run alembic upgrade head

# 在 EKS 集群中执行（生产镜像不含 uv，直接用 python）
kubectl exec -it deployment/backend -n kbp -- alembic upgrade head

# 创建新的迁移文件（仅本地）
cd backend && uv run alembic revision --autogenerate -m "describe your change"
```

---

## 回滚

### 应用回滚

```bash
kubectl rollout undo deployment/backend -n kbp
kubectl rollout undo deployment/frontend -n kbp
```

### Global Accelerator 回滚

```bash
./deploy-all.sh --step 5   # 检测到 GA 已启用，提供禁用选项
```

---

## 故障排查

### Ingress 没有创建 ALB

```bash
kubectl get pods -n kube-system | grep aws-load-balancer
kubectl logs -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller
kubectl describe ingress -n kbp
```

### Pod 无法启动

```bash
kubectl describe pod <pod-name> -n kbp
kubectl logs <pod-name> -n kbp
```

常见原因：镜像拉取失败（检查 ECR 权限）、配置错误（检查 ESO 同步状态）、资源不足（检查 Karpenter）。

### 数据库连接失败

```bash
kubectl get secret backend-secrets -n kbp -o yaml
kubectl run -it --rm debug --image=postgres:15 --restart=Never -- \
  psql "postgresql://postgres:PASSWORD@RDS_ENDPOINT:5432/DATABASE"  # pragma: allowlist secret
```

### HPA 不生效

```bash
kubectl top nodes
kubectl top pods -n kbp
kubectl rollout restart deployment metrics-server -n kube-system
```

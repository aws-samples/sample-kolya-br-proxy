# Kolya BR Proxy — 部署 SOP

本文档涵盖 AWS EKS 上的完整部署和销毁流程。

本地开发环境搭建请参考 [README 快速开始](../README.zh.md#快速开始)。

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

1. 验证 AWS 凭证和区域
2. **配置 `terraform.tfvars`**（步骤 0）— 自动检测账户/区域/功能开关，提示输入域名
3. 提示 S3 后端配置（存储桶名称）— 从模板生成 `iac/providers.tf`
4. 选择或创建 Terraform workspace
5. 执行 `terraform init` + `plan` + `apply`（VPC、EKS、RDS 等）
6. 部署 Helm charts（ALB Controller、Karpenter、Metrics Server）
7. 构建并推送 Docker 镜像到 ECR（域名从 `terraform.tfvars` 读取）
8. 部署 K8s 应用（从 `terraform.tfvars` 生成配置，通过 ESO 管理 secrets）
9. ALB 就绪后自动启用 WAF

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

# 跳过确认提示（CI/CD 场景）
./deploy-all.sh --yes

# K8s 管理
cd k8s && ./deploy.sh status   # 查看应用状态
cd k8s && ./deploy.sh logs     # 查看日志
cd k8s && ./deploy.sh update   # 更新应用配置
```

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
| **Backend Pod** | CPU 请求/限制 | 100m / 500m | 200m / 1000m |
| | 内存请求/限制 | 256Mi / 512Mi | 512Mi / 1024Mi |
| | HPA 最小副本数 | 1 | 2 |
| **Frontend Pod** | CPU 请求/限制 | 50m / 200m | 100m / 500m |
| | 内存请求/限制 | 128Mi / 256Mi | 256Mi / 512Mi |
| | HPA 最小副本数 | 1 | 2 |
| **EKS 核心节点** | 实例类型 | `t4g.small` | `t4g.medium` |
| | EBS 卷大小 | 30 GB | 100 GB |
| **Karpenter 节点** | 实例类别 | `t`（t4g） | `m`（m7g） |
| | EBS 卷大小 | 30 GB | 100 GB |
| | CPU 上限 | 100 | 1000 |
| | 内存上限 | 100 Gi | 1000 Gi |
| **RDS Aurora** | 删除保护 | 关闭 | 开启 |
| | 备份保留天数 | 1 天 | 7 天 |
| | 备份时间窗口 | 未设置 | 03:00-04:00 UTC |
| | 快照标签复制 | 否 | 是 |
| | 跳过最终快照 | 是 | 否 |
| | 立即应用变更 | 是 | 否 |
| | CloudWatch 日志导出 | 无 | `["postgresql"]` |
| | 监控间隔（秒） | 0（关闭） | 60 |
| | Performance Insights | 关闭 | 开启 |
| **Cognito** | 高级安全模式 | `AUDIT` | `ENFORCED` |
| | 删除保护 | 关闭 | 开启 |
| **Global Accelerator** | 流日志 | 关闭 | 开启 |

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
2026-04-11 08:23:01,234 - kolya_br_proxy.router - INFO - [my-team-key] streaming request to us-west-2
2026-04-11 08:23:05,678 - kolya_br_proxy.router - WARNING - [-] health check from unknown caller
```

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

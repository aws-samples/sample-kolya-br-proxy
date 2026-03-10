# 部署指南

本文档涵盖 Kolya BR Proxy 从本地开发到 AWS EKS 生产环境的完整部署流程。

## 前置条件

### 所需工具

| 工具 | 版本要求 | 安装方式 |
|------|---------|---------|
| Terraform | >= 1.0 | https://www.terraform.io/downloads |
| kubectl | 最新版 | https://kubernetes.io/docs/tasks/tools/ |
| Helm | 最新版 | https://helm.sh/docs/intro/install/ |
| AWS CLI | v2 | https://aws.amazon.com/cli/ |
| Docker | 最新版 | https://docs.docker.com/get-docker/ |
| jq | 最新版 | `brew install jq` |
| yq | 最新版 | `brew install yq` |
| Node.js | 20+ | https://nodejs.org/ |
| Python | 3.12+ | https://www.python.org/ |
| uv | 最新版 | https://astral.sh/uv |

### AWS 账户

- 需要拥有创建 VPC、EKS、RDS、IAM、ACM、Route 53 和 ECR 资源权限的 AWS 账户。
- AWS CLI 已配置有效凭证（通过 `aws configure` 或环境变量）。
- 已注册并通过 Route 53 管理的域名（默认：`kolya.fun`）。

---

## 本地开发环境搭建

### 1. 克隆代码仓库

```bash
git clone https://github.com/kolya-amazon/kolya-br-proxy.git
cd kolya-br-proxy
```

### 2. 后端配置

```bash
cd backend
cp .env.example .env
# 编辑 .env，填入本地数据库连接、JWT 密钥等配置
```

`.env` 中的关键环境变量：

```bash
KBR_ENV=non-prod
KBR_DEBUG=true
KBR_PORT=8000
KBR_DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/kolyabrproxy  # pragma: allowlist secret
KBR_JWT_SECRET_KEY=your-secret-key-min-32-characters-long  # pragma: allowlist secret
KBR_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:9000
KBR_AWS_REGION=us-west-2
KBR_MICROSOFT_CLIENT_ID=your-client-id
KBR_MICROSOFT_CLIENT_SECRET=your-client-secret
KBR_MICROSOFT_TENANT_ID=your-tenant-id
```

启动后端服务：

```bash
uv sync
uv run python -m backend.main
```

API 地址：`http://localhost:8000`，健康检查：`http://localhost:8000/health/`。

### 3. 前端配置

```bash
cd frontend
npm ci
npm run dev
```

前端地址：`http://localhost:9000`。

### 4. 数据库初始化

确保本地 PostgreSQL 正在运行，然后执行数据库迁移：

```bash
cd backend
uv run alembic upgrade head
```

---

## 生产部署概览

生产部署严格按照以下四个步骤执行，每个步骤可独立运行，也可通过统一脚本一键完成。

```mermaid
flowchart LR
    S1["Step 1\nTerraform\n(AWS Infra)"]
    S2["Step 2\nHelm\n(K8s Infra)"]
    S3["Step 3\nDocker\n(Build Images)"]
    S4["Step 4\nK8s Deploy\n(Application)"]
    S5["Step 5\nGlobal Accelerator\n(Optional)"]
    S1 --> S2 --> S3 --> S4 -.-> S5
```

### 统一部署脚本

`deploy-all.sh` 负责编排全部四个步骤：

```bash
# 完整交互式部署（步骤 1-4）
./deploy-all.sh

# 执行单个步骤
./deploy-all.sh --step 1   # 仅 Terraform（AWS 基础设施 + Cognito 配置）
./deploy-all.sh --step 2   # 仅 Helm（K8s 基础设施）
./deploy-all.sh --step 3   # 仅 Docker 构建
./deploy-all.sh --step 4   # 仅应用部署
./deploy-all.sh --step 5   # Global Accelerator 开关（启用/禁用，需先完成步骤 1-4）

# 跳过确认提示（谨慎使用）
./deploy-all.sh --yes
```

---

## 步骤一：Terraform -- AWS 基础设施

Terraform 负责创建所有云资源：VPC、EKS、RDS Aurora PostgreSQL、IAM 角色、安全组、ACM 证书和 Route 53 DNS。

```bash
cd iac-612674025488-us-west-2

# 选择工作空间（决定部署环境）
terraform workspace select non-prod   # 或：terraform workspace select prod

# 部署
terraform init -upgrade
terraform plan -out=tfplan
terraform apply tfplan
```

Terraform 工作空间决定使用生产还是非生产配置，详见下方差异对照表。

### 生产环境与非生产环境配置差异

| 类别 | 配置项 | 非生产环境 | 生产环境 |
|------|--------|----------|---------|
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

这些差异通过 `iac-612674025488-us-west-2/main.tf` 和 `modules/eks-karpenter/eks.tf` 中的 `workspace == "prod"` 条件表达式控制。

---

## 步骤二：Helm -- Kubernetes 基础设施

Terraform 创建 EKS 集群后，需要通过 Helm 安装集群级组件。

```bash
# 配置 kubectl
aws eks update-kubeconfig --name <cluster-name> --region us-west-2

# 从 Terraform 输出生成 Helm values
cd k8s/infrastructure/helm-installations
./generate-values.sh ../../iac-612674025488-us-west-2

# 安装 Helm charts（ALB Controller、Karpenter、Metrics Server）
./install.sh

# 应用 Karpenter 节点配置
cd ../karpenter
./apply-karpenter-config.sh
```

安装的组件：
- **AWS Load Balancer Controller**（v3.0.0）-- 根据 Ingress 资源自动创建 ALB
- **Karpenter**（v1.9.0）-- 自动配置和扩缩节点
- **Metrics Server**（v3.13.0）-- 为 HPA 提供 CPU/内存指标

---

## 步骤三：Docker 镜像构建

后端和前端镜像均以 `linux/arm64` 为目标平台，适配 Graviton 实例。

### 使用构建脚本

```bash
# 构建并推送所有镜像
./build-and-push.sh

# 仅构建单个目标
./build-and-push.sh backend
./build-and-push.sh frontend

# 自定义标签
./build-and-push.sh --tag v1.2.3
```

### 手动构建

```bash
# ECR 登录
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr get-login-password --region us-west-2 | \
  docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com

# 后端（上下文为项目根目录，Dockerfile 在 backend/ 中）
docker build -f backend/Dockerfile \
  -t $ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com/kolya-br-proxy-backend:latest .

# 前端（上下文为 frontend/）
cd frontend
docker build \
  --build-arg VITE_API_BASE_URL=https://api.kbp.kolya.fun \
  --build-arg VITE_MICROSOFT_REDIRECT_URI=https://kbp.kolya.fun/auth/microsoft/callback \
  -t $ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com/kolya-br-proxy-frontend:latest .

# 推送
docker push $ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com/kolya-br-proxy-backend:latest
docker push $ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com/kolya-br-proxy-frontend:latest
```

### 镜像详情

| 镜像 | 基础镜像 | 平台 | 健康检查 | 端口 |
|------|---------|------|---------|------|
| Backend | `python:3.12-slim` | `linux/arm64` | `curl http://localhost:8000/health/` | 8000 |
| Frontend | `nginx:alpine`（多阶段构建） | `linux/arm64` | `wget http://localhost:3000/` | 3000 |

---

## 步骤四：Kubernetes 应用部署

### 首次部署

运行 `deploy-all.sh` 时，步骤四包含一个**内联配置向导**，会自动检测配置文件是否已存在。首次运行时，向导会直接启动 -- 无需单独运行 `deploy.sh init`。

配置向导会自动从 Terraform 获取 RDS 端点、区域和 Cognito 凭证等信息，并引导你填写：
- **认证提供商选择** -- Cognito（默认）或 Microsoft Entra ID
- 前端和 API 域名
- 数据库密码
- JWT 密钥（留空可自动生成）
- OAuth 认证配置（基于所选的认证提供商）
- ACM 证书 ARN

后续运行时，如果配置文件已存在，向导将被跳过。

> **关于 Cognito 用户：** 自助注册已禁用。第一个管理员用户会在步骤一（Terraform）结束时自动创建，临时密码通过邮件发送。后续用户需由管理员通过 `aws cognito-idp admin-create-user` 创建。详见 [OAuth 配置指南](oauth-setup.zh.md)。

> **注意：** 你仍然可以随时从 `k8s/` 目录单独运行 `./deploy.sh init` 来重新配置或更新设置。

```bash
# 完整部署（首次部署时向导自动运行）
./deploy-all.sh

# 或单独运行步骤四
./deploy-all.sh --step 4

# 独立重新配置（如有需要）
cd k8s
./deploy.sh init
```

### 日常运维

```bash
./deploy.sh status    # 查看 Pod、Service、Ingress、HPA 状态
./deploy.sh logs      # 实时查看应用日志
./deploy.sh update    # 更新 Secret/ConfigMap 并重启 Pod
./deploy.sh delete    # 删除应用
```

### 创建的资源

| 资源类型 | 名称 | 命名空间 |
|---------|------|---------|
| Namespace | `kbp` | -- |
| Deployment | `backend`（1-10 副本） | `kbp` |
| Deployment | `frontend`（1-5 副本） | `kbp` |
| Service | `backend`（ClusterIP） | `kbp` |
| Service | `frontend`（ClusterIP） | `kbp` |
| Ingress | `kolya-br-proxy-frontend` | `kbp` |
| Ingress | `kolya-br-proxy-api` | `kbp` |
| HPA | `backend-hpa` | `kbp` |
| HPA | `frontend-hpa` | `kbp` |
| Secret | `backend-secrets` | `kbp` |
| ConfigMap | `backend-config` | `kbp` |
| ConfigMap | `frontend-config` | `kbp` |

---

## DNS 配置

Ingress 资源创建 ALB 后（约需 2-3 分钟），配置 DNS 记录：

```bash
# 获取 ALB 地址
kubectl get ingress -n kbp
```

在 DNS 服务商处创建 CNAME 记录：

| 记录 | 类型 | 值 |
|------|------|---|
| `kbp.kolya.fun` | CNAME | Frontend ALB 主机名 |
| `api.kbp.kolya.fun` | CNAME | API ALB 主机名 |

如果使用 Route 53：

```bash
ZONE_ID=$(aws route53 list-hosted-zones-by-name \
  --dns-name kolya.fun \
  --query 'HostedZones[0].Id' --output text | cut -d'/' -f3)

FRONTEND_ALB=$(kubectl get ingress kolya-br-proxy-frontend -n kbp \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

aws route53 change-resource-record-sets --hosted-zone-id $ZONE_ID --change-batch '{
  "Changes": [{"Action":"UPSERT","ResourceRecordSet":{
    "Name":"kbp.kolya.fun","Type":"CNAME","TTL":300,
    "ResourceRecords":[{"Value":"'$FRONTEND_ALB'"}]
  }}]
}'
```

API ALB 同理，将域名改为 `api.kbp.kolya.fun`。

---

## 步骤五：Global Accelerator（可选）

AWS Global Accelerator 通过 AWS 骨干网络转发流量，可将远距离用户的访问延迟降低 40-60%。

> **重要：** Global Accelerator 依赖步骤四创建的 ALB。不能与步骤一同时部署，因为此时 ALB 尚不存在。务必先完成步骤 1-4。

### 架构对比

```
未启用 GA：用户（亚洲）--> 公网 --> us-west-2 ALB --> EKS
启用 GA：  用户（亚洲）--> 最近的 AWS 边缘节点 --> AWS 骨干网 --> us-west-2 ALB --> EKS
```

### 启用 / 禁用 Global Accelerator

```bash
# 通过 deploy-all.sh 切换（推荐）
./deploy-all.sh --step 5
```

脚本会自动检测当前 GA 状态并提供相应操作：

**当 GA 未启用时**（启用流程）：
1. 验证两个 ALB（`kolya-br-proxy-frontend-alb` 和 `kolya-br-proxy-api-alb`）是否存在
2. 更新 `terraform.tfvars` 设置 `enable_global_accelerator = true`
3. 执行 `terraform plan` 并确认
4. 应用并显示 Global Accelerator 的 DNS 名称和静态 IP
5. 重新生成 configmap，API 端口改为 8443（`API_PORT_SUFFIX=":8443"`）
6. 应用 configmap 并重启 pods

**当 GA 已启用时**（禁用流程）：
1. 更新 `terraform.tfvars` 设置 `enable_global_accelerator = false`
2. 执行 `terraform plan` 并确认
3. 应用以销毁 Global Accelerator
4. 重新生成 configmap，恢复默认 API 端口（`API_PORT_SUFFIX=""`）
5. 应用 configmap 并重启 pods
6. 显示 ALB 主机名，用于 DNS 回切

### 端口映射

| 服务 | GA 端口 | ALB 端口 | 协议 |
|------|---------|----------|------|
| Frontend | 443 | 443 | HTTPS |
| Frontend | 80 | 80 | HTTP |
| API | 8443 | 443 | HTTPS |
| API | 8080 | 80 | HTTP |

### 配合 Global Accelerator 的 DNS 配置

将 DNS 指向 GA 的 DNS 名称：

```bash
GA_DNS=$(terraform output -raw global_accelerator_dns_name)

# kbp.kolya.fun         CNAME  $GA_DNS
# ga-api.kbp.kolya.fun  CNAME  $GA_DNS
```

建议采用渐进式迁移策略：保留现有 ALB DNS 作为主记录，先用子域名（如 `ga.kbp.kolya.fun`）接入 GA 进行测试，确认无误后再切换主域名。

### 费用参考

| 项目 | 月费用 |
|------|--------|
| 固定费用 | $18.00 |
| 数据传输（100 GB） | $1.50 |
| **合计（典型场景）** | **约 $19.50** |

---

## 数据库迁移

数据库迁移使用 Alembic，在后端项目中执行。

### 本地执行

```bash
cd backend
uv run alembic upgrade head
```

### 在 EKS 集群中执行

```bash
# 进入运行中的后端 Pod
kubectl exec -it deployment/backend -n kbp -- uv run alembic upgrade head
```

### 创建新的迁移文件

```bash
cd backend
uv run alembic revision --autogenerate -m "describe your change"
```

---

## 健康检查

### 后端

```bash
curl http://localhost:8000/health/
```

Dockerfile 中配置的健康检查每 30 秒执行一次，超时 10 秒，最多重试 3 次：

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/ || exit 1
```

### 前端

```bash
wget --quiet --tries=1 --spider http://localhost:3000/
```

### Kubernetes 层面检查

```bash
# Pod 状态
kubectl get pods -n kbp

# HPA 指标
kubectl top pods -n kbp

# Ingress / ALB 状态
kubectl get ingress -n kbp
kubectl describe ingress -n kbp
```

---

## 故障排查

### Ingress 没有创建 ALB

```bash
# 检查 ALB Controller 是否正常运行
kubectl get pods -n kube-system | grep aws-load-balancer
kubectl logs -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller

# 检查 Ingress 事件
kubectl describe ingress -n kbp
```

### Pod 无法启动

```bash
kubectl get pods -n kbp
kubectl describe pod <pod-name> -n kbp
kubectl logs <pod-name> -n kbp
```

常见原因：
- 镜像拉取失败（检查 ECR 权限和镜像是否存在）
- 配置错误（检查 `secrets.yaml` 中的值）
- 资源不足（检查 Karpenter 节点供应状态）

### 数据库连接失败

```bash
# 检查 Secret 内容
kubectl get secret backend-secrets -n kbp -o yaml

# 从集群内部测试连接
kubectl run -it --rm debug --image=postgres:15 --restart=Never -- \
  psql "postgresql://postgres:PASSWORD@RDS_ENDPOINT:5432/DATABASE"  # pragma: allowlist secret
```

### HPA 不生效

```bash
kubectl top nodes
kubectl top pods -n kbp

# 如果指标不可用，重启 Metrics Server
kubectl rollout restart deployment metrics-server -n kube-system
```

### Cognito 登录问题

**Authorize 请求被取消（浏览器显示 "canceled"）**

后端 ConfigMap 中的 `KBR_COGNITO_DOMAIN` 与实际 Cognito 域名不匹配。验证真实域名：

```bash
aws cognito-idp describe-user-pool \
  --user-pool-id <pool-id> \
  --region us-west-2 \
  --query 'UserPool.Domain' --output text
```

更新 `k8s/application/backend-configmap.yaml` 中的 `KBR_COGNITO_DOMAIN` 使其匹配，然后重新应用并重启：

```bash
kubectl apply -f k8s/application/backend-configmap.yaml
kubectl rollout restart deployment/backend -n kbp
```

**Cognito 重定向报 "redirect_mismatch" 错误**

生产环境的回调 URL 未在 Cognito app client 中注册。添加方法：

```bash
aws cognito-idp update-user-pool-client \
  --user-pool-id <pool-id> \
  --client-id <client-id> \
  --callback-urls "https://<前端域名>/auth/cognito/callback" "http://localhost:9000/auth/cognito/callback" \
  --logout-urls "https://<前端域名>/" "http://localhost:9000/" \
  --allowed-o-auth-flows code \
  --allowed-o-auth-scopes email openid profile \
  --allowed-o-auth-flows-user-pool-client \
  --supported-identity-providers COGNITO \
  --region us-west-2
```

**部署后没有用户能登录**

Cognito 用户池在初次创建后是空的。创建第一个管理员用户（注意：用户池使用邮箱别名，`--username` 不能是邮箱格式）：

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <pool-id> \
  --username admin \
  --user-attributes Name=email,Value=admin@example.com Name=email_verified,Value=true \
  --desired-delivery-mediums EMAIL \
  --region us-west-2
```

> 如果通过 `deploy-all.sh` 部署，步骤一会自动处理此步骤。

### Global Accelerator -- 找不到匹配的 ALB

```bash
# 确认 ALB 名称与 Terraform 变量一致
kubectl get ingress -n kbp -o jsonpath='{.items[*].metadata.annotations.alb\.ingress\.kubernetes\.io/load-balancer-name}'
aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName'
```

---

## 回滚

### 应用回滚

```bash
# 回退 Deployment 到上一个版本
kubectl rollout undo deployment/backend -n kbp
kubectl rollout undo deployment/frontend -n kbp

# 确认回滚状态
kubectl rollout status deployment/backend -n kbp
kubectl rollout status deployment/frontend -n kbp
```

### 配置回滚

```bash
# 恢复之前的 Secret 或 ConfigMap 文件，然后重新应用
kubectl apply -f application/secrets.yaml
kubectl rollout restart deployment/backend -n kbp
kubectl rollout restart deployment/frontend -n kbp
```

### 基础设施回滚

```bash
cd iac-612674025488-us-west-2

# 回退到之前的 Terraform 状态（如已保存）
terraform plan    # 审查变更
terraform apply
```

### Global Accelerator 回滚

推荐使用切换命令，自动处理所有回滚步骤：

```bash
./deploy-all.sh --step 5   # 检测到 GA 已启用，提供禁用选项
```

脚本会自动销毁 GA 资源、重新生成 configmap（移除端口 8443）、重启 pods，并显示 ALB 主机名用于 DNS 回切。

如需手动回滚：
1. **DNS 回退** -- 将 DNS 记录重新指向 ALB 主机名。
2. **禁用模块** -- 在 `terraform.tfvars` 中设置 `enable_global_accelerator = false`，然后运行 `terraform apply`。
3. **重新生成 configmap** -- 设置 `API_PORT_SUFFIX=""`，从模板重新生成，然后 `kubectl apply` 并重启 pods。

### 完整销毁

```bash
# 删除应用
cd k8s && ./deploy.sh delete

# 销毁基础设施（警告：将删除所有数据）
cd iac-612674025488-us-west-2
terraform destroy
```

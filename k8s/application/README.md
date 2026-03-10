# 应用部署配置

本目录包含 Kolya BR Proxy 应用的 Kubernetes 部署配置。

## ⚡ 推荐方式：使用统一脚本

```bash
# 返回上级目录
cd ..

# 使用统一部署脚本
./deploy.sh init    # 首次初始化
./deploy.sh deploy  # 部署应用
```

**本文档描述手动部署步骤，仅在特殊情况下使用。**

---

## 📁 文件清单

### 模板文件（可提交到 Git ✅）

| 文件 | 说明 |
|------|------|
| `secrets.yaml.template` | Secrets 配置模板 |
| `backend-configmap.yaml.template` | Backend ConfigMap 模板 |
| `frontend-configmap.yaml.template` | Frontend ConfigMap 模板 |
| `backend-deployment.yaml.template` | Backend Deployment 模板（资源按环境变化） |
| `frontend-deployment.yaml.template` | Frontend Deployment 模板（资源按环境变化） |
| `hpa-backend.yaml.template` | Backend HPA 模板（副本数按环境变化） |
| `hpa-frontend.yaml.template` | Frontend HPA 模板（副本数按环境变化） |
| `ingress-frontend.yaml.template` | Frontend Ingress 模板 |
| `ingress-api.yaml.template` | API Ingress 模板 |
| `generate-ingress.sh` | Ingress 生成脚本 |

### 静态配置文件（可提交到 Git ✅）

| 文件 | 说明 |
|------|------|
| `namespace.yaml` | 命名空间定义 (kbp) |
| `backend-service.yaml` | Backend Service (ClusterIP) |
| `frontend-service.yaml` | Frontend Service (ClusterIP) |

### 生成的文件（不提交到 Git ❌）

| 文件 | 说明 |
|------|------|
| `secrets.yaml` | 实际的 Secrets（从模板生成） |
| `backend-configmap.yaml` | Backend ConfigMap（从模板生成） |
| `frontend-configmap.yaml` | Frontend ConfigMap（从模板生成） |
| `backend-deployment.yaml` | Backend Deployment（从模板生成，资源按环境） |
| `frontend-deployment.yaml` | Frontend Deployment（从模板生成，资源按环境） |
| `hpa-backend.yaml` | Backend HPA（从模板生成，副本数按环境） |
| `hpa-frontend.yaml` | Frontend HPA（从模板生成，副本数按环境） |
| `ingress-frontend.yaml` | Frontend Ingress（从模板生成） |
| `ingress-api.yaml` | API Ingress（从模板生成） |

---

## 📋 部署前准备

### 1. 检查前置条件

```bash
# 确认 kubectl 已连接到正确的集群
kubectl cluster-info

# 确认基础设施组件已安装
kubectl get pods -n kube-system | grep -E "(aws-load-balancer|karpenter|metrics-server)"

# 确认 Terraform 已部署 AWS 资源
cd ../../iac-612674025488-us-west-2
terraform output
```

### 2. 准备配置信息

需要收集以下信息：

#### 从 Terraform 获取

```bash
cd ../../iac-612674025488-us-west-2

# RDS 信息
terraform output rds_cluster_endpoint
terraform output rds_cluster_port
terraform output rds_cluster_database_name

# AWS 信息
terraform output region
aws sts get-caller-identity --query Account --output text
```

#### 需要手动提供

- 数据库密码（创建 RDS 时设置的）
- JWT Secret Key（生成：`openssl rand -base64 32`）
- Microsoft OAuth 配置：
  - Client ID
  - Client Secret
  - Tenant ID
- ACM Certificate ARNs：
  - Frontend 证书
  - API 证书

查询 ACM 证书：
```bash
aws acm list-certificates --region us-west-2
```

---

## 🚀 手动部署步骤

### 步骤 1: 创建 secrets.yaml

```bash
# 从模板复制
cp secrets.yaml.template secrets.yaml

# 编辑文件，填入实际值
vim secrets.yaml
```

需要替换的占位符：
- `YOUR_DB_PASSWORD` - RDS 数据库密码
- `YOUR_RDS_ENDPOINT` - RDS 集群端点
- `YOUR_DATABASE_NAME` - 数据库名称
- `YOUR_JWT_SECRET_KEY_MINIMUM_32_CHARACTERS_LONG` - JWT 密钥
- `YOUR_MICROSOFT_CLIENT_ID` - Microsoft OAuth Client ID
- `YOUR_MICROSOFT_CLIENT_SECRET` - Microsoft OAuth Client Secret
- `YOUR_MICROSOFT_TENANT_ID` - Microsoft OAuth Tenant ID
- `arn:aws:acm:REGION:ACCOUNT_ID:certificate/CERTIFICATE_ID` - ACM 证书 ARN（两处）
- `YOUR_AWS_ACCOUNT_ID` - AWS 账户 ID

### 步骤 2: 生成 Ingress 文件

```bash
# 使用脚本生成
./generate-ingress.sh
```

这将从 `secrets.yaml` 读取配置并生成：
- `ingress-frontend.yaml`
- `ingress-api.yaml`

### 步骤 3: 检查配置文件

```bash
# 验证 YAML 语法
kubectl apply --dry-run=client -f namespace.yaml
kubectl apply --dry-run=client -f secrets.yaml
kubectl apply --dry-run=client -f backend-deployment.yaml
kubectl apply --dry-run=client -f frontend-deployment.yaml
kubectl apply --dry-run=client -f ingress-frontend.yaml
kubectl apply --dry-run=client -f ingress-api.yaml
```

### 步骤 4: 部署到 Kubernetes

```bash
# 1. 创建命名空间
kubectl apply -f namespace.yaml

# 2. 部署 Secrets
kubectl apply -f secrets.yaml

# 3. 部署 ConfigMaps
kubectl apply -f backend-configmap.yaml
kubectl apply -f frontend-configmap.yaml

# 4. 部署应用
kubectl apply -f backend-deployment.yaml
kubectl apply -f frontend-deployment.yaml

# 5. 创建 Services
kubectl apply -f backend-service.yaml
kubectl apply -f frontend-service.yaml

# 6. 创建 Ingress（会触发 ALB 创建）
kubectl apply -f ingress-frontend.yaml
kubectl apply -f ingress-api.yaml

# 7. 配置自动扩缩容
kubectl apply -f hpa-backend.yaml
kubectl apply -f hpa-frontend.yaml
```

### 步骤 5: 验证部署

```bash
# 检查 Pods
kubectl get pods -n kbp

# 检查 Services
kubectl get svc -n kbp

# 检查 Ingress
kubectl get ingress -n kbp

# 查看详细信息
kubectl describe ingress kolya-br-proxy-frontend -n kbp
kubectl describe ingress kolya-br-proxy-api -n kbp
```

等待几分钟，ALB 会被创建。

### 步骤 6: 获取 ALB 地址

```bash
# Frontend ALB
kubectl get ingress kolya-br-proxy-frontend -n kbp \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'

# API ALB
kubectl get ingress kolya-br-proxy-api -n kbp \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

### 步骤 7: 配置 DNS

将域名指向 ALB：
- `kbp.kolya.fun` → Frontend ALB CNAME
- `api.kbp.kolya.fun` → API ALB CNAME

---

## 🔄 更新配置

### 更新 Secrets

```bash
# 1. 修改 secrets.yaml
vim secrets.yaml

# 2. 应用更新
kubectl apply -f secrets.yaml

# 3. 重启 Pods 以加载新配置
kubectl rollout restart deployment/backend -n kbp
kubectl rollout restart deployment/frontend -n kbp

# 4. 等待更新完成
kubectl rollout status deployment/backend -n kbp
kubectl rollout status deployment/frontend -n kbp
```

### 更新 ConfigMaps

```bash
# 1. 修改配置文件
vim backend-configmap.yaml
vim frontend-configmap.yaml

# 2. 应用更新
kubectl apply -f backend-configmap.yaml
kubectl apply -f frontend-configmap.yaml

# 3. 重启 Pods
kubectl rollout restart deployment/backend -n kbp
kubectl rollout restart deployment/frontend -n kbp
```

### 更新 Ingress（更换证书）

```bash
# 1. 修改 secrets.yaml 中的证书 ARN
vim secrets.yaml

# 2. 重新生成 Ingress 文件
./generate-ingress.sh

# 3. 应用更新
kubectl apply -f ingress-frontend.yaml
kubectl apply -f ingress-api.yaml

# ALB 会自动更新证书
```

### 更新应用镜像

```bash
# 方法 1: 修改 deployment.yaml 并应用
vim backend-deployment.yaml  # 更新 image 标签
kubectl apply -f backend-deployment.yaml

# 方法 2: 直接设置新镜像
kubectl set image deployment/backend \
  backend=<account-id>.dkr.ecr.us-west-2.amazonaws.com/kolya-br-proxy-backend:v1.2.3 \
  -n kbp

# 查看滚动更新状态
kubectl rollout status deployment/backend -n kbp

# 如果需要回滚
kubectl rollout undo deployment/backend -n kbp
```

---

## 📊 监控和诊断

### 查看 Pod 状态

```bash
# 列出所有 Pods
kubectl get pods -n kbp

# 查看 Pod 详情
kubectl describe pod <pod-name> -n kbp

# 查看 Pod 事件
kubectl get events -n kbp --sort-by='.lastTimestamp'
```

### 查看日志

```bash
# 查看最近的日志
kubectl logs deployment/backend -n kbp --tail=100

# 实时查看日志
kubectl logs -f deployment/backend -n kbp

# 查看所有 backend pods 的日志
kubectl logs -l app=backend -n kbp --tail=100

# 查看前一个容器的日志（崩溃重启场景）
kubectl logs <pod-name> -n kbp --previous
```

### 检查 HPA 状态

```bash
# 查看 HPA
kubectl get hpa -n kbp

# 查看详细信息
kubectl describe hpa backend-hpa -n kbp

# 查看 CPU/内存使用
kubectl top pods -n kbp
```

### 检查 Ingress 和 ALB

```bash
# 查看 Ingress
kubectl get ingress -n kbp

# 查看 Ingress 详情
kubectl describe ingress kolya-br-proxy-frontend -n kbp

# 检查 ALB Controller 日志
kubectl logs -n kube-system deployment/aws-load-balancer-controller
```

### 端口转发（本地调试）

```bash
# 转发 Backend
kubectl port-forward svc/backend 8000:8000 -n kbp

# 转发 Frontend
kubectl port-forward svc/frontend 3000:3000 -n kbp

# 访问 http://localhost:8000 或 http://localhost:3000
```

---

## 🛠️  故障排查

### Pod 无法启动

**症状**: Pod 状态为 `Pending`, `ImagePullBackOff`, `CrashLoopBackOff`

**诊断**:
```bash
kubectl describe pod <pod-name> -n kbp
kubectl logs <pod-name> -n kbp
```

**常见原因和解决方案**:

1. **ImagePullBackOff** - 镜像拉取失败
   ```bash
   # 检查 ECR 权限
   # 确认 IAM role 有 ECR pull 权限
   # 确认镜像存在
   aws ecr describe-images --repository-name kolya-br-proxy-backend
   ```

2. **CrashLoopBackOff** - 容器启动后崩溃
   ```bash
   # 查看日志
   kubectl logs <pod-name> -n kbp --previous

   # 常见原因：
   # - 数据库连接失败（检查 secrets.yaml）
   # - 配置错误（检查 configmap）
   # - 依赖服务不可用
   ```

3. **Pending** - 无法调度
   ```bash
   # 检查节点资源
   kubectl top nodes

   # 检查 Karpenter
   kubectl get nodepool
   kubectl logs -n kube-system deployment/karpenter
   ```

### 无法连接数据库

**症状**: Backend 日志显示数据库连接错误

**诊断**:
```bash
# 1. 检查 Secret
kubectl get secret backend-secrets -n kbp -o yaml | grep database-url

# 2. 解码查看（注意：包含密码，小心）
kubectl get secret backend-secrets -n kbp -o jsonpath='{.data.database-url}' | base64 -d

# 3. 测试连接（从 Pod 内部）
kubectl run -it --rm debug --image=postgres:15 --restart=Never -n kbp -- \
  psql "<your-database-url>"
```

**常见原因**:
- RDS Security Group 未允许 EKS 节点访问
- 数据库 URL 配置错误
- 数据库密码错误

### Ingress 未创建 ALB

**症状**: `kubectl get ingress` 显示 ADDRESS 为空

**诊断**:
```bash
# 检查 Ingress events
kubectl describe ingress kolya-br-proxy-frontend -n kbp

# 检查 ALB Controller 日志
kubectl logs -n kube-system deployment/aws-load-balancer-controller
```

**常见原因**:
- ALB Controller 未安装或未就绪
- Subnet 标签缺失（`kubernetes.io/role/elb=1`）
- IAM 权限不足
- Certificate ARN 无效

### HPA 不工作

**症状**: HPA 无法获取指标，TARGETS 显示 `<unknown>`

**诊断**:
```bash
# 检查 Metrics Server
kubectl get pods -n kube-system | grep metrics-server

# 测试指标
kubectl top nodes
kubectl top pods -n kbp

# 检查 HPA
kubectl describe hpa backend-hpa -n kbp
```

**解决方案**:
```bash
# 重启 Metrics Server
kubectl rollout restart deployment/metrics-server -n kube-system

# 等待一分钟后再次检查
kubectl top pods -n kbp
```

---

## 🗑️  删除部署

### 删除应用（保留命名空间）

```bash
kubectl delete -f hpa-frontend.yaml
kubectl delete -f hpa-backend.yaml
kubectl delete -f ingress-api.yaml
kubectl delete -f ingress-frontend.yaml
kubectl delete -f frontend-service.yaml
kubectl delete -f backend-service.yaml
kubectl delete -f frontend-deployment.yaml
kubectl delete -f backend-deployment.yaml
kubectl delete -f frontend-configmap.yaml
kubectl delete -f backend-configmap.yaml
kubectl delete -f secrets.yaml
```

### 删除所有资源（包括命名空间）

```bash
kubectl delete namespace kbp
```

**警告**: 这将删除命名空间下的所有资源，包括 ALB。

---

## 📝 配置参考

### Backend 配置项

ConfigMap 配置（`backend-configmap.yaml`）:

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `KBR_ENV` | 运行环境 | `development` |
| `KBR_DEBUG` | 调试模式 | `false` |
| `KBR_PORT` | 服务端口 | `8000` |
| `KBR_AWS_REGION` | AWS 区域 | `us-west-2` |
| `KBR_ALLOWED_ORIGINS` | CORS 允许的源 | 域名列表 |
| `KBR_JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | JWT 过期时间 | `30` |
| `KBR_LOG_LEVEL` | 日志级别 | `INFO` |

Secret 配置（`secrets.yaml`）:
- `database-url` - 完整的数据库连接字符串
- `jwt-secret-key` - JWT 签名密钥
- `microsoft-client-id` - OAuth Client ID
- `microsoft-client-secret` - OAuth Client Secret
- `microsoft-tenant-id` - OAuth Tenant ID

### Frontend 配置项

ConfigMap 配置（`frontend-configmap.yaml`）:

| 环境变量 | 说明 |
|---------|------|
| `VITE_API_BASE_URL` | API 基础 URL |
| `VITE_MICROSOFT_REDIRECT_URI` | OAuth 回调 URL |
| `NODE_ENV` | Node 环境 |

### 资源配置

资源配额和 HPA 副本数根据环境自动设置（由 `deploy-all.sh` / `deploy.sh init` 从模板生成）：

| 配置项 | Non-Prod | Prod |
|--------|----------|------|
| **Backend** CPU request / limit | 100m / 500m | 200m / 1000m |
| **Backend** Memory request / limit | 256Mi / 512Mi | 512Mi / 1024Mi |
| **Backend** HPA min / max 副本 | 1 / 10 | 2 / 10 |
| **Backend** HPA CPU / Memory 阈值 | 70% / 80% | 70% / 80% |
| **Frontend** CPU request / limit | 50m / 200m | 100m / 500m |
| **Frontend** Memory request / limit | 128Mi / 256Mi | 256Mi / 512Mi |
| **Frontend** HPA min / max 副本 | 1 / 5 | 2 / 5 |
| **Frontend** HPA CPU / Memory 阈值 | 75% / 85% | 75% / 85% |

---

## 🔗 相关文档

- [统一部署脚本使用](../README.md#快速开始使用统一脚本)
- [基础设施部署](../infrastructure/README.md)
- [Terraform 配置](../../iac-612674025488-us-west-2/README.md)

---

**维护者**: Application Team
**最后更新**: 2026-02-18

**推荐**: 使用统一部署脚本 `../deploy.sh` 代替手动部署！

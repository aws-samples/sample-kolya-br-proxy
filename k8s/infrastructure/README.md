# Kubernetes 基础设施配置

本目录包含 EKS 集群的基础设施组件配置，由 **Infrastructure 团队**维护。

## 📁 目录结构

```
infrastructure/
├── README.md                    # 本文件
├── helm-installations/          # Helm Chart 安装
│   ├── install.sh                  # 一键安装脚本
│   ├── generate-values.sh          # 从 Terraform 生成 values
│   ├── aws-load-balancer-controller-values.yaml
│   ├── karpenter-values.yaml
│   ├── metrics-server-values.yaml
│   └── README.md                   # 详细安装文档
└── karpenter/                   # Karpenter 配置
    ├── apply-karpenter-config.sh   # 应用配置脚本
    ├── common-ec2nodeclass.yaml    # EC2 节点类配置
    ├── common-nodepool.yaml        # 节点池配置
    └── README.md                   # Karpenter 文档
```

## 🎯 组件概览

### 1. AWS Load Balancer Controller

**功能**: 管理 AWS ALB/NLB 的创建和配置
**版本**: v3.0.0
**部署方式**: Helm Chart

- 自动为 Ingress 资源创建 ALB
- 支持 SSL/TLS 终止
- 集成 AWS WAF
- 支持目标组绑定模式

### 2. Karpenter

**功能**: 节点自动扩缩容
**版本**: v1.9.0
**部署方式**: Helm Chart + CRD

- 根据 Pod 需求自动添加/删除节点
- 比 Cluster Autoscaler 更快、更高效
- 支持多实例类型
- 成本优化

### 3. Metrics Server

**功能**: 提供集群资源使用指标
**版本**: v3.13.0
**部署方式**: Helm Chart

- HPA (Horizontal Pod Autoscaler) 所需
- 提供 `kubectl top` 命令支持
- CPU 和内存使用监控

## 🚀 快速部署

### 前置条件

1. ✅ Terraform 已完成基础设施部署
2. ✅ kubectl 已配置并连接到 EKS 集群
3. ✅ Helm 3.x 已安装

```bash
# 检查连接
kubectl cluster-info
helm version
```

### 一键安装所有组件

```bash
cd helm-installations
./install.sh
```

这将依次安装：
1. AWS Load Balancer Controller (约 2 分钟)
2. Karpenter (约 2 分钟)
3. Metrics Server (约 1 分钟)
4. Karpenter EC2NodeClass 和 NodePool 配置

### 手动安装（分步骤）

#### 步骤 1: 生成 Helm Values

```bash
cd helm-installations
./generate-values.sh
```

从 Terraform 输出生成:
- `aws-load-balancer-controller-values.yaml`
- `karpenter-values.yaml`
- `metrics-server-values.yaml`

#### 步骤 2: 安装 ALB Controller

```bash
helm repo add eks https://aws.github.io/eks-charts
helm repo update

helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  -f aws-load-balancer-controller-values.yaml \
  --version 3.0.0
```

验证:
```bash
kubectl get pods -n kube-system | grep aws-load-balancer-controller
kubectl get deployment -n kube-system aws-load-balancer-controller
```

#### 步骤 3: 安装 Karpenter

```bash
# 认证到 ECR Public（Karpenter 镜像）
aws ecr-public get-login-password --region us-east-1 | \
  helm registry login --username AWS --password-stdin public.ecr.aws

helm install karpenter oci://public.ecr.aws/karpenter/karpenter \
  --namespace kube-system \
  -f karpenter-values.yaml \
  --version 1.9.0
```

验证:
```bash
kubectl get pods -n kube-system | grep karpenter
```

#### 步骤 4: 安装 Metrics Server

```bash
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/
helm repo update

helm install metrics-server metrics-server/metrics-server \
  -n kube-system \
  -f metrics-server-values.yaml \
  --version 3.13.0
```

验证:
```bash
kubectl get pods -n kube-system | grep metrics-server
kubectl top nodes  # 应该显示节点资源使用
```

#### 步骤 5: 应用 Karpenter 配置

```bash
cd ../karpenter
./apply-karpenter-config.sh
```

验证:
```bash
kubectl get ec2nodeclass
kubectl get nodepool
```

## 📊 组件状态检查

### 检查所有组件

```bash
# Pod 状态
kubectl get pods -n kube-system | grep -E "(aws-load-balancer|karpenter|metrics-server)"

# Deployment 状态
kubectl get deployments -n kube-system | grep -E "(aws-load-balancer|karpenter|metrics-server)"

# Helm Release 状态
helm list -n kube-system
```

### 检查 ALB Controller

```bash
# Pod 日志
kubectl logs -n kube-system deployment/aws-load-balancer-controller

# Webhook 配置
kubectl get validatingwebhookconfiguration | grep aws-load-balancer
kubectl get mutatingwebhookconfiguration | grep aws-load-balancer
```

### 检查 Karpenter

```bash
# Karpenter 日志
kubectl logs -n kube-system deployment/karpenter

# NodePool 状态
kubectl describe nodepool common

# 查看 Karpenter 管理的节点
kubectl get nodes -l karpenter.sh/nodepool=common
```

### 检查 Metrics Server

```bash
# Metrics Server 日志
kubectl logs -n kube-system deployment/metrics-server

# 测试指标
kubectl top nodes
kubectl top pods -A
```

## 🔧 配置说明

### ALB Controller 配置

关键配置项（`aws-load-balancer-controller-values.yaml`）:

```yaml
clusterName: <your-cluster-name>  # 从 Terraform 获取
region: us-west-2
vpcId: <your-vpc-id>

serviceAccount:
  create: false  # 使用 EKS Pod Identity
  name: aws-load-balancer-controller
```

### Karpenter 配置

关键配置项（`karpenter-values.yaml`）:

```yaml
settings:
  clusterName: <your-cluster-name>
  clusterEndpoint: <eks-endpoint>
  interruptionQueue: <sqs-queue-name>

serviceAccount:
  name: karpenter
```

EC2NodeClass 配置（`common-ec2nodeclass.yaml`）:
- AMI Family: AL2
- 实例类型: t3.medium, t3.large, t3.xlarge
- Spot 实例优先
- 自动终止策略

NodePool 配置（`common-nodepool.yaml`）:
- CPU 限制: 100 cores
- 内存限制: 200 Gi
- 自动过期: 168h (7天)
- Consolidation: 启用

## 🛠️  故障排查

### ALB Controller 问题

**问题**: Ingress 创建后没有 ALB

```bash
# 检查 controller 日志
kubectl logs -n kube-system deployment/aws-load-balancer-controller

# 检查 Ingress events
kubectl describe ingress <ingress-name> -n <namespace>

# 常见原因:
# 1. IAM 权限不足
# 2. Subnets 标签缺失 (kubernetes.io/role/elb=1)
# 3. Security Group 配置问题
```

**问题**: Webhook 证书错误

```bash
# 删除并重新创建 webhook
kubectl delete validatingwebhookconfiguration aws-load-balancer-webhook
kubectl delete mutatingwebhookconfiguration aws-load-balancer-webhook

# 重启 controller
kubectl rollout restart deployment aws-load-balancer-controller -n kube-system
```

### Karpenter 问题

**问题**: 节点不自动创建

```bash
# 检查 Karpenter 日志
kubectl logs -n kube-system deployment/karpenter

# 检查 NodePool 状态
kubectl describe nodepool common

# 常见原因:
# 1. IAM 权限不足
# 2. EC2 配额限制
# 3. Subnet 容量不足
# 4. NodePool 限制达到上限
```

**问题**: 节点持续重启

```bash
# 检查节点日志
kubectl describe node <node-name>

# 检查 EC2NodeClass
kubectl describe ec2nodeclass common

# 常见原因:
# 1. User data 脚本错误
# 2. AMI 不兼容
# 3. Security Group 规则问题
```

### Metrics Server 问题

**问题**: `kubectl top` 不工作

```bash
# 检查 Metrics Server 状态
kubectl get apiservice v1beta1.metrics.k8s.io -o yaml

# 检查日志
kubectl logs -n kube-system deployment/metrics-server

# 常见原因:
# 1. Metrics Server 未就绪
# 2. Kubelet 证书问题
# 3. 网络连接问题
```

## 🔄 更新组件

### 更新 ALB Controller

```bash
# 更新到新版本
helm upgrade aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  -f aws-load-balancer-controller-values.yaml \
  --version <new-version>
```

### 更新 Karpenter

```bash
helm upgrade karpenter oci://public.ecr.aws/karpenter/karpenter \
  --namespace kube-system \
  -f karpenter-values.yaml \
  --version <new-version>
```

### 更新 Karpenter 配置

```bash
# 修改配置文件后重新应用
kubectl apply -f common-ec2nodeclass.yaml
kubectl apply -f common-nodepool.yaml
```

## 🗑️  卸载组件

### 卸载顺序

**重要**: 按以下顺序卸载，避免资源泄漏

```bash
# 1. 删除 Karpenter 配置
kubectl delete nodepool common
kubectl delete ec2nodeclass common

# 2. 卸载 Karpenter
helm uninstall karpenter -n kube-system

# 3. 卸载 Metrics Server
helm uninstall metrics-server -n kube-system

# 4. 卸载 ALB Controller (最后卸载，因为可能有活跃的 ALB)
helm uninstall aws-load-balancer-controller -n kube-system
```

### 清理资源

```bash
# 手动删除遗留的 ALB
# 在 AWS Console 或使用 AWS CLI

# 清理 Karpenter 创建的节点
kubectl delete nodes -l karpenter.sh/nodepool=common
```

## 📝 维护建议

### 定期检查

- [ ] 每周检查组件版本更新
- [ ] 每月审查 Karpenter 节点使用情况
- [ ] 每月审查 ALB 配置和成本
- [ ] 定期备份配置文件

### 监控建议

建议监控以下指标：

**ALB Controller:**
- Webhook 响应时间
- Ingress 创建/更新失败率
- ALB 创建耗时

**Karpenter:**
- 节点创建/删除速率
- Pending Pod 数量
- 节点利用率
- Spot 中断率

**Metrics Server:**
- API 响应时间
- 数据采集延迟

## 🔗 相关文档

- [AWS Load Balancer Controller 官方文档](https://kubernetes-sigs.github.io/aws-load-balancer-controller/)
- [Karpenter 官方文档](https://karpenter.sh/)
- [Metrics Server 官方文档](https://github.com/kubernetes-sigs/metrics-server)
- [应用部署文档](../application/README.md)
- [主 README](../README.md)

---

**维护者**: Infrastructure Team
**最后更新**: 2026-02-18

# Helm Installations for EKS Add-ons

This directory contains Helm charts and configuration for EKS cluster add-ons that are **decoupled from Terraform**. These components should be installed separately after the infrastructure is provisioned.

## Overview

The following components are managed here:

1. **AWS Load Balancer Controller v3.0.0** - Manages ALB/NLB for Kubernetes services
2. **Karpenter v1.9.0** - Auto-scaling and node provisioning
3. **Metrics Server v3.13.0** - Resource metrics for HPA and kubectl top

## ⚠️ Important: AWS Load Balancer Controller v3.0.0

**Before installation**, AWS LBC v3.0.0 requires manual CRD updates. See [PRE-INSTALL-v3.md](./PRE-INSTALL-v3.md) for required steps.

## Why Decoupled?

Previously, these Helm releases were managed by Terraform, which caused:
- Slow Terraform apply/destroy operations
- Coupling of infrastructure and application layer
- Difficulty in updating Helm charts independently
- Terraform state issues with Kubernetes resources

By decoupling, we achieve:
- Faster infrastructure changes
- Independent lifecycle management
- Better separation of concerns
- Standard Kubernetes deployment patterns

## Prerequisites

Before installing these charts:

1. **Infrastructure must be provisioned:**
   ```bash
   cd ../../iac-612674025488-us-west-2
   terraform apply
   ```

2. **IAM roles and Pod Identity Associations are created by Terraform:**
   - AWS Load Balancer Controller IAM role
   - Karpenter service account IAM role
   - Backend Bedrock IAM role

3. **Configure kubectl:**
   ```bash
   aws eks update-kubeconfig --name <cluster-name> --region <region>
   ```

4. **Install Helm:**
   ```bash
   # macOS
   brew install helm

   # Linux
   curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
   ```

## Installation

### Quick Start (Automated)

1. **⚠️ PRE-REQUISITE: Update CRDs for AWS Load Balancer Controller v3.0.0**

   **REQUIRED STEP - Do this first:**
   ```bash
   # Apply CRDs manually (Helm doesn't handle this in v3.0.0)
   kubectl apply -k "github.com/aws/eks-charts/stable/aws-load-balancer-controller/crds?ref=v3.0.0"
   ```

   See [PRE-INSTALL-v3.md](./PRE-INSTALL-v3.md) for details and troubleshooting.

2. **Generate values files from Terraform outputs:**
   ```bash
   ./generate-values.sh
   ```

   This will read Terraform outputs and create:
   - `aws-load-balancer-controller-values.yaml`
   - `karpenter-values.yaml`
   - `metrics-server-values.yaml` (static)

3. **Install all Helm charts:**
   ```bash
   ./install.sh
   ```

4. **Apply Karpenter node configurations:**
   ```bash
   cd ../karpenter
   ./apply-karpenter-config.sh
   ```

### Manual Installation

If you prefer manual installation or need custom configuration:

#### 1. AWS Load Balancer Controller

```bash
# Update values file with your cluster info
vi aws-load-balancer-controller-values.yaml

# Install
helm repo add eks https://aws.github.io/eks-charts
helm repo update
helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
    --namespace kube-system \
    -f aws-load-balancer-controller-values.yaml
```

#### 2. Karpenter

```bash
# Update values file
vi karpenter-values.yaml

# Install
helm install karpenter oci://public.ecr.aws/karpenter/karpenter \
    --namespace kube-system \
    -f karpenter-values.yaml
```

#### 3. Metrics Server

```bash
# Install (values are static)
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/
helm repo update
helm install metrics-server metrics-server/metrics-server \
    --namespace kube-system \
    -f metrics-server-values.yaml
```

#### 4. Karpenter Node Configurations

```bash
cd ../karpenter

# Get values from Terraform
CLUSTER_NAME=$(cd ../../iac-612674025488-us-west-2 && terraform output -raw cluster_name)
NODE_ROLE=$(cd ../../iac-612674025488-us-west-2 && terraform output -raw karpenter_node_iam_role_name)

# Apply EC2NodeClass
sed -e "s/\${subnetSelectorTermsValue}/${CLUSTER_NAME}/g" \
    -e "s/\${node_iam_role_name}/${NODE_ROLE}/g" \
    common-ec2nodeclass.yaml | kubectl apply -f -

# Apply NodePool
kubectl apply -f common-nodepool.yaml
```

## Verification

After installation, verify all components are running:

```bash
# Check AWS Load Balancer Controller
kubectl get deployment -n kube-system aws-load-balancer-controller
kubectl logs -n kube-system deployment/aws-load-balancer-controller

# Check Karpenter
kubectl get deployment -n kube-system karpenter
kubectl logs -n kube-system deployment/karpenter

# Check Metrics Server
kubectl get deployment -n kube-system metrics-server
kubectl top nodes

# Check Karpenter configurations
kubectl get ec2nodeclass
kubectl get nodepool
```

## Upgrading

To upgrade a Helm chart:

```bash
# Update repository
helm repo update

# Upgrade specific chart
helm upgrade aws-load-balancer-controller eks/aws-load-balancer-controller \
    --namespace kube-system \
    -f aws-load-balancer-controller-values.yaml

# Or upgrade all
./install.sh  # This uses upgrade --install
```

## Uninstalling

To remove a component:

```bash
# Uninstall Helm release
helm uninstall <release-name> -n kube-system

# Delete Karpenter configurations
kubectl delete -f ../karpenter/common-nodepool.yaml
kubectl delete -f ../karpenter/common-ec2nodeclass.yaml
```

**Note:** IAM roles and Pod Identity Associations are still managed by Terraform and will be removed when you run `terraform destroy`.

## Troubleshooting

### AWS Load Balancer Controller Issues

```bash
# Check service account
kubectl get serviceaccount -n kube-system aws-load-balancer-controller

# Check pod identity
aws eks describe-pod-identity-association \
    --cluster-name <cluster-name> \
    --association-id <association-id>

# Check logs
kubectl logs -n kube-system deployment/aws-load-balancer-controller --tail=100
```

### Karpenter Issues

```bash
# Check Karpenter logs
kubectl logs -n kube-system deployment/karpenter -c controller --tail=100

# Check EC2NodeClass status
kubectl describe ec2nodeclass common-nodeclass

# Check NodePool status
kubectl describe nodepool common-nodepool
```

### Metrics Server Issues

```bash
# Check metrics
kubectl top nodes
kubectl top pods -A

# Check logs
kubectl logs -n kube-system deployment/metrics-server --tail=100
```

## File Structure

```
helm-installations/
├── README.md                                    # This file
├── generate-values.sh                           # Auto-generate values from Terraform
├── install.sh                                   # Install all Helm charts
├── aws-load-balancer-controller-values.yaml     # ALB Controller config
├── karpenter-values.yaml                        # Karpenter config
└── metrics-server-values.yaml                   # Metrics Server config

../karpenter/
├── apply-karpenter-config.sh                    # Apply Karpenter K8s resources
├── common-ec2nodeclass.yaml                     # EC2NodeClass template
└── common-nodepool.yaml                         # NodePool configuration
```

## Integration with Terraform

While these Helm charts are **not managed by Terraform**, they depend on resources created by Terraform:

| Terraform Resource | Purpose | Used By |
|-------------------|---------|---------|
| `aws_iam_role.aws_lbc` | IAM role for ALB Controller | AWS Load Balancer Controller |
| `aws_eks_pod_identity_association.aws_lbc` | Pod Identity for ALB Controller | AWS Load Balancer Controller |
| Karpenter IAM role (in eks-karpenter module) | IAM role for Karpenter | Karpenter |
| Karpenter SQS queue | Interruption handling | Karpenter |
| `aws_iam_role.backend_bedrock` | IAM role for backend pods | Application backend |

These resources are outputs from Terraform and can be queried via:
```bash
cd ../../iac-612674025488-us-west-2
terraform output
```

## Version Management

Chart versions are specified in:
- `install.sh` - Default versions used by automation
- Individual values files - Can override versions

To update versions, edit the install script or specify `--version` during manual installation.

## Next Steps

After installing these add-ons:

1. Deploy your application workloads in `../` directory
2. Configure Ingress resources for ALB
3. Monitor Karpenter auto-scaling behavior
4. Set up HPA (Horizontal Pod Autoscaler) for your workloads

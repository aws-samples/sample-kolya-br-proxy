#!/bin/bash
set -e

# Helm Installations for EKS Cluster Add-ons
# This script installs AWS Load Balancer Controller, Karpenter, and Metrics Server
#
# Prerequisites:
# 1. EKS cluster must be created (via Terraform)
# 2. IAM roles and Pod Identity Associations must exist (created by Terraform)
# 3. kubectl must be configured to access the cluster
# 4. Helm must be installed

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

function info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

function warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

function error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# Check prerequisites
if ! command -v kubectl &> /dev/null; then
    error "kubectl is not installed"
fi

if ! command -v helm &> /dev/null; then
    error "helm is not installed"
fi

# Check if values files have been updated
if grep -q "REPLACE_WITH" "$SCRIPT_DIR/aws-load-balancer-controller-values.yaml" 2>/dev/null; then
    error "Please update aws-load-balancer-controller-values.yaml with your cluster information"
fi

if grep -q "REPLACE_WITH" "$SCRIPT_DIR/karpenter-values.yaml" 2>/dev/null; then
    error "Please update karpenter-values.yaml with your cluster information"
fi

info "Installing AWS Load Balancer Controller..."
info "NOTE: Using v3.0.0 which requires CRD updates. See documentation."
helm repo add eks https://aws.github.io/eks-charts
helm repo update
helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
    --version 3.0.0 \
    --namespace kube-system \
    --values "$SCRIPT_DIR/aws-load-balancer-controller-values.yaml" \
    --timeout 600s \
    --wait

info "AWS Load Balancer Controller installed successfully"

info "Installing Karpenter..."
helm upgrade --install karpenter oci://public.ecr.aws/karpenter/karpenter \
    --version 1.9.0 \
    --namespace kube-system \
    --values "$SCRIPT_DIR/karpenter-values.yaml" \
    --timeout 600s \
    --wait

info "Karpenter installed successfully"

info "Applying Karpenter node configurations..."
# Apply Karpenter NodePool and EC2NodeClass
KARPENTER_CONFIG_DIR="$SCRIPT_DIR/../karpenter"
# Determine Terraform directory - go up from helm-installations to infrastructure, then to root, then to iac
TF_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)/iac-612674025488-us-west-2"

if [ -f "$KARPENTER_CONFIG_DIR/apply-karpenter-config.sh" ]; then
    if [ -d "$TF_DIR" ]; then
        bash "$KARPENTER_CONFIG_DIR/apply-karpenter-config.sh" "$TF_DIR"
        info "Karpenter node configurations applied successfully"
    else
        warn "Terraform directory not found at $TF_DIR"
        warn "Please run manually: cd k8s/infrastructure/karpenter && ./apply-karpenter-config.sh /path/to/terraform"
    fi
else
    warn "Karpenter config script not found at $KARPENTER_CONFIG_DIR/apply-karpenter-config.sh"
    warn "Please run manually: cd k8s/infrastructure/karpenter && ./apply-karpenter-config.sh"
fi

info "Installing Metrics Server..."
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/
helm repo update
helm upgrade --install metrics-server metrics-server/metrics-server \
    --version 3.13.0 \
    --namespace kube-system \
    --values "$SCRIPT_DIR/metrics-server-values.yaml" \
    --timeout 600s \
    --wait

info "Metrics Server installed successfully"

info "All Helm charts installed successfully!"
info "Karpenter is ready with NodePool and EC2NodeClass configured"
info "Run 'kubectl get nodepool' and 'kubectl get ec2nodeclass' to verify"

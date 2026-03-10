#!/bin/bash
set -e

# Generate Helm values from Terraform outputs
# This script reads Terraform outputs and generates the Helm values files
#
# Usage: ./generate-values.sh [path-to-terraform-directory]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="${1:-$SCRIPT_DIR/../../../iac-612674025488-us-west-2}"

# Color output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

function info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

function error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

if [ ! -d "$TF_DIR" ]; then
    error "Terraform directory not found: $TF_DIR"
fi

info "Reading Terraform outputs from: $TF_DIR"

cd "$TF_DIR"

# Get Terraform outputs
CLUSTER_NAME=$(terraform output -raw cluster_name 2>/dev/null) || error "Failed to get cluster_name"
CLUSTER_ENDPOINT=$(terraform output -raw cluster_endpoint 2>/dev/null) || error "Failed to get cluster_endpoint"
VPC_ID=$(terraform output -raw vpc_id 2>/dev/null) || error "Failed to get vpc_id"
AWS_REGION=$(terraform output -raw region 2>/dev/null || echo "us-west-2")
KARPENTER_SERVICE_ACCOUNT=$(terraform output -raw karpenter_service_account 2>/dev/null) || error "Failed to get karpenter_service_account"
KARPENTER_QUEUE_NAME=$(terraform output -raw karpenter_queue_name 2>/dev/null) || error "Failed to get karpenter_queue_name"

info "Generating AWS Load Balancer Controller values..."
cat > "$SCRIPT_DIR/aws-load-balancer-controller-values.yaml" <<EOF
# AWS Load Balancer Controller Helm Values
# Generated automatically from Terraform outputs

clusterName: ${CLUSTER_NAME}
region: ${AWS_REGION}
vpcId: ${VPC_ID}

serviceAccount:
  name: aws-load-balancer-controller
  # Note: Pod Identity Association is managed by Terraform
  # The IAM role is created in modules/eks-addons
EOF

info "Generating Karpenter values..."
cat > "$SCRIPT_DIR/karpenter-values.yaml" <<EOF
# Karpenter Helm Values
# Generated automatically from Terraform outputs

serviceAccount:
  name: ${KARPENTER_SERVICE_ACCOUNT}

settings:
  clusterName: ${CLUSTER_NAME}
  clusterEndpoint: ${CLUSTER_ENDPOINT}
  interruptionQueue: ${KARPENTER_QUEUE_NAME}
EOF

info "Values files generated successfully!"
info "  - aws-load-balancer-controller-values.yaml"
info "  - karpenter-values.yaml"
info "  - metrics-server-values.yaml (static, no changes needed)"
info ""
info "Next step: Run ./install.sh to install the Helm charts"

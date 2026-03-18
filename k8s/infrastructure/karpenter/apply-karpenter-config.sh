#!/bin/bash
set -e

# Apply Karpenter Node Configurations
# This script generates and applies Karpenter EC2NodeClass and NodePool from templates
# Environment-specific values are determined by the Terraform workspace (prod vs non-prod)
#
# Usage: ./apply-karpenter-config.sh [path-to-terraform-directory]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="${1:-../../iac}"

# Color output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

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

if [ ! -d "$TF_DIR" ]; then
    error "Terraform directory not found: $TF_DIR"
fi

info "Reading Terraform outputs from: $TF_DIR"

cd "$TF_DIR"

# Get Terraform outputs
CLUSTER_NAME=$(terraform output -raw cluster_name 2>/dev/null) || error "Failed to get cluster_name"
KARPENTER_NODE_IAM_ROLE_NAME=$(terraform output -raw karpenter_node_iam_role_name 2>/dev/null) || error "Failed to get karpenter_node_iam_role_name"

# Determine environment from Terraform workspace
WORKSPACE=$(terraform workspace show 2>/dev/null) || error "Failed to get Terraform workspace"
info "Terraform workspace: $WORKSPACE"

# Environment-specific configuration
if [ "$WORKSPACE" = "prod" ]; then
    info "Using PRODUCTION Karpenter configuration"
    INSTANCE_CATEGORIES='"m"'              # m7g series only
    INSTANCE_MIN_GENERATION="6"            # generation > 6 (m7g)
    VOLUME_SIZE="100Gi"
    LIMITS_CPU="1000"
    LIMITS_MEMORY="1000Gi"
else
    info "Using NON-PROD Karpenter configuration"
    INSTANCE_CATEGORIES='"t"'              # t4g series only
    INSTANCE_MIN_GENERATION="2"            # generation > 2 (t4g)
    VOLUME_SIZE="30Gi"
    LIMITS_CPU="100"
    LIMITS_MEMORY="100Gi"
fi

info "  Instance categories: $INSTANCE_CATEGORIES"
info "  Volume size: $VOLUME_SIZE"
info "  CPU limit: $LIMITS_CPU, Memory limit: $LIMITS_MEMORY"

info "Applying Karpenter EC2NodeClass..."
sed -e "s/\${subnetSelectorTermsValue}/${CLUSTER_NAME}/g" \
    -e "s/\${node_iam_role_name}/${KARPENTER_NODE_IAM_ROLE_NAME}/g" \
    -e "s/\${volume_size}/${VOLUME_SIZE}/g" \
    -e "s/\${workspace}/${WORKSPACE}/g" \
    "$SCRIPT_DIR/common-ec2nodeclass.yaml" | kubectl apply -f -

info "Applying Karpenter NodePool..."
sed -e "s/\${instance_categories}/${INSTANCE_CATEGORIES}/g" \
    -e "s/\${instance_min_generation}/${INSTANCE_MIN_GENERATION}/g" \
    -e "s/\${limits_cpu}/${LIMITS_CPU}/g" \
    -e "s/\${limits_memory}/${LIMITS_MEMORY}/g" \
    "$SCRIPT_DIR/common-nodepool.yaml" | kubectl apply -f -

info "Karpenter configurations applied successfully!"
info "Run 'kubectl get ec2nodeclass' to verify EC2NodeClass"
info "Run 'kubectl get nodepool' to verify NodePool"

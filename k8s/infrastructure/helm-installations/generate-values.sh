#!/bin/bash
set -e

# Generate Helm values from Terraform outputs or environment variables
# This script reads Terraform outputs and generates the Helm values files
#
# Environment variables take precedence over Terraform outputs.
# This allows deploy-to-existing.sh to export values before calling this script,
# while deploy-all.sh continues to work unchanged (env vars empty → fallback to terraform).
#
# Usage:
#   ./generate-values.sh [path-to-terraform-directory]
#
# Supported environment variables:
#   CLUSTER_NAME, CLUSTER_ENDPOINT, VPC_ID, AWS_REGION
#   KARPENTER_SERVICE_ACCOUNT, KARPENTER_QUEUE_NAME
#   SKIP_KARPENTER=true  (skip generating karpenter-values.yaml)

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

function warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

function error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

# Helper: get value from env var, fallback to terraform output
# Usage: tf_or_env "ENV_VAR_NAME" "terraform_output_key" [required=true]
tf_or_env() {
    local env_val="${!1}"
    local tf_key="$2"
    local required="${3:-true}"

    if [[ -n "$env_val" ]]; then
        echo "$env_val"
        return 0
    fi

    if [[ "$TF_AVAILABLE" == "true" ]]; then
        local tf_val
        tf_val=$(terraform output -raw "$tf_key" 2>/dev/null) || true
        if [[ -n "$tf_val" ]]; then
            echo "$tf_val"
            return 0
        fi
    fi

    if [[ "$required" == "true" ]]; then
        error "Missing required parameter: set $1 env var or provide via Terraform output '$tf_key'"
    fi
    echo ""
}

# Determine if Terraform is available
TF_AVAILABLE=false
if [[ -d "$TF_DIR" ]]; then
    cd "$TF_DIR"
    if terraform output -raw cluster_name &>/dev/null; then
        TF_AVAILABLE=true
        info "Reading Terraform outputs from: $TF_DIR"
    fi
fi

if [[ "$TF_AVAILABLE" == "false" && -z "$CLUSTER_NAME" ]]; then
    error "No Terraform directory found and CLUSTER_NAME env var not set. Provide parameters via environment variables or a valid Terraform directory."
fi

# Get parameters (env var → terraform output)
CLUSTER_NAME=$(tf_or_env "CLUSTER_NAME" "cluster_name" "true")
VPC_ID=$(tf_or_env "VPC_ID" "vpc_id" "true")
AWS_REGION=$(tf_or_env "AWS_REGION" "region" "false")
AWS_REGION="${AWS_REGION:-us-west-2}"
CLUSTER_ENDPOINT=$(tf_or_env "CLUSTER_ENDPOINT" "cluster_endpoint" "false")
KARPENTER_SERVICE_ACCOUNT=$(tf_or_env "KARPENTER_SERVICE_ACCOUNT" "karpenter_service_account" "false")
KARPENTER_QUEUE_NAME=$(tf_or_env "KARPENTER_QUEUE_NAME" "karpenter_queue_name" "false")

info "Parameters:"
info "  CLUSTER_NAME=$CLUSTER_NAME"
info "  VPC_ID=$VPC_ID"
info "  AWS_REGION=$AWS_REGION"

# Generate ALBC values
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

# Generate Karpenter values (skip if SKIP_KARPENTER=true or missing required params)
if [[ "${SKIP_KARPENTER}" == "true" ]]; then
    warn "Skipping Karpenter values generation (SKIP_KARPENTER=true)"
elif [[ -z "$CLUSTER_ENDPOINT" || -z "$KARPENTER_SERVICE_ACCOUNT" || -z "$KARPENTER_QUEUE_NAME" ]]; then
    warn "Skipping Karpenter values generation (missing CLUSTER_ENDPOINT, KARPENTER_SERVICE_ACCOUNT, or KARPENTER_QUEUE_NAME)"
else
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
fi

info "Values files generated successfully!"
info "  - aws-load-balancer-controller-values.yaml"
if [[ "${SKIP_KARPENTER}" != "true" && -n "$CLUSTER_ENDPOINT" && -n "$KARPENTER_SERVICE_ACCOUNT" && -n "$KARPENTER_QUEUE_NAME" ]]; then
    info "  - karpenter-values.yaml"
fi
info "  - metrics-server-values.yaml (static, no changes needed)"
info ""
info "Next step: Run ./install.sh to install the Helm charts"

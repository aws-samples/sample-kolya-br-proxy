#!/bin/bash
#
# Initialize Terraform S3 backend configuration
# Generates providers.tf from providers.tf.template with user-provided values
#
# Usage:
#   ./init-backend.sh
#
# This script is for users who run Terraform independently of deploy-all.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() { echo -e "${BLUE}ℹ️  $1${NC}"; }
print_success() { echo -e "${GREEN}✅ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
print_error() { echo -e "${RED}❌ $1${NC}"; }

cd "$SCRIPT_DIR"

# Check if providers.tf already exists
if [[ -f "providers.tf" ]]; then
    print_warning "providers.tf already exists"
    read -p "Overwrite? (y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Keeping existing providers.tf"
        exit 0
    fi
fi

# Check template exists
if [[ ! -f "providers.tf.template" ]]; then
    print_error "providers.tf.template not found in $SCRIPT_DIR"
    exit 1
fi

# Detect defaults from AWS CLI
DEFAULT_REGION=$(aws configure get region 2>/dev/null || echo "us-west-2")
DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")

echo ""
print_info "Terraform S3 Backend Configuration"
echo ""
echo "Terraform remote state requires an S3 bucket."
echo "Please create the bucket first if it doesn't exist."
echo ""

# Prompt for values
read -p "S3 bucket name for Terraform state: " TF_STATE_BUCKET
if [[ -z "$TF_STATE_BUCKET" ]]; then
    print_error "Bucket name is required"
    exit 1
fi

read -p "S3 bucket region [${DEFAULT_REGION}]: " TF_STATE_REGION
TF_STATE_REGION="${TF_STATE_REGION:-$DEFAULT_REGION}"

read -p "State key [kolya-br-proxy/tf.state]: " TF_STATE_KEY
TF_STATE_KEY="${TF_STATE_KEY:-kolya-br-proxy/tf.state}"

# Generate providers.tf
export TF_STATE_BUCKET TF_STATE_REGION TF_STATE_KEY
envsubst '${TF_STATE_BUCKET} ${TF_STATE_REGION} ${TF_STATE_KEY}' < providers.tf.template > providers.tf

echo ""
print_success "providers.tf generated successfully"
print_info "Backend configuration:"
echo "  Bucket: $TF_STATE_BUCKET"
echo "  Region: $TF_STATE_REGION"
echo "  Key:    $TF_STATE_KEY"
echo ""
print_info "Next steps:"
echo "  1. Run: terraform init -reconfigure"
echo "  2. Run: terraform plan"
echo "  3. Run: terraform apply"

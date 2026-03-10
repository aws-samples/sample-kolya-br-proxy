#!/bin/bash

# Script to generate terraform.tfvars from current AWS profile
# Based on lakehouse-core implementation

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Generating terraform.tfvars from current AWS profile...${NC}"

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo -e "${RED}Error: AWS CLI is not installed${NC}"
    exit 1
fi

# Get current AWS profile info
ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")
REGION=$(aws configure get region 2>/dev/null || echo "")

if [ -z "$ACCOUNT" ]; then
    echo -e "${RED}Error: Unable to get AWS account ID. Please check your AWS credentials.${NC}"
    exit 1
fi

if [ -z "$REGION" ]; then
    echo -e "${YELLOW}Warning: No default region configured. Using us-west-2${NC}"
    REGION="us-west-2"
fi

# Create terraform.tfvars file
cat > terraform.tfvars << EOF
# Auto-generated terraform.tfvars
# Generated on: $(date)
# AWS Profile: $(aws configure list-profiles 2>/dev/null | head -1 || echo "default")

# AWS Configuration
account = "$ACCOUNT"
region  = "$REGION"

# Domain Configuration
domain_name = "kolya.fun"

# Infrastructure Versions
eks_version = "1.35"
karpenter_version = "1.9.0"
aws_lbc_version = "3.0.0"
metrics_server_version = "3.13.0"
EOF

echo -e "${GREEN}✓ terraform.tfvars generated successfully${NC}"
echo -e "${GREEN}Account: $ACCOUNT${NC}"
echo -e "${GREEN}Region: $REGION${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Review and modify terraform.tfvars if needed"
echo "2. Run: terraform init"
echo "3. Run: terraform plan"
echo "4. Run: terraform apply"

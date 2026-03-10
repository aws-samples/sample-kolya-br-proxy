#!/bin/bash
set -e

# Verification script for Global Accelerator prerequisites
# This script checks if your environment is ready for Global Accelerator deployment

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

function info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

function success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

function warning() {
    echo -e "${YELLOW}[⚠]${NC} $1"
    ((WARNINGS++))
}

function error() {
    echo -e "${RED}[✗]${NC} $1"
    ((ERRORS++))
}

info "Verifying Global Accelerator prerequisites..."
echo ""

# Check 1: kubectl connectivity
info "Check 1: kubectl connectivity"
if kubectl cluster-info &>/dev/null; then
    success "kubectl is configured and connected to cluster"
else
    error "kubectl is not configured or cannot connect to cluster"
    exit 1
fi
echo ""

# Check 2: Namespace exists
info "Check 2: Namespace 'kbp' exists"
if kubectl get namespace kbp &>/dev/null; then
    success "Namespace 'kbp' exists"
else
    error "Namespace 'kbp' not found"
fi
echo ""

# Check 3: Ingress resources exist
info "Check 3: Ingress resources exist"
FRONTEND_EXISTS=$(kubectl get ingress kolya-br-proxy-frontend -n kbp --ignore-not-found -o name)
API_EXISTS=$(kubectl get ingress kolya-br-proxy-api -n kbp --ignore-not-found -o name)

if [ -n "$FRONTEND_EXISTS" ]; then
    success "Frontend Ingress exists"
else
    error "Frontend Ingress 'kolya-br-proxy-frontend' not found in namespace 'kbp'"
fi

if [ -n "$API_EXISTS" ]; then
    success "API Ingress exists"
else
    error "API Ingress 'kolya-br-proxy-api' not found in namespace 'kbp'"
fi
echo ""

# Check 4: Ingress has ALB name annotation (CRITICAL)
info "Check 4: Ingress resources specify ALB names (CRITICAL)"

if [ -n "$FRONTEND_EXISTS" ]; then
    FRONTEND_ALB_NAME=$(kubectl get ingress kolya-br-proxy-frontend -n kbp \
        -o jsonpath='{.metadata.annotations.alb\.ingress\.kubernetes\.io/load-balancer-name}' 2>/dev/null)

    if [ -n "$FRONTEND_ALB_NAME" ]; then
        success "Frontend Ingress specifies ALB name: $FRONTEND_ALB_NAME"
    else
        error "Frontend Ingress does NOT specify alb.ingress.kubernetes.io/load-balancer-name annotation"
        error "ALB Controller will generate a random name, and Terraform won't be able to discover it"
        echo -e "${YELLOW}Fix: Add annotation to ingress-frontend.yaml:${NC}"
        echo "  annotations:"
        echo "    alb.ingress.kubernetes.io/load-balancer-name: kolya-br-proxy-frontend-alb"
    fi
fi

if [ -n "$API_EXISTS" ]; then
    API_ALB_NAME=$(kubectl get ingress kolya-br-proxy-api -n kbp \
        -o jsonpath='{.metadata.annotations.alb\.ingress\.kubernetes\.io/load-balancer-name}' 2>/dev/null)

    if [ -n "$API_ALB_NAME" ]; then
        success "API Ingress specifies ALB name: $API_ALB_NAME"
    else
        error "API Ingress does NOT specify alb.ingress.kubernetes.io/load-balancer-name annotation"
        error "ALB Controller will generate a random name, and Terraform won't be able to discover it"
        echo -e "${YELLOW}Fix: Add annotation to ingress-api.yaml:${NC}"
        echo "  annotations:"
        echo "    alb.ingress.kubernetes.io/load-balancer-name: kolya-br-proxy-api-alb"
    fi
fi
echo ""

# Check 5: ALBs are created and healthy
info "Check 5: ALBs are provisioned"

if [ -n "$FRONTEND_EXISTS" ]; then
    FRONTEND_ALB_DNS=$(kubectl get ingress kolya-br-proxy-frontend -n kbp \
        -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)

    if [ -n "$FRONTEND_ALB_DNS" ]; then
        success "Frontend ALB is provisioned: $FRONTEND_ALB_DNS"
    else
        warning "Frontend ALB is not yet provisioned (Ingress may be pending)"
        echo -e "${YELLOW}Wait a few minutes for ALB Controller to create the ALB${NC}"
    fi
fi

if [ -n "$API_EXISTS" ]; then
    API_ALB_DNS=$(kubectl get ingress kolya-br-proxy-api -n kbp \
        -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)

    if [ -n "$API_ALB_DNS" ]; then
        success "API ALB is provisioned: $API_ALB_DNS"
    else
        warning "API ALB is not yet provisioned (Ingress may be pending)"
        echo -e "${YELLOW}Wait a few minutes for ALB Controller to create the ALB${NC}"
    fi
fi
echo ""

# Check 6: AWS CLI connectivity
info "Check 6: AWS CLI connectivity"
if aws sts get-caller-identity &>/dev/null; then
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    REGION=$(aws configure get region || echo "not set")
    success "AWS CLI is configured (Account: $ACCOUNT_ID, Region: $REGION)"
else
    error "AWS CLI is not configured or credentials are invalid"
fi
echo ""

# Check 7: Verify ALB names in AWS match Ingress annotations
info "Check 7: Verify ALB names in AWS"

if command -v aws &>/dev/null && [ -n "$FRONTEND_ALB_NAME" ]; then
    if aws elbv2 describe-load-balancers --names "$FRONTEND_ALB_NAME" &>/dev/null; then
        success "Frontend ALB '$FRONTEND_ALB_NAME' found in AWS"
    else
        warning "Frontend ALB '$FRONTEND_ALB_NAME' not found in AWS yet"
        echo -e "${YELLOW}ALB may still be creating. Wait a few minutes.${NC}"
    fi
fi

if command -v aws &>/dev/null && [ -n "$API_ALB_NAME" ]; then
    if aws elbv2 describe-load-balancers --names "$API_ALB_NAME" &>/dev/null; then
        success "API ALB '$API_ALB_NAME' found in AWS"
    else
        warning "API ALB '$API_ALB_NAME' not found in AWS yet"
        echo -e "${YELLOW}ALB may still be creating. Wait a few minutes.${NC}"
    fi
fi
echo ""

# Check 8: Terraform variable configuration
info "Check 8: Terraform variable configuration"

if [ -f "terraform.tfvars" ]; then
    success "terraform.tfvars exists"

    # Check if Global Accelerator is enabled
    GA_ENABLED=$(grep -E "^enable_global_accelerator\s*=" terraform.tfvars | grep -c "true" || echo "0")

    if [ "$GA_ENABLED" -eq "1" ]; then
        warning "Global Accelerator is already enabled in terraform.tfvars"
        echo -e "${YELLOW}Make sure ALBs are created before applying Terraform${NC}"
    else
        success "Global Accelerator is disabled (will be enabled manually)"
    fi

    # Check if custom ALB names are specified
    if grep -q "^ga_frontend_alb_name" terraform.tfvars; then
        TFVARS_FRONTEND=$(grep "^ga_frontend_alb_name" terraform.tfvars | cut -d'=' -f2 | tr -d ' "')
        info "Custom frontend ALB name in tfvars: $TFVARS_FRONTEND"
        if [ "$TFVARS_FRONTEND" != "$FRONTEND_ALB_NAME" ]; then
            warning "tfvars name ($TFVARS_FRONTEND) doesn't match Ingress annotation ($FRONTEND_ALB_NAME)"
        fi
    fi

    if grep -q "^ga_api_alb_name" terraform.tfvars; then
        TFVARS_API=$(grep "^ga_api_alb_name" terraform.tfvars | cut -d'=' -f2 | tr -d ' "')
        info "Custom API ALB name in tfvars: $TFVARS_API"
        if [ "$TFVARS_API" != "$API_ALB_NAME" ]; then
            warning "tfvars name ($TFVARS_API) doesn't match Ingress annotation ($API_ALB_NAME)"
        fi
    fi
else
    warning "terraform.tfvars not found in current directory"
fi
echo ""

# Summary
echo "=========================================="
echo "VERIFICATION SUMMARY"
echo "=========================================="

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✓ All checks passed!${NC}"
    echo ""
    echo "You are ready to enable Global Accelerator:"
    echo "  1. Add to terraform.tfvars: enable_global_accelerator = true"
    echo "  2. Run: terraform apply"
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠ $WARNINGS warning(s) found${NC}"
    echo ""
    echo "You can proceed with caution, but review warnings above."
else
    echo -e "${RED}✗ $ERRORS error(s) found${NC}"
    echo -e "${YELLOW}⚠ $WARNINGS warning(s) found${NC}"
    echo ""
    echo "Please fix errors before enabling Global Accelerator."
    exit 1
fi

echo ""
echo "For more information, see:"
echo "  - modules/global-accelerator/README.md"
echo "  - docs/GLOBAL_ACCELERATOR_DEPLOYMENT.md"

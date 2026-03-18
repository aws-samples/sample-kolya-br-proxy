#!/bin/bash
#
# Kolya BR Proxy - Deploy to Existing EKS Cluster
# Deploys the application to a pre-existing EKS cluster (no Terraform required)
#
# Prerequisites:
#   - EKS cluster created, kubectl configured
#   - RDS PostgreSQL created and accessible from cluster
#   - AWS Secrets Manager secret created (for backend secrets)
#   - ECR repositories created (or permissions to auto-create)
#   - ACM certificate issued
#   - EBS CSI Driver installed (for PVC)
#   - IAM roles created for ALBC and ESO Pod Identity
#
# Deployment flow:
#   1. Deploy Kubernetes infrastructure (Helm: ALBC, Karpenter optional, Metrics Server, ESO, Redis)
#   2. Build Docker images and push to ECR
#   3. Deploy application to EKS (Backend & Frontend)
#
# Usage:
#   ./deploy-to-existing.sh                       # Interactive full deployment
#   ./deploy-to-existing.sh --config config.yaml  # From config file
#   ./deploy-to-existing.sh --step 1              # Run step 1 only (Helm)
#   ./deploy-to-existing.sh --step 2              # Run step 2 only (Docker build)
#   ./deploy-to-existing.sh --step 3              # Run step 3 only (App deployment)
#   ./deploy-to-existing.sh --help                # Show help

set -e

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# Directory definitions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$SCRIPT_DIR/k8s"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# Default configuration
SKIP_CONFIRMATION=false
SPECIFIC_STEP=""
CONFIG_FILE=""
DEPLOY_ENV="non-prod"

# Cluster parameters (collected interactively or from config)
CLUSTER_NAME=""
AWS_REGION=""
VPC_ID=""
ECR_ACCOUNT_ID=""
CLUSTER_ENDPOINT=""
INSTALL_KARPENTER="no"
INSTALL_ALBC="yes"
SECRETS_MANAGER_NAME=""
KARPENTER_SERVICE_ACCOUNT=""
KARPENTER_QUEUE_NAME=""

# Print functions
print_banner() {
    echo ""
    echo -e "${CYAN}╔═══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║                                                               ║${NC}"
    echo -e "${CYAN}║    Kolya BR Proxy - Deploy to Existing EKS Cluster            ║${NC}"
    echo -e "${CYAN}║    No Terraform Required                                      ║${NC}"
    echo -e "${CYAN}║                                                               ║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

print_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
}

print_step() {
    echo -e "${MAGENTA}▶ Step $1/3: $2${NC}"
}

print_substep() {
    echo -e "${CYAN}  → $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Show help
show_help() {
    cat << 'EOF'
Kolya BR Proxy - Deploy to Existing EKS Cluster

Usage: ./deploy-to-existing.sh [options]

Options:
  --step <1-3>        Run a specific step only
                      1: Deploy Kubernetes infrastructure (Helm)
                      2: Build and push Docker images
                      3: Deploy application to EKS

  --config <file>     Load cluster parameters from YAML config file
  --yes               Skip all confirmation prompts
  --help              Show this help message

Config file format (YAML):
  cluster_name: my-eks-cluster
  aws_region: us-west-2
  vpc_id: vpc-0abc123
  ecr_account_id: "612674025488"
  secrets_manager_name: my-backend-secrets
  deploy_env: non-prod
  install_karpenter: false
  install_albc: true
  # Optional Karpenter params (required if install_karpenter: true)
  cluster_endpoint: https://xxx.eks.amazonaws.com
  karpenter_service_account: karpenter
  karpenter_queue_name: my-karpenter-queue

Prerequisites:
  - EKS cluster created, kubectl configured
  - RDS PostgreSQL created and accessible from cluster
  - AWS Secrets Manager secret created (empty, for backend secrets)
  - ACM certificate issued
  - EBS CSI Driver installed
  - IAM roles for ALBC and ESO Pod Identity

Deployment flow:
  1. Helm - Deploy Kubernetes infrastructure
     - AWS Load Balancer Controller (optional)
     - Karpenter (optional)
     - Metrics Server
     - External Secrets Operator
     - Redis

  2. Docker - Build and push images
     - Backend Docker image
     - Frontend Docker image
     - Push to Amazon ECR

  3. Kubernetes - Deploy application
     - Configuration wizard (domains, database, auth)
     - Push secrets to Secrets Manager
     - Deploy Backend & Frontend
     - Create Services, Ingress, HPA
EOF
}

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --step)
                SPECIFIC_STEP="$2"
                if [[ ! "$SPECIFIC_STEP" =~ ^[1-3]$ ]]; then
                    print_error "Invalid step number: $SPECIFIC_STEP (must be 1-3)"
                    exit 1
                fi
                shift 2
                ;;
            --config)
                CONFIG_FILE="$2"
                if [[ ! -f "$CONFIG_FILE" ]]; then
                    print_error "Config file not found: $CONFIG_FILE"
                    exit 1
                fi
                shift 2
                ;;
            --yes)
                SKIP_CONFIRMATION=true
                shift
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

# Check dependencies
check_dependencies() {
    print_header "Checking Dependencies"

    local missing_deps=()

    local required_tools=(
        "kubectl:Kubectl:https://kubernetes.io/docs/tasks/tools/"
        "helm:Helm:https://helm.sh/docs/intro/install/"
        "aws:AWS CLI:https://aws.amazon.com/cli/"
        "docker:Docker:https://docs.docker.com/get-docker/"
        "jq:jq:brew install jq"
        "envsubst:envsubst:brew install gettext"
    )

    for tool_info in "${required_tools[@]}"; do
        IFS=':' read -r cmd name url <<< "$tool_info"
        if ! command -v "$cmd" &> /dev/null; then
            missing_deps+=("$name ($url)")
            print_error "$name not installed"
        else
            print_success "$name installed"
        fi
    done

    # yq is needed only if --config is used
    if [[ -n "$CONFIG_FILE" ]] && ! command -v yq &> /dev/null; then
        missing_deps+=("yq (brew install yq) - required for --config")
        print_error "yq not installed (required for --config)"
    fi

    if [ ${#missing_deps[@]} -ne 0 ]; then
        echo ""
        print_error "Missing dependencies:"
        for dep in "${missing_deps[@]}"; do
            echo "  - $dep"
        done
        exit 1
    fi

    print_success "All dependencies satisfied"
}

# Check AWS credentials
check_aws_credentials() {
    print_header "Checking AWS Credentials"

    print_substep "Validating AWS credentials..."
    if ! aws sts get-caller-identity &> /dev/null; then
        print_error "AWS credentials are invalid or not configured"
        echo ""
        echo "Please configure AWS credentials:"
        echo "  aws configure"
        echo "Or set environment variables:"
        echo "  export AWS_ACCESS_KEY_ID=..."
        echo "  export AWS_SECRET_ACCESS_KEY=..."
        exit 1
    fi

    local account_id=$(aws sts get-caller-identity --query Account --output text)
    local user_arn=$(aws sts get-caller-identity --query Arn --output text)

    print_success "AWS credentials valid"
    print_info "Account ID: $account_id"
    print_info "User: $user_arn"
}

# Load parameters from YAML config file
load_config_file() {
    print_substep "Loading config from: $CONFIG_FILE"

    CLUSTER_NAME=$(yq '.cluster_name // ""' "$CONFIG_FILE")
    AWS_REGION=$(yq '.aws_region // ""' "$CONFIG_FILE")
    VPC_ID=$(yq '.vpc_id // ""' "$CONFIG_FILE")
    ECR_ACCOUNT_ID=$(yq '.ecr_account_id // ""' "$CONFIG_FILE")
    SECRETS_MANAGER_NAME=$(yq '.secrets_manager_name // ""' "$CONFIG_FILE")
    DEPLOY_ENV=$(yq '.deploy_env // "non-prod"' "$CONFIG_FILE")

    local install_karpenter_val=$(yq '.install_karpenter // false' "$CONFIG_FILE")
    local install_albc_val=$(yq '.install_albc // true' "$CONFIG_FILE")
    INSTALL_KARPENTER=$([[ "$install_karpenter_val" == "true" ]] && echo "yes" || echo "no")
    INSTALL_ALBC=$([[ "$install_albc_val" == "true" ]] && echo "yes" || echo "no")

    CLUSTER_ENDPOINT=$(yq '.cluster_endpoint // ""' "$CONFIG_FILE")
    KARPENTER_SERVICE_ACCOUNT=$(yq '.karpenter_service_account // ""' "$CONFIG_FILE")
    KARPENTER_QUEUE_NAME=$(yq '.karpenter_queue_name // ""' "$CONFIG_FILE")

    print_success "Config loaded from file"
}

# Collect cluster parameters interactively
collect_cluster_params_interactive() {
    print_header "Cluster Configuration"
    echo "Please provide your existing EKS cluster details."
    echo ""

    # Ensure stdin is available
    exec < /dev/tty

    # Cluster name
    while [[ -z "$CLUSTER_NAME" ]]; do
        read -p "EKS Cluster Name: " CLUSTER_NAME
        [[ -z "$CLUSTER_NAME" ]] && print_warning "Cluster name is required"
    done

    # AWS Region
    while [[ -z "$AWS_REGION" ]]; do
        read -p "AWS Region (e.g. us-west-2): " AWS_REGION
        [[ -z "$AWS_REGION" ]] && print_warning "AWS Region is required"
    done

    # VPC ID
    while [[ -z "$VPC_ID" ]]; do
        read -p "VPC ID (e.g. vpc-0abc123): " VPC_ID
        [[ -z "$VPC_ID" ]] && print_warning "VPC ID is required"
    done

    # ECR Account ID
    local default_account_id=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")
    if [[ -n "$default_account_id" ]]; then
        read -p "ECR Account ID [$default_account_id]: " ECR_ACCOUNT_ID
        ECR_ACCOUNT_ID="${ECR_ACCOUNT_ID:-$default_account_id}"
    else
        while [[ -z "$ECR_ACCOUNT_ID" ]]; do
            read -p "ECR Account ID: " ECR_ACCOUNT_ID
            [[ -z "$ECR_ACCOUNT_ID" ]] && print_warning "ECR Account ID is required"
        done
    fi

    # Secrets Manager name
    while [[ -z "$SECRETS_MANAGER_NAME" ]]; do
        read -p "Secrets Manager Secret Name (pre-created): " SECRETS_MANAGER_NAME
        [[ -z "$SECRETS_MANAGER_NAME" ]] && print_warning "Secrets Manager name is required"
    done

    # Environment
    echo ""
    echo "Deployment environment:"
    echo "  1) non-prod (default)"
    echo "  2) prod"
    read -p "Select [1/2]: " env_choice
    if [[ "$env_choice" == "2" ]]; then
        DEPLOY_ENV="prod"
    else
        DEPLOY_ENV="non-prod"
    fi

    # ALBC
    echo ""
    echo "Install AWS Load Balancer Controller?"
    echo "  (Skip if already installed in your cluster)"
    read -p "Install ALBC? (Y/n): " albc_choice
    INSTALL_ALBC=$([[ "$albc_choice" =~ ^[Nn] ]] && echo "no" || echo "yes")

    # Karpenter
    echo ""
    echo "Install Karpenter?"
    echo "  (Skip if already installed or using a different autoscaler)"
    read -p "Install Karpenter? (y/N): " karpenter_choice
    INSTALL_KARPENTER=$([[ "$karpenter_choice" =~ ^[Yy] ]] && echo "yes" || echo "no")

    if [[ "$INSTALL_KARPENTER" == "yes" ]]; then
        read -p "Cluster Endpoint (e.g. https://xxx.eks.amazonaws.com): " CLUSTER_ENDPOINT
        read -p "Karpenter Service Account Name [karpenter]: " KARPENTER_SERVICE_ACCOUNT
        KARPENTER_SERVICE_ACCOUNT="${KARPENTER_SERVICE_ACCOUNT:-karpenter}"
        read -p "Karpenter SQS Queue Name: " KARPENTER_QUEUE_NAME
    fi
}

# Collect cluster parameters (from config file or interactive)
collect_cluster_params() {
    if [[ -n "$CONFIG_FILE" ]]; then
        load_config_file
    else
        collect_cluster_params_interactive
    fi

    # Validate required parameters
    local missing=()
    [[ -z "$CLUSTER_NAME" ]] && missing+=("CLUSTER_NAME")
    [[ -z "$AWS_REGION" ]] && missing+=("AWS_REGION")
    [[ -z "$VPC_ID" ]] && missing+=("VPC_ID")
    [[ -z "$ECR_ACCOUNT_ID" ]] && missing+=("ECR_ACCOUNT_ID")
    [[ -z "$SECRETS_MANAGER_NAME" ]] && missing+=("SECRETS_MANAGER_NAME")

    if [ ${#missing[@]} -ne 0 ]; then
        print_error "Missing required parameters: ${missing[*]}"
        exit 1
    fi

    # Summary
    echo ""
    print_header "Cluster Parameters"
    echo "  Cluster Name:     $CLUSTER_NAME"
    echo "  AWS Region:       $AWS_REGION"
    echo "  VPC ID:           $VPC_ID"
    echo "  ECR Account ID:   $ECR_ACCOUNT_ID"
    echo "  Secrets Manager:  $SECRETS_MANAGER_NAME"
    echo "  Environment:      $DEPLOY_ENV"
    echo "  Install ALBC:     $INSTALL_ALBC"
    echo "  Install Karpenter: $INSTALL_KARPENTER"
    if [[ "$INSTALL_KARPENTER" == "yes" ]]; then
        echo "  Cluster Endpoint: $CLUSTER_ENDPOINT"
        echo "  Karpenter SA:     $KARPENTER_SERVICE_ACCOUNT"
        echo "  Karpenter Queue:  $KARPENTER_QUEUE_NAME"
    fi
    echo ""

    if [[ "$SKIP_CONFIRMATION" == "false" ]]; then
        read -p "Confirm parameters? (yes/no): " confirm
        if [[ "$confirm" != "yes" ]]; then
            print_info "Cancelled"
            exit 0
        fi
    fi
}

# Step 1: Deploy Kubernetes infrastructure
deploy_k8s_infrastructure() {
    print_step "1" "Deploy Kubernetes Infrastructure (Helm)"

    # Configure kubectl
    print_substep "Configuring kubectl for cluster: $CLUSTER_NAME ..."
    aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION"
    print_success "kubectl configured"

    # Verify connection
    print_substep "Verifying cluster connection..."
    if ! kubectl cluster-info &> /dev/null; then
        print_error "Cannot connect to EKS cluster"
        exit 1
    fi
    print_success "Cluster connection OK"

    # Authenticate to ECR Public (for Karpenter OCI images)
    if [[ "$INSTALL_KARPENTER" == "yes" ]]; then
        print_substep "Authenticating to ECR Public..."
        if aws ecr-public get-login-password --region us-east-1 | helm registry login --username AWS --password-stdin public.ecr.aws 2>/dev/null; then
            print_success "ECR Public authentication successful"
        else
            print_warning "ECR Public authentication failed, Karpenter installation may fail"
        fi
    fi

    # Export environment variables for generate-values.sh
    export CLUSTER_NAME
    export AWS_REGION
    export VPC_ID
    export CLUSTER_ENDPOINT
    export KARPENTER_SERVICE_ACCOUNT
    export KARPENTER_QUEUE_NAME

    if [[ "$INSTALL_KARPENTER" != "yes" ]]; then
        export SKIP_KARPENTER=true
    fi
    if [[ "$INSTALL_ALBC" != "yes" ]]; then
        export SKIP_ALBC=true
    fi

    # Generate Helm values
    print_substep "Generating Helm values..."
    cd "$K8S_DIR/infrastructure/helm-installations"
    ./generate-values.sh

    # Install components
    print_substep "Installing Helm charts..."
    ./install.sh

    print_success "Step 1 complete: Kubernetes infrastructure deployed"
}

# Step 2: Build and push Docker images
build_and_push_images() {
    print_step "2" "Build and Push Docker Images to ECR"

    local account_id="$ECR_ACCOUNT_ID"
    print_info "ECR Account ID: $account_id"

    # ECR login
    print_substep "Logging in to Amazon ECR..."
    aws ecr get-login-password --region "$AWS_REGION" | \
        docker login --username AWS --password-stdin "$account_id.dkr.ecr.$AWS_REGION.amazonaws.com"
    print_success "ECR login successful"

    # Create ECR repositories (if not exist)
    local repositories=("kolya-br-proxy-backend" "kolya-br-proxy-frontend")
    for repo in "${repositories[@]}"; do
        print_substep "Checking ECR repository: $repo"
        if ! aws ecr describe-repositories --repository-names "$repo" --region "$AWS_REGION" &> /dev/null; then
            print_warning "Repository does not exist, creating..."
            aws ecr create-repository \
                --repository-name "$repo" \
                --region "$AWS_REGION" \
                --image-scanning-configuration scanOnPush=true \
                --encryption-configuration encryptionType=AES256
            print_success "ECR repository created: $repo"
        else
            print_success "ECR repository exists: $repo"
        fi
    done

    # Build Backend image
    print_substep "Building Backend Docker image (platform: linux/arm64)..."
    local backend_image="$account_id.dkr.ecr.$AWS_REGION.amazonaws.com/kolya-br-proxy-backend:latest"
    local backend_tag="$account_id.dkr.ecr.$AWS_REGION.amazonaws.com/kolya-br-proxy-backend:$(date +%Y%m%d-%H%M%S)"

    if ! docker build --network host --platform linux/arm64 -f "$BACKEND_DIR/Dockerfile" -t "$backend_image" -t "$backend_tag" "$SCRIPT_DIR"; then
        print_error "Backend image build failed"
        exit 1
    fi
    print_success "Backend image built"

    print_substep "Pushing Backend image to ECR..."
    docker push "$backend_image"
    docker push "$backend_tag"
    print_success "Backend image pushed"

    # Build Frontend image
    print_substep "Building Frontend Docker image (platform: linux/arm64)..."
    cd "$FRONTEND_DIR"
    local frontend_image="$account_id.dkr.ecr.$AWS_REGION.amazonaws.com/kolya-br-proxy-frontend:latest"
    local frontend_tag="$account_id.dkr.ecr.$AWS_REGION.amazonaws.com/kolya-br-proxy-frontend:$(date +%Y%m%d-%H%M%S)"

    if ! docker build --network host --platform linux/arm64 -t "$frontend_image" -t "$frontend_tag" .; then
        print_error "Frontend image build failed"
        exit 1
    fi
    print_success "Frontend image built"

    print_substep "Pushing Frontend image to ECR..."
    docker push "$frontend_image"
    docker push "$frontend_tag"
    print_success "Frontend image pushed"

    print_success "Step 2 complete: Docker images built and pushed"

    echo ""
    print_info "Image info:"
    echo "  Backend:  $backend_image"
    echo "  Frontend: $frontend_image"
}

# Configuration wizard (no Terraform dependency)
run_config_wizard() {
    local app_dir="$K8S_DIR/application"

    print_header "Configuration Wizard"
    echo "Please provide the following configuration values."
    echo ""

    # Ensure stdin is available
    exec < /dev/tty

    local cfg_region="$AWS_REGION"
    local cfg_account_id="$ECR_ACCOUNT_ID"

    # --- RDS Configuration ---
    print_substep "Database configuration"
    local cfg_rds_endpoint=""
    local cfg_rds_database=""
    local cfg_rds_port="5432"

    read -p "RDS Endpoint (host): " cfg_rds_endpoint
    read -p "RDS Database Name: " cfg_rds_database
    read -p "RDS Port [5432]: " cfg_rds_port
    cfg_rds_port="${cfg_rds_port:-5432}"
    read -sp "RDS Database Password: " cfg_db_password
    echo ""

    # --- Domain names ---
    echo ""
    print_substep "Domain configuration"
    read -p "Frontend domain (e.g. kbp.kolya.fun): " cfg_frontend_domain
    read -p "API domain (e.g. api.kbp.kolya.fun): " cfg_api_domain

    if [[ -z "$cfg_frontend_domain" || -z "$cfg_api_domain" ]]; then
        print_error "Domain names cannot be empty"
        exit 1
    fi

    # --- JWT Secret ---
    echo ""
    print_substep "JWT configuration"
    echo "JWT Secret Key (leave blank to auto-generate):"
    read -p "> " cfg_jwt_secret
    if [[ -z "$cfg_jwt_secret" ]]; then
        cfg_jwt_secret=$(openssl rand -base64 32)
        print_success "Generated random JWT Secret: ${cfg_jwt_secret:0:20}..."
    fi

    # --- Auth provider ---
    echo ""
    print_substep "Authentication Provider"
    local cfg_auth_choice=""
    local cfg_ms_client_id=""
    local cfg_ms_client_secret=""
    local cfg_ms_tenant_id=""
    local cfg_cognito_user_pool_id=""
    local cfg_cognito_client_id=""
    local cfg_cognito_client_secret=""
    local cfg_cognito_region="$cfg_region"

    echo "  1) AWS Cognito"
    echo "  2) Microsoft Entra ID"
    echo "  3) Both"
    read -p "Select authentication method [1/2/3]: " cfg_auth_choice
    cfg_auth_choice="${cfg_auth_choice:-1}"

    if [[ "$cfg_auth_choice" == "2" || "$cfg_auth_choice" == "3" ]]; then
        echo ""
        print_substep "Microsoft Entra ID configuration"
        read -p "Microsoft Client ID: " cfg_ms_client_id
        read -sp "Microsoft Client Secret: " cfg_ms_client_secret
        echo ""
        read -p "Microsoft Tenant ID: " cfg_ms_tenant_id
    fi

    if [[ "$cfg_auth_choice" == "1" || "$cfg_auth_choice" == "3" ]]; then
        echo ""
        print_substep "AWS Cognito configuration"
        read -p "Cognito User Pool ID: " cfg_cognito_user_pool_id
        read -p "Cognito Client ID: " cfg_cognito_client_id
        read -sp "Cognito Client Secret: " cfg_cognito_client_secret
        echo ""
        read -p "Cognito Region (blank to use $cfg_region): " cfg_cognito_region
        cfg_cognito_region="${cfg_cognito_region:-$cfg_region}"
    fi

    # --- ACM certificate ARNs ---
    echo ""
    print_substep "ACM certificate configuration"
    echo "Listing certificates..."
    aws acm list-certificates --region "$cfg_region" --output table --no-cli-pager 2>/dev/null || true
    echo ""
    read -p "Frontend ACM Certificate ARN: " cfg_frontend_cert_arn
    read -p "API ACM Certificate ARN: " cfg_api_cert_arn

    # --- Build database URL ---
    local cfg_database_url=""
    if [[ -n "$cfg_rds_endpoint" && -n "$cfg_db_password" && -n "$cfg_rds_database" ]]; then
        cfg_database_url="postgresql+asyncpg://postgres:${cfg_db_password}@${cfg_rds_endpoint}:${cfg_rds_port}/${cfg_rds_database}"
        print_success "Generated database URL"
    else
        echo ""
        read -p "Enter full database URL: " cfg_database_url
    fi

    # --- Cognito domain ---
    echo ""
    read -p "Cognito Domain (e.g. my-app, leave blank to derive from frontend domain): " cfg_cognito_domain
    if [[ -z "$cfg_cognito_domain" ]]; then
        cfg_cognito_domain=$(echo "$cfg_frontend_domain" | tr '.' '-')
        print_info "Derived Cognito domain: $cfg_cognito_domain"
    fi

    # --- Final confirmation ---
    echo ""
    print_header "Configuration Summary"
    echo ""
    echo "=== AWS Configuration ==="
    echo "  AWS Region: $cfg_region"
    echo "  AWS Account ID: $cfg_account_id"
    echo ""
    echo "=== Domain Configuration ==="
    echo "  Frontend Domain: $cfg_frontend_domain"
    echo "  API Domain: $cfg_api_domain"
    echo ""
    echo "=== Database Configuration ==="
    echo "  RDS Endpoint: $cfg_rds_endpoint"
    echo "  RDS Database: $cfg_rds_database"
    echo "  RDS Port: $cfg_rds_port"
    echo ""
    echo "=== Authentication ==="
    if [[ "$cfg_auth_choice" == "1" ]]; then
        echo "  Provider: AWS Cognito only"
    elif [[ "$cfg_auth_choice" == "2" ]]; then
        echo "  Provider: Microsoft Entra ID only"
    else
        echo "  Provider: Both (Cognito + Microsoft)"
    fi
    echo ""
    echo "=== Deployment Environment ==="
    echo "  Environment: $DEPLOY_ENV"
    echo ""

    read -p "Confirm and generate configuration? (yes/no): " confirm_config
    if [[ "$confirm_config" != "yes" ]]; then
        print_error "Configuration cancelled"
        exit 1
    fi

    # --- Push secrets to AWS Secrets Manager ---
    print_substep "Pushing secrets to AWS Secrets Manager..."
    local secret_name="$SECRETS_MANAGER_NAME"
    if [[ -z "$secret_name" ]]; then
        print_error "Secrets Manager name not set"
        exit 1
    fi

    local secret_json
    secret_json=$(jq -n \
      --arg db_url "$cfg_database_url" \
      --arg jwt "$cfg_jwt_secret" \
      --arg ms_client_id "$cfg_ms_client_id" \
      --arg ms_client_secret "$cfg_ms_client_secret" \
      --arg ms_tenant_id "$cfg_ms_tenant_id" \
      --arg cognito_user_pool_id "$cfg_cognito_user_pool_id" \
      --arg cognito_client_id "$cfg_cognito_client_id" \
      --arg cognito_client_secret "$cfg_cognito_client_secret" \
      --arg cognito_region "$cfg_cognito_region" \
      --arg frontend_cert_arn "$cfg_frontend_cert_arn" \
      --arg api_cert_arn "$cfg_api_cert_arn" \
      --arg account_id "$cfg_account_id" \
      --arg region "$cfg_region" \
      '{
        "database-url": $db_url,
        "jwt-secret-key": $jwt,
        "aws-access-key-id": "",
        "aws-secret-access-key": "",
        "microsoft-client-id": $ms_client_id,
        "microsoft-client-secret": $ms_client_secret,
        "microsoft-tenant-id": $ms_tenant_id,
        "cognito-user-pool-id": $cognito_user_pool_id,
        "cognito-client-id": $cognito_client_id,
        "cognito-client-secret": $cognito_client_secret,
        "cognito-region": $cognito_region,
        "acm-certificate-frontend-arn": $frontend_cert_arn,
        "acm-certificate-api-arn": $api_cert_arn,
        "aws-account-id": $account_id,
        "aws-region": $region
      }')

    aws secretsmanager put-secret-value \
      --secret-id "$secret_name" \
      --secret-string "$secret_json" \
      --region "$cfg_region" \
      --no-cli-pager
    print_success "Secrets pushed to AWS Secrets Manager: $secret_name"

    # --- Generate ConfigMaps from templates ---
    print_substep "Generating ConfigMaps..."
    export FRONTEND_DOMAIN="$cfg_frontend_domain"
    export API_DOMAIN="$cfg_api_domain"
    export API_PORT_SUFFIX=""
    export AWS_REGION="$cfg_region"
    export KBR_ENV="$DEPLOY_ENV"
    export SECRETS_MANAGER_SECRET_NAME="$secret_name"
    export COGNITO_DOMAIN="$cfg_cognito_domain"

    envsubst < "$app_dir/backend-configmap.yaml.template" > "$app_dir/backend-configmap.yaml"
    envsubst < "$app_dir/frontend-configmap.yaml.template" > "$app_dir/frontend-configmap.yaml"
    print_success "Generated: backend-configmap.yaml, frontend-configmap.yaml"

    envsubst < "$app_dir/secret-store.yaml.template" > "$app_dir/secret-store.yaml"
    envsubst < "$app_dir/external-secret.yaml.template" > "$app_dir/external-secret.yaml"
    print_success "Generated: secret-store.yaml, external-secret.yaml"

    # --- Generate Ingress files ---
    print_substep "Generating Ingress configuration..."
    cd "$app_dir"
    ./generate-ingress.sh
    print_success "Generated Ingress files"

    echo ""
    print_success "Configuration wizard complete!"
}

# Step 3: Deploy application to EKS
deploy_application() {
    print_step "3" "Deploy Application to EKS"

    print_info "Deployment environment: $DEPLOY_ENV"

    cd "$K8S_DIR"

    # Check and confirm configuration
    print_info "Checking application configuration..."

    local has_config=true
    if [[ ! -f "application/external-secret.yaml" ]]; then
        print_warning "external-secret.yaml not found"
        has_config=false
    fi
    if [[ ! -f "application/backend-configmap.yaml" || ! -f "application/frontend-configmap.yaml" ]]; then
        print_warning "ConfigMaps not found"
        has_config=false
    fi

    if [[ "$has_config" == "true" ]]; then
        print_success "Configuration files found"
        echo ""
        print_warning "Do you want to use existing configuration or regenerate?"
        echo "  y) Use existing configuration (skip wizard)"
        echo "  n) Run configuration wizard to regenerate (default)"
        echo ""
        read -p "Use existing configuration? (y/N): " -n 1 -r
        echo ""
        echo ""

        if [[ $REPLY =~ ^[Yy]$ ]]; then
            print_success "Using existing configuration files"
        else
            print_info "Starting configuration wizard..."
            run_config_wizard
        fi
    else
        print_info "Configuration files missing, starting wizard..."
        run_config_wizard
    fi

    # Generate Deployment and HPA from templates (env-aware resources)
    local app_dir="$K8S_DIR/application"
    print_substep "Generating Deployment and HPA ($DEPLOY_ENV resources)..."
    if [[ "$DEPLOY_ENV" == "prod" ]]; then
        export BACKEND_CPU_REQUEST="200m"  BACKEND_CPU_LIMIT="1000m"
        export BACKEND_MEMORY_REQUEST="512Mi"  BACKEND_MEMORY_LIMIT="1024Mi"
        export FRONTEND_CPU_REQUEST="100m"  FRONTEND_CPU_LIMIT="500m"
        export FRONTEND_MEMORY_REQUEST="256Mi"  FRONTEND_MEMORY_LIMIT="512Mi"
        export BACKEND_HPA_MIN="2"  BACKEND_HPA_MAX="10"
        export FRONTEND_HPA_MIN="2"  FRONTEND_HPA_MAX="5"
    else
        export BACKEND_CPU_REQUEST="100m"  BACKEND_CPU_LIMIT="500m"
        export BACKEND_MEMORY_REQUEST="256Mi"  BACKEND_MEMORY_LIMIT="512Mi"
        export FRONTEND_CPU_REQUEST="50m"  FRONTEND_CPU_LIMIT="200m"
        export FRONTEND_MEMORY_REQUEST="128Mi"  FRONTEND_MEMORY_LIMIT="256Mi"
        export BACKEND_HPA_MIN="1"  BACKEND_HPA_MAX="10"
        export FRONTEND_HPA_MIN="1"  FRONTEND_HPA_MAX="5"
    fi
    envsubst < "$app_dir/backend-deployment.yaml.template" > "$app_dir/backend-deployment.yaml"
    envsubst < "$app_dir/frontend-deployment.yaml.template" > "$app_dir/frontend-deployment.yaml"
    envsubst < "$app_dir/hpa-backend.yaml.template" > "$app_dir/hpa-backend.yaml"
    envsubst < "$app_dir/hpa-frontend.yaml.template" > "$app_dir/hpa-frontend.yaml"
    print_success "Generated: Deployment and HPA files ($DEPLOY_ENV)"

    # Deploy application
    print_substep "Deploying application to Kubernetes..."
    cd "$K8S_DIR"
    if ! ./deploy.sh deploy; then
        print_error "Application deployment failed or was cancelled"
        exit 1
    fi

    print_success "Step 3 complete: Application deployed successfully"

    # Get ALB addresses
    echo ""
    print_info "Waiting for ALB creation..."
    sleep 15

    print_substep "Getting ALB addresses..."
    local frontend_alb=$(kubectl get ingress kolya-br-proxy-frontend -n kbp -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "creating...")
    local api_alb=$(kubectl get ingress kolya-br-proxy-api -n kbp -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "creating...")

    # Wait for ALB
    local max_wait=180
    local waited=0
    while [[ "$frontend_alb" == "creating..." || "$api_alb" == "creating..." ]] && [[ $waited -lt $max_wait ]]; do
        sleep 10
        waited=$((waited + 10))
        frontend_alb=$(kubectl get ingress kolya-br-proxy-frontend -n kbp -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "creating...")
        api_alb=$(kubectl get ingress kolya-br-proxy-api -n kbp -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "creating...")
        print_info "Waiting for ALB... ($waited/$max_wait seconds)"
    done

    echo ""
    print_success "Frontend ALB: $frontend_alb"
    print_success "API ALB: $api_alb"

    if [[ "$frontend_alb" == "creating..." || "$api_alb" == "creating..." ]]; then
        print_warning "ALB creation timed out. Check manually: kubectl get ingress -n kbp"
    else
        echo ""
        print_info "Configure DNS records:"
        echo "  <frontend-domain> → CNAME → $frontend_alb"
        echo "  <api-domain>      → CNAME → $api_alb"
    fi
}

# Show deployment summary
show_deployment_summary() {
    print_header "Deployment Summary"

    echo ""
    print_success "All steps completed!"
    echo ""

    print_info "Cluster: $CLUSTER_NAME"
    print_info "Region: $AWS_REGION"
    print_info "Environment: $DEPLOY_ENV"

    echo ""
    print_info "Management commands:"
    echo "  View status: cd k8s && ./deploy.sh status"
    echo "  View logs:   cd k8s && ./deploy.sh logs"
    echo "  Update app:  cd k8s && ./deploy.sh update"
    echo ""
}

# Main function
main() {
    print_banner

    # Parse arguments
    parse_args "$@"

    # If a specific step is specified
    if [[ -n "$SPECIFIC_STEP" ]]; then
        print_info "Running step $SPECIFIC_STEP"
        echo ""

        # Always collect params (needed for all steps)
        check_dependencies
        check_aws_credentials
        collect_cluster_params

        case $SPECIFIC_STEP in
            1) deploy_k8s_infrastructure ;;
            2) build_and_push_images ;;
            3) deploy_application ;;
        esac

        echo ""
        print_success "Step $SPECIFIC_STEP complete"
        exit 0
    fi

    # Full deployment flow
    print_info "Starting full deployment flow (3 steps)"
    echo ""

    check_dependencies
    check_aws_credentials

    # Collect cluster parameters
    collect_cluster_params

    # Confirm execution
    if [[ "$SKIP_CONFIRMATION" == "false" ]]; then
        echo ""
        print_warning "About to run the full deployment flow:"
        echo "  1. Helm - Kubernetes infrastructure"
        echo "  2. Docker - Build and push images"
        echo "  3. Kubernetes - Deploy application"
        echo ""
        print_warning "This will incur AWS costs!"
        echo ""
        read -p "Confirm to continue? (yes/no): " confirm
        if [[ "$confirm" != "yes" ]]; then
            print_info "Deployment cancelled"
            exit 0
        fi
    fi

    # Execute all steps
    deploy_k8s_infrastructure
    build_and_push_images
    deploy_application

    # Show summary
    show_deployment_summary
}

# Execute main function
main "$@"

#!/bin/bash
#
# Kolya BR Proxy - Docker Build and Push Script
# Build Docker images and push to Amazon ECR
#
# Usage:
#   ./build-and-push.sh                    # Build and push both images
#   ./build-and-push.sh backend            # Build and push backend only
#   ./build-and-push.sh frontend           # Build and push frontend only
#   ./build-and-push.sh --tag v1.2.3       # Use custom tag
#   ./build-and-push.sh --skip-login       # Skip ECR login (if already logged in)

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Default settings
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AWS_REGION="${AWS_REGION:-us-west-2}"
CUSTOM_TAG=""
SKIP_LOGIN=false
BUILD_TARGET="all"  # all, backend, or frontend

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        backend|frontend)
            BUILD_TARGET="$1"
            shift
            ;;
        --tag)
            CUSTOM_TAG="$2"
            shift 2
            ;;
        --region)
            AWS_REGION="$2"
            shift 2
            ;;
        --skip-login)
            SKIP_LOGIN=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [backend|frontend] [--tag TAG] [--region REGION] [--skip-login]"
            echo ""
            echo "Options:"
            echo "  backend          Build and push backend image only"
            echo "  frontend         Build and push frontend image only"
            echo "  --tag TAG        Use custom image tag (default: latest + timestamp)"
            echo "  --region REGION  AWS region (default: us-west-2)"
            echo "  --skip-login     Skip ECR login step"
            echo "  --help           Show this help"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

print_header() {
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
}

print_step() {
    echo -e "${BLUE}▶ $1${NC}"
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

# Get AWS account ID
print_header "Docker Build and Push to ECR"

print_step "Getting AWS account information..."
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)

if [[ -z "$ACCOUNT_ID" ]]; then
    print_error "Failed to get AWS account ID. Please configure AWS credentials."
    echo ""
    echo "Run: aws configure"
    echo "Or set: AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY"
    exit 1
fi

print_success "AWS Account ID: $ACCOUNT_ID"
print_info "Region: $AWS_REGION"

# Generate image tags
TIMESTAMP_TAG="$(date +%Y%m%d-%H%M%S)"
if [[ -n "$CUSTOM_TAG" ]]; then
    TAG="$CUSTOM_TAG"
else
    TAG="latest"
fi

print_info "Image tags: $TAG, $TIMESTAMP_TAG"

# ECR repository base URL
ECR_BASE="$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

# ECR Login
if [[ "$SKIP_LOGIN" == "false" ]]; then
    print_step "Logging in to Amazon ECR..."
    if aws ecr get-login-password --region "$AWS_REGION" | \
        docker login --username AWS --password-stdin "$ECR_BASE" >/dev/null 2>&1; then
        print_success "ECR login successful"
    else
        print_error "ECR login failed"
        exit 1
    fi
else
    print_warning "Skipping ECR login (--skip-login flag set)"
fi

# Function to ensure ECR repository exists
ensure_ecr_repo() {
    local repo_name="$1"

    print_step "Checking ECR repository: $repo_name"

    if aws ecr describe-repositories --repository-names "$repo_name" --region "$AWS_REGION" >/dev/null 2>&1; then
        print_success "Repository exists: $repo_name"
    else
        print_warning "Repository does not exist, creating..."
        if aws ecr create-repository \
            --repository-name "$repo_name" \
            --region "$AWS_REGION" \
            --image-scanning-configuration scanOnPush=true \
            --encryption-configuration encryptionType=AES256 >/dev/null 2>&1; then
            print_success "Repository created: $repo_name"
        else
            print_error "Failed to create repository: $repo_name"
            exit 1
        fi
    fi
}

# Build and push backend
build_backend() {
    local repo_name="kolya-br-proxy-backend"
    local image_latest="$ECR_BASE/$repo_name:$TAG"
    local image_timestamp="$ECR_BASE/$repo_name:$TIMESTAMP_TAG"

    print_header "Building Backend Docker Image"

    ensure_ecr_repo "$repo_name"

    print_step "Building backend image..."
    print_info "Context: $SCRIPT_DIR (Dockerfile: backend/Dockerfile)"

    if docker build -f "$SCRIPT_DIR/backend/Dockerfile" -t "$image_latest" -t "$image_timestamp" "$SCRIPT_DIR" ; then
        print_success "Backend image built successfully"
    else
        print_error "Backend image build failed"
        return 1
    fi

    print_step "Pushing backend image to ECR..."
    print_info "Pushing: $image_latest"

    if docker push "$image_latest"; then
        print_success "Pushed: $image_latest"
    else
        print_error "Failed to push: $image_latest"
        return 1
    fi

    print_info "Pushing: $image_timestamp"
    if docker push "$image_timestamp"; then
        print_success "Pushed: $image_timestamp"
    else
        print_error "Failed to push: $image_timestamp"
        return 1
    fi

    echo ""
    print_success "Backend images pushed successfully"
    print_info "Latest: $image_latest"
    print_info "Tagged: $image_timestamp"
}

# Build and push frontend
build_frontend() {
    local repo_name="kolya-br-proxy-frontend"
    local image_latest="$ECR_BASE/$repo_name:$TAG"
    local image_timestamp="$ECR_BASE/$repo_name:$TIMESTAMP_TAG"

    print_header "Building Frontend Docker Image"

    ensure_ecr_repo "$repo_name"

    print_step "Building frontend image..."
    print_info "Context: $SCRIPT_DIR/frontend"

    cd "$SCRIPT_DIR/frontend"

    if docker build -t "$image_latest" -t "$image_timestamp" . ; then
        print_success "Frontend image built successfully"
    else
        print_error "Frontend image build failed"
        return 1
    fi

    print_step "Pushing frontend image to ECR..."
    print_info "Pushing: $image_latest"

    if docker push "$image_latest"; then
        print_success "Pushed: $image_latest"
    else
        print_error "Failed to push: $image_latest"
        return 1
    fi

    print_info "Pushing: $image_timestamp"
    if docker push "$image_timestamp"; then
        print_success "Pushed: $image_timestamp"
    else
        print_error "Failed to push: $image_timestamp"
        return 1
    fi

    echo ""
    print_success "Frontend images pushed successfully"
    print_info "Latest: $image_latest"
    print_info "Tagged: $image_timestamp"
}

# Execute builds based on target
case $BUILD_TARGET in
    backend)
        build_backend
        ;;
    frontend)
        build_frontend
        ;;
    all)
        build_backend
        echo ""
        build_frontend
        ;;
esac

# Summary
print_header "Build Complete"
print_success "All images built and pushed successfully!"
echo ""
print_info "Next steps:"
echo "  1. Update Kubernetes deployment with new image tags (if not using 'latest')"
echo "  2. Deploy to EKS: cd k8s && ./deploy.sh deploy"
echo "  3. Or run full deployment: ./deploy-all.sh --step 4"
echo ""

#!/bin/bash
#
# Kolya BR Proxy - Destroy Script
# Safely destroy all AWS resources for a specific account and region
#
# Usage:
#   ./destroy.sh                                              # Interactive mode
#   ./destroy.sh --account 123456789012 --region us-west-2    # Specify account and region
#   ./destroy.sh --workspace kolya                            # Specify workspace
#   ./destroy.sh --help                                       # Show help
#

set -e

# Disable AWS CLI pager so commands never block waiting for user input
export AWS_PAGER=""

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
IAC_DIR="$SCRIPT_DIR/iac"

# Variables
# Preserve AWS_REGION from environment (needed for SSO auth to work)
AWS_REGION="${AWS_REGION:-}"
AWS_ACCOUNT_ID=""
TF_WORKSPACE=""

# Path to terraform.tfvars
TFVARS_FILE="$IAC_DIR/terraform.tfvars"

# Read a single value from terraform.tfvars
_read_tfvar() {
    local key="$1"
    if [[ ! -f "$TFVARS_FILE" ]]; then
        echo ""
        return
    fi
    local raw
    raw=$(awk -v k="$key" '$1 == k && $2 == "=" { $1=""; $2=""; sub(/^[[:space:]]+/, ""); print; exit }' "$TFVARS_FILE")
    if [[ "$raw" == \"*\" ]]; then
        raw="${raw#\"}"
        raw="${raw%\"}"
    fi
    echo "$raw"
}

# Write/update a single key-value pair in terraform.tfvars (idempotent)
_write_tfvar() {
    local key="$1"
    local value="$2"
    local type="${3:-string}"

    if [[ ! -f "$TFVARS_FILE" ]]; then
        touch "$TFVARS_FILE"
    fi

    local new_value
    if [[ "$type" == "bare" ]]; then
        new_value="$value"
    else
        new_value="\"${value}\""
    fi

    if grep -qE "^${key}\s*=" "$TFVARS_FILE" 2>/dev/null; then
        local tmpfile
        tmpfile=$(mktemp)
        awk -v k="$key" -v v="$new_value" '
            $1 == k && $2 == "=" { print k " = " v; next }
            { print }
        ' "$TFVARS_FILE" > "$tmpfile" && mv "$tmpfile" "$TFVARS_FILE"
    else
        echo "${key} = ${new_value}" >> "$TFVARS_FILE"
    fi
}

# Print functions
print_banner() {
    echo ""
    echo -e "${RED}╔═══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║                                                               ║${NC}"
    echo -e "${RED}║         Kolya BR Proxy - DESTROY Script                       ║${NC}"
    echo -e "${RED}║         This will PERMANENTLY delete all resources             ║${NC}"
    echo -e "${RED}║                                                               ║${NC}"
    echo -e "${RED}╚═══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

print_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
}

print_substep() { echo -e "${CYAN}  → $1${NC}"; }
print_success() { echo -e "${GREEN}✅ $1${NC}"; }
print_error()   { echo -e "${RED}❌ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
print_info()    { echo -e "${BLUE}ℹ️  $1${NC}"; }

# Show help
show_help() {
    cat << 'EOF'
Kolya BR Proxy - Destroy Script

Usage: ./destroy.sh [options]

Options:
  --account <id>        Specify AWS account ID (highest priority, skips auto-detect)
  --region <region>     Specify AWS region (highest priority, skips auto-detect)
  --workspace <name>    Specify Terraform workspace (skips selection prompt)
  --help                Show this help message

Steps performed:
  1. Verify AWS account and region
  2. Configure Terraform backend (S3 bucket)
  3. Select Terraform workspace
  4. Run terraform destroy

EOF
}

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --account)
                AWS_ACCOUNT_ID="$2"
                shift 2
                ;;
            --region)
                AWS_REGION="$2"
                shift 2
                ;;
            --workspace)
                TF_WORKSPACE="$2"
                shift 2
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

# Verify AWS account and region
verify_aws_identity() {
    print_header "Verifying AWS Identity"

    # 1. Check AWS credentials
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

    # 2. Get account ID
    local detected_account
    detected_account=$(aws sts get-caller-identity --query Account --output text)
    local user_arn
    user_arn=$(aws sts get-caller-identity --query Arn --output text)

    print_success "AWS credentials valid"
    print_info "Detected Account ID: $detected_account"
    print_info "User: $user_arn"

    # 3. Confirm account ID
    if [[ -n "$AWS_ACCOUNT_ID" ]]; then
        # --account was provided, verify it matches current credentials
        if [[ "$AWS_ACCOUNT_ID" != "$detected_account" ]]; then
            print_error "Specified account ($AWS_ACCOUNT_ID) does not match current credentials ($detected_account)"
            print_warning "Please switch to the correct AWS account/profile and re-run."
            echo ""
            echo "Examples:"
            echo "  export AWS_PROFILE=other-profile"
            echo "  aws sso login --profile other-profile"
            exit 1
        fi
        print_success "Account ID matches: $AWS_ACCOUNT_ID"
    else
        echo ""
        read -p "Is this the correct account to destroy resources from? (yes/no): " account_confirm
        if [[ "$account_confirm" != "yes" ]]; then
            print_warning "Please switch to the correct AWS account/profile and re-run."
            echo ""
            echo "Examples:"
            echo "  export AWS_PROFILE=other-profile"
            echo "  aws sso login --profile other-profile"
            exit 0
        fi
        AWS_ACCOUNT_ID="$detected_account"
    fi

    # 4. Determine region
    #    Detect from: --region arg > env $AWS_REGION > aws config
    #    Always let user confirm before proceeding
    if [[ -z "$AWS_REGION" ]]; then
        AWS_REGION="$(aws configure get region 2>/dev/null || echo "")"
    fi

    if [[ -n "$AWS_REGION" ]]; then
        print_info "Detected region: $AWS_REGION"
        read -p "Use this region? (yes/no) [yes]: " use_detected
        use_detected="${use_detected:-yes}"
        if [[ "$use_detected" != "yes" ]]; then
            AWS_REGION=""
        fi
    fi

    while [[ -z "$AWS_REGION" ]]; do
        read -p "Enter AWS region (e.g. us-west-2): " AWS_REGION
        if [[ -z "$AWS_REGION" ]]; then
            print_warning "Region is required"
        fi
    done

    print_info "Region: $AWS_REGION"

    # 5. Determine workspace
    if [[ -n "$TF_WORKSPACE" ]]; then
        print_info "Workspace from --workspace: $TF_WORKSPACE"
        read -p "Use this workspace? (yes/no) [yes]: " use_ws
        use_ws="${use_ws:-yes}"
        if [[ "$use_ws" != "yes" ]]; then
            TF_WORKSPACE=""
        fi
    fi

    while [[ -z "$TF_WORKSPACE" ]]; do
        read -p "Enter Terraform workspace name (e.g. kolya, prod): " TF_WORKSPACE
        if [[ -z "$TF_WORKSPACE" ]]; then
            print_warning "Workspace is required"
        fi
    done

    print_info "Workspace: $TF_WORKSPACE"

    # 6. Summary confirmation
    echo ""
    echo -e "${RED}════════════════════════════════════════════════════${NC}"
    echo -e "${RED}  DESTROY TARGET${NC}"
    echo -e "${RED}  Account:   $AWS_ACCOUNT_ID${NC}"
    echo -e "${RED}  Region:    $AWS_REGION${NC}"
    echo -e "${RED}  Workspace: $TF_WORKSPACE${NC}"
    echo -e "${RED}  User:      $user_arn${NC}"
    echo -e "${RED}════════════════════════════════════════════════════${NC}"
    echo ""
}

# Disable WAF and Global Accelerator via Terraform BEFORE deleting K8s/ALBs.
# These modules have data "aws_lb" lookups that fail if ALBs are gone.
disable_waf_and_ga() {
    print_header "Pre-cleanup: Disable WAF & Global Accelerator"

    cd "$IAC_DIR"

    local needs_apply=false

    # Check if WAF is enabled
    if terraform state list 2>/dev/null | grep -q "module.waf"; then
        print_substep "WAF is enabled, disabling..."
        _write_tfvar "enable_waf" "false" "bare"
        needs_apply=true
    else
        print_info "WAF not in state, skipping"
    fi

    # Check if GA is enabled
    if terraform state list 2>/dev/null | grep -q "module.global_accelerator"; then
        print_substep "Global Accelerator is enabled, disabling..."
        _write_tfvar "enable_global_accelerator" "false" "bare"
        needs_apply=true
    else
        print_info "Global Accelerator not in state, skipping"
    fi

    if [[ "$needs_apply" == "true" ]]; then
        print_substep "Applying Terraform to remove WAF/GA (so ALBs can be safely deleted)..."
        if terraform apply -auto-approve; then
            print_success "WAF/GA removed successfully"
        else
            print_warning "Terraform apply failed. Attempting state removal as fallback..."
            # Fallback: remove from state directly so destroy doesn't try to read ALBs
            terraform state rm 'module.waf' 2>/dev/null || true
            terraform state rm 'module.global_accelerator' 2>/dev/null || true
            print_warning "Removed WAF/GA from state. Some AWS resources may need manual cleanup."
        fi
    else
        print_success "WAF and GA already disabled, nothing to do"
    fi
}

# Check if EKS cluster exists and clean up k8s resources if so
cleanup_k8s_resources() {
    print_header "Checking EKS Cluster"

    local NAMESPACE="kbp"
    # Derive cluster name from project_name_alias (same pattern as main.tf)
    local alias
    alias=$(_read_tfvar "project_name_alias")
    alias="${alias:-kbr-proxy}"
    local CLUSTER_NAME="${alias}-eks-${AWS_REGION}-${TF_WORKSPACE}"

    # Check if EKS cluster exists
    print_substep "Checking for EKS cluster: $CLUSTER_NAME ..."
    if ! aws eks describe-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" &> /dev/null; then
        print_info "EKS cluster '$CLUSTER_NAME' does not exist, skipping k8s cleanup"
        return 0
    fi

    print_success "EKS cluster found: $CLUSTER_NAME"

    # Check if kubectl is available
    if ! command -v kubectl &> /dev/null; then
        print_error "kubectl not found. Must clean up k8s resources before destroying infrastructure."
        print_info "Install kubectl: https://kubernetes.io/docs/tasks/tools/"
        exit 1
    fi

    # Update kubeconfig to connect to the cluster
    print_substep "Connecting to EKS cluster..."
    if ! aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION" &> /dev/null; then
        print_error "Failed to connect to EKS cluster"
        exit 1
    fi
    print_success "Connected to cluster: $CLUSTER_NAME"

    # Verify cluster is reachable
    if ! kubectl cluster-info &> /dev/null 2>&1; then
        print_error "Cannot reach Kubernetes API. Must clean up k8s resources before destroying infrastructure."
        exit 1
    fi

    # Check if namespace exists
    if ! kubectl get namespace "$NAMESPACE" &> /dev/null 2>&1; then
        print_info "Namespace '$NAMESPACE' does not exist, nothing to clean up"
        return 0
    fi

    print_header "Cleaning Up Kubernetes Resources"

    print_info "Namespace: $NAMESPACE"
    print_info "Cluster: $CLUSTER_NAME"
    echo ""

    # Show what will be deleted
    print_substep "Resources in namespace '$NAMESPACE':"
    kubectl get all -n "$NAMESPACE" 2>/dev/null || true
    echo ""
    kubectl get ingress -n "$NAMESPACE" 2>/dev/null || true
    echo ""
    kubectl get externalsecret,secretstore,clustersecretstore -n "$NAMESPACE" 2>/dev/null || true
    echo ""

    read -p "Delete all resources in namespace '$NAMESPACE'? (yes/no): " confirm_k8s
    if [[ "$confirm_k8s" != "yes" ]]; then
        print_error "Must clean up k8s resources before destroying infrastructure (ALB/target groups will block Terraform)."
        exit 1
    fi

    # Delete ingress first (triggers ALB deletion)
    print_substep "Deleting Ingress resources (triggers ALB cleanup)..."
    kubectl delete ingress --all -n "$NAMESPACE" --ignore-not-found=true
    print_success "Ingress resources deleted"

    # Wait for ALB to be cleaned up
    print_substep "Waiting for ALB cleanup (30s)..."
    sleep 30

    # Delete ExternalSecrets and SecretStore
    print_substep "Deleting External Secrets resources..."
    kubectl delete externalsecret --all -n "$NAMESPACE" --ignore-not-found=true
    kubectl delete secretstore --all -n "$NAMESPACE" --ignore-not-found=true
    print_success "External Secrets resources deleted"

    # Delete remaining resources
    print_substep "Deleting remaining resources..."
    kubectl delete all --all -n "$NAMESPACE" --ignore-not-found=true
    kubectl delete configmap --all -n "$NAMESPACE" --ignore-not-found=true
    kubectl delete secret --all -n "$NAMESPACE" --ignore-not-found=true
    kubectl delete hpa --all -n "$NAMESPACE" --ignore-not-found=true
    print_success "All resources in namespace deleted"

    # Delete namespace
    print_substep "Deleting namespace '$NAMESPACE'..."
    kubectl delete namespace "$NAMESPACE" --ignore-not-found=true

    # Wait for namespace deletion
    print_substep "Waiting for namespace deletion..."
    local wait_count=0
    local max_wait=60
    while [[ $wait_count -lt $max_wait ]]; do
        if ! kubectl get namespace "$NAMESPACE" &> /dev/null 2>&1; then
            break
        fi
        sleep 2
        ((wait_count+=2))
    done

    if kubectl get namespace "$NAMESPACE" &> /dev/null 2>&1; then
        print_warning "Namespace still terminating, proceeding anyway"
    else
        print_success "Namespace '$NAMESPACE' deleted"
    fi

    echo ""
    print_success "Kubernetes resources cleanup complete"
}

# Initialize Terraform backend and select workspace (shared by disable_waf_and_ga + destroy)
init_terraform() {
    print_header "Terraform Initialization"

    cd "$IAC_DIR"

    # 1. Handle providers.tf (backend config)
    local backend_changed=false
    if [[ -f "$IAC_DIR/providers.tf" ]]; then
        print_info "Existing providers.tf found"
        read -p "Reconfigure Terraform backend? (yes/no) [no]: " reconfigure
        reconfigure="${reconfigure:-no}"
        if [[ "$reconfigure" == "yes" ]]; then
            rm -f "$IAC_DIR/providers.tf"
            backend_changed=true
        fi
    else
        backend_changed=true
    fi

    if [[ "$backend_changed" == "true" ]]; then
        print_substep "Configuring Terraform S3 backend..."
        if [[ ! -f "$IAC_DIR/providers.tf.template" ]]; then
            print_error "providers.tf.template not found in $IAC_DIR"
            exit 1
        fi

        echo ""
        print_info "Terraform remote state requires the S3 bucket where state is stored."
        echo ""

        local tf_state_bucket=""
        while [[ -z "$tf_state_bucket" ]]; do
            read -p "S3 bucket name for Terraform state: " tf_state_bucket
            if [[ -z "$tf_state_bucket" ]]; then
                print_warning "Bucket name is required"
            fi
        done

        local tf_state_region="$AWS_REGION"

        local tf_state_key="kolya-br-proxy/tf.state"

        export TF_STATE_BUCKET="$tf_state_bucket"
        export TF_STATE_REGION="$tf_state_region"
        export TF_STATE_KEY="$tf_state_key"
        envsubst '${TF_STATE_BUCKET} ${TF_STATE_REGION} ${TF_STATE_KEY}' < "$IAC_DIR/providers.tf.template" > "$IAC_DIR/providers.tf"
        print_success "providers.tf generated (bucket: $tf_state_bucket, region: $tf_state_region)"
    fi

    # 2. Terraform init
    print_substep "Initializing Terraform..."
    local init_flags="-upgrade"
    if [[ "$backend_changed" == "true" ]]; then
        init_flags="-reconfigure -upgrade"
        print_info "Backend changed, running init with -reconfigure"
    fi
    if ! terraform init $init_flags; then
        print_error "Terraform init failed"
        exit 1
    fi
    print_success "Terraform initialized"

    # 3. Verify workspace exists
    print_substep "Verifying workspace '$TF_WORKSPACE'..."
    local current_workspace
    current_workspace=$(terraform workspace show 2>/dev/null || echo "default")

    if ! terraform workspace list | grep -q "^[* ]*${TF_WORKSPACE}$"; then
        print_error "Workspace '$TF_WORKSPACE' does not exist in this backend"
        print_info "Available workspaces:"
        terraform workspace list
        exit 1
    fi
    print_success "Workspace '$TF_WORKSPACE' exists"

    if [[ "$TF_WORKSPACE" != "$current_workspace" ]]; then
        print_substep "Switching to workspace: $TF_WORKSPACE"
        terraform workspace select "$TF_WORKSPACE"
        print_success "Switched to workspace: $TF_WORKSPACE"
    fi

    # 4. Ensure account/region are in tfvars
    _write_tfvar "account" "$AWS_ACCOUNT_ID"
    _write_tfvar "region" "$AWS_REGION"
}

# Destroy remaining Terraform resources
run_terraform_destroy() {
    print_header "Terraform Destroy"

    cd "$IAC_DIR"

    # Show plan for destroy
    print_substep "Generating destroy plan..."
    echo ""
    if ! terraform plan -destroy; then
        print_error "Terraform destroy plan failed"
        exit 1
    fi

    # Final confirmation
    echo ""
    echo -e "${RED}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${RED}  WARNING: This will PERMANENTLY destroy all resources!${NC}"
    echo -e "${RED}  Account:   $AWS_ACCOUNT_ID${NC}"
    echo -e "${RED}  Region:    $AWS_REGION${NC}"
    echo -e "${RED}  Workspace: $TF_WORKSPACE${NC}"
    echo -e "${RED}════════════════════════════════════════════════════════════════${NC}"
    echo ""
    read -p "Type 'destroy' to confirm: " destroy_confirm
    if [[ "$destroy_confirm" != "destroy" ]]; then
        print_info "Destroy cancelled"
        exit 0
    fi

    # Execute destroy
    print_substep "Destroying resources..."
    if ! terraform destroy -auto-approve; then
        print_error "Terraform destroy failed"
        exit 1
    fi

    echo ""
    print_success "All resources destroyed successfully"
    print_info "Account: $AWS_ACCOUNT_ID"
    print_info "Region: $AWS_REGION"
    print_info "Workspace: $TF_WORKSPACE"
}

# Main
main() {
    parse_args "$@"
    print_banner
    verify_aws_identity
    init_terraform              # Init backend + select workspace (needed by all subsequent steps)
    disable_waf_and_ga          # Terraform apply to remove WAF/GA (their data sources need ALBs alive)
    cleanup_k8s_resources       # Delete K8s resources (Ingress → ALBs get destroyed here)
    run_terraform_destroy       # Destroy remaining infrastructure
}

main "$@"

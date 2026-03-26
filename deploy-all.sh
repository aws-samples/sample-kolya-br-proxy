#!/bin/bash
#
# Kolya BR Proxy - Unified Deployment Script
# One-click deployment of the complete application stack
#
# Deployment flow:
#   1. Deploy AWS infrastructure (Terraform)
#   2. Deploy Kubernetes infrastructure (Helm: ALB Controller, Karpenter, Metrics Server)
#   3. Build Docker images and push to ECR
#   4. Deploy application to EKS (Frontend & Backend)
#
# Usage:
#   ./deploy-all.sh                # Interactive full deployment
#   ./deploy-all.sh --step 1       # Run step 1 only (Terraform)
#   ./deploy-all.sh --step 2       # Run step 2 only (Helm)
#   ./deploy-all.sh --step 3       # Run step 3 only (Docker build)
#   ./deploy-all.sh --step 4       # Run step 4 only (App deployment)
#   ./deploy-all.sh --help         # Show help

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
K8S_DIR="$SCRIPT_DIR/k8s"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# Default configuration
SKIP_CONFIRMATION=false
SPECIFIC_STEP=""
AWS_REGION="${AWS_REGION:-$(aws configure get region 2>/dev/null || echo "")}"
AWS_ACCOUNT_ID=""
ECR_NAMESPACE="kolya-br-proxy"
DEPLOY_ENV=""  # Auto-derived from Terraform workspace: prod or non-prod

# Path to terraform.tfvars
TFVARS_FILE="$IAC_DIR/terraform.tfvars"

# Read a single value from terraform.tfvars
# Usage: _read_tfvar "key"
# Returns the raw value with outer quotes stripped. For list/map values returns empty.
_read_tfvar() {
    local key="$1"
    if [[ ! -f "$TFVARS_FILE" ]]; then
        echo ""
        return
    fi
    # Extract the value part after "key = ", skip list/map values (starting with [ or {)
    local raw
    raw=$(awk -v k="$key" '$1 == k && $2 == "=" { $1=""; $2=""; sub(/^[[:space:]]+/, ""); print; exit }' "$TFVARS_FILE")
    # Strip outer quotes if present (handles exactly one pair)
    if [[ "$raw" == \"*\" ]]; then
        raw="${raw#\"}"
        raw="${raw%\"}"
    fi
    echo "$raw"
}

# Write/update a single key-value pair in terraform.tfvars (idempotent)
# Usage: _write_tfvar "key" "value" ["string"|"bare"]
#   "string" (default) wraps value in quotes; "bare" writes as-is (for bool/number)
_write_tfvar() {
    local key="$1"
    local value="$2"
    local type="${3:-string}"

    # Ensure tfvars file exists
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
        # Update existing line using awk (avoids sed escaping issues)
        local tmpfile
        tmpfile=$(mktemp)
        awk -v k="$key" -v v="$new_value" '
            $1 == k && $2 == "=" { print k " = " v; next }
            { print }
        ' "$TFVARS_FILE" > "$tmpfile" && mv "$tmpfile" "$TFVARS_FILE"
    else
        # Append new line
        echo "${key} = ${new_value}" >> "$TFVARS_FILE"
    fi
}

# Safely read a terraform output value.
# Returns empty string if the output doesn't exist or contains warnings/errors.
# Usage: _tf_output "output_name"
_tf_output() {
    local name="$1"
    local val
    val=$(terraform output -raw "$name" 2>/dev/null) || return 1
    # Reject if it contains ANSI codes, newlines, or warning markers (terraform outputs
    # warnings to stdout with exit 0 when state has no outputs)
    if [[ "$val" == *$'\n'* || "$val" == *$'\033'* || "$val" == *"Warning:"* || "$val" == *"Error:"* ]]; then
        echo ""
        return 1
    fi
    echo "$val"
}

# Detect whether a terraform module is present in state (for bool toggles)
# Usage: _detect_bool_from_state "module_name"  →  prints "true" or "false"
_detect_bool_from_state() {
    local module_name="$1"
    cd "$IAC_DIR"
    if terraform state list 2>/dev/null | grep -q "module.${module_name}"; then
        echo "true"
    else
        echo "false"
    fi
}

# Step 0: Configure terraform.tfvars as single source of truth
configure_tfvars() {
    print_header "Step 0: Configure terraform.tfvars"

    cd "$IAC_DIR"

    # 1. Auto-detect account and region
    print_substep "Auto-detecting AWS account and region..."
    local detected_account
    detected_account=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")
    local detected_region="${AWS_REGION:-$(aws configure get region 2>/dev/null || echo "")}"

    if [[ -n "$detected_account" ]]; then
        _write_tfvar "account" "$detected_account"
        print_success "account = $detected_account"
    fi
    if [[ -n "$detected_region" ]]; then
        _write_tfvar "region" "$detected_region"
        print_success "region = $detected_region"
    fi

    # 2. Auto-detect boolean toggles from terraform state
    print_substep "Detecting feature flags from Terraform state..."
    if [[ -d "$IAC_DIR/.terraform" ]]; then
        local detected_waf
        detected_waf=$(_detect_bool_from_state "waf")
        _write_tfvar "enable_waf" "$detected_waf" "bare"
        print_success "enable_waf = $detected_waf (from state)"

        local detected_ga
        detected_ga=$(_detect_bool_from_state "global_accelerator")
        _write_tfvar "enable_global_accelerator" "$detected_ga" "bare"
        print_success "enable_global_accelerator = $detected_ga (from state)"

    else
        print_warning "Terraform not initialized, skipping state detection"
    fi

    # 2b. Authentication provider selection (always prompt, show current value as default)
    local current_cognito
    current_cognito=$(_read_tfvar "enable_cognito")
    echo ""
    print_substep "Authentication provider"
    if [[ "$current_cognito" == "true" ]]; then
        echo "  Current: Cognito enabled"
        echo ""
        echo "  1) AWS Cognito (current)"
        echo "  2) Microsoft Entra ID only (disable Cognito)"
        echo "  3) Both (Cognito + Microsoft)"
        read -p "Select authentication method [1]: " auth_choice
        auth_choice="${auth_choice:-1}"
    elif [[ "$current_cognito" == "false" ]]; then
        echo "  Current: Cognito disabled (Microsoft only)"
        echo ""
        echo "  1) Microsoft Entra ID only (current)"
        echo "  2) AWS Cognito"
        echo "  3) Both (Cognito + Microsoft)"
        read -p "Select authentication method [1]: " auth_choice
        auth_choice="${auth_choice:-1}"
        # Remap: 1=keep false, 2=cognito, 3=both
        case "$auth_choice" in
            1) auth_choice="microsoft" ;;
            2) auth_choice="1" ;;
            3) auth_choice="3" ;;
            *) auth_choice="microsoft" ;;
        esac
    else
        echo "  1) AWS Cognito (recommended for new deployments)"
        echo "  2) Microsoft Entra ID only (no Cognito)"
        echo "  3) Both (Cognito + Microsoft)"
        read -p "Select authentication method [1]: " auth_choice
        auth_choice="${auth_choice:-1}"
    fi
    case "$auth_choice" in
        1)
            _write_tfvar "enable_cognito" "true" "bare"
            print_success "enable_cognito = true"
            ;;
        2|microsoft)
            _write_tfvar "enable_cognito" "false" "bare"
            print_success "enable_cognito = false (Microsoft only)"
            ;;
        3)
            _write_tfvar "enable_cognito" "true" "bare"
            print_success "enable_cognito = true (+ Microsoft via Secrets Manager)"
            ;;
        *)
            # Keep current or default to Cognito
            if [[ "$current_cognito" == "false" ]]; then
                _write_tfvar "enable_cognito" "false" "bare"
                print_success "enable_cognito = false (kept current)"
            else
                _write_tfvar "enable_cognito" "true" "bare"
                print_success "enable_cognito = true"
            fi
            ;;
    esac

    # 3. Confirm/input: frontend_domain, api_domain
    echo ""
    print_substep "Domain configuration"

    local existing_fe_domain
    existing_fe_domain=$(_read_tfvar "frontend_domain")
    local existing_api_domain
    existing_api_domain=$(_read_tfvar "api_domain")

    local input_fe_domain
    if [[ -n "$existing_fe_domain" ]]; then
        read -p "Frontend domain [$existing_fe_domain]: " input_fe_domain
        input_fe_domain="${input_fe_domain:-$existing_fe_domain}"
    else
        while [[ -z "$input_fe_domain" ]]; do
            read -p "Frontend domain (e.g. kbp.kolya.fun): " input_fe_domain
            if [[ -z "$input_fe_domain" ]]; then
                print_warning "Frontend domain is required"
            fi
        done
    fi
    _write_tfvar "frontend_domain" "$input_fe_domain"

    local input_api_domain
    if [[ -n "$existing_api_domain" ]]; then
        read -p "API domain [$existing_api_domain]: " input_api_domain
        input_api_domain="${input_api_domain:-$existing_api_domain}"
    else
        while [[ -z "$input_api_domain" ]]; do
            read -p "API domain (e.g. api.kbp.kolya.fun): " input_api_domain
            if [[ -z "$input_api_domain" ]]; then
                print_warning "API domain is required"
            fi
        done
    fi
    _write_tfvar "api_domain" "$input_api_domain"

    # 4. Auto-detect project naming (critical: embedded in all resource names)
    #    project_name       → deployment_name ("kolya-br-proxy-kolya"), VPC name_prefix, tags
    #    project_name_alias → cluster_name ("kbr-proxy-eks-us-west-1-kolya"), Karpenter, RDS, WAF, Cognito
    echo ""
    print_substep "Project naming detection"

    # --- project_name ---
    local detected_name=""
    local name_source=""
    detected_name=$(_read_tfvar "project_name")
    if [[ -n "$detected_name" ]]; then
        name_source="tfvars"
    fi
    # Derive from deployment tag in state (pattern: ${project_name}-${workspace})
    if [[ -z "$detected_name" && -d "$IAC_DIR/.terraform" ]]; then
        local vpc_id_from_state
        vpc_id_from_state=$(_tf_output vpc_id || echo "")
        if [[ -n "$vpc_id_from_state" ]]; then
            local deployment_tag
            deployment_tag=$(aws ec2 describe-vpcs --vpc-ids "$vpc_id_from_state" \
                --query 'Vpcs[0].Tags[?Key==`DeploymentName`].Value' --output text \
                --region "${detected_region:-$AWS_REGION}" 2>/dev/null || echo "")
            if [[ -n "$deployment_tag" ]]; then
                # deployment_name format: ${project_name}-${workspace}
                local ws
                ws=$(terraform workspace show 2>/dev/null || echo "")
                if [[ -n "$ws" ]]; then
                    detected_name="${deployment_tag%-"$ws"}"
                    name_source="state (DeploymentName tag)"
                fi
            fi
        fi
    fi

    if [[ -n "$detected_name" ]]; then
        print_success "project_name = $detected_name (from $name_source)"
        print_warning "Used in VPC/deployment naming. Cannot be changed safely after initial deploy."
        _write_tfvar "project_name" "$detected_name"
    else
        print_warning "Could not auto-detect project_name from tfvars or terraform state."
        print_warning "This value is used in VPC naming, deployment tags, and other resources."
        print_warning "Entering the wrong value will cause resource conflicts!"
        local input_name=""
        while [[ -z "$input_name" ]]; do
            read -p "Project name (e.g. kolya-br-proxy): " input_name
            if [[ -z "$input_name" ]]; then
                print_warning "This field is required."
            fi
        done
        _write_tfvar "project_name" "$input_name"
    fi

    # --- project_name_alias ---
    local detected_alias=""
    local alias_source=""
    detected_alias=$(_read_tfvar "project_name_alias")
    if [[ -n "$detected_alias" ]]; then
        alias_source="tfvars"
    fi
    # Derive from EKS cluster name in terraform state (pattern: ${alias}-eks-${region}-${workspace})
    if [[ -z "$detected_alias" && -d "$IAC_DIR/.terraform" ]]; then
        local cluster_name_from_state
        cluster_name_from_state=$(_tf_output cluster_name || echo "")
        if [[ -n "$cluster_name_from_state" ]]; then
            detected_alias=$(echo "$cluster_name_from_state" | sed 's/-eks-.*//')
            alias_source="state (cluster_name)"
        fi
    fi

    if [[ -n "$detected_alias" ]]; then
        print_success "project_name_alias = $detected_alias (from $alias_source)"
        print_warning "Used in EKS cluster, Karpenter, RDS, WAF, Cognito naming. Cannot be changed safely."
        _write_tfvar "project_name_alias" "$detected_alias"
    else
        print_warning "Could not auto-detect project_name_alias from tfvars or terraform state."
        print_warning "This value is embedded in EKS cluster name, Karpenter, RDS, WAF, Cognito."
        print_warning "Entering the wrong value will cause resource conflicts!"
        local input_alias=""
        while [[ -z "$input_alias" ]]; do
            read -p "Project name alias (e.g. kbr-proxy): " input_alias
            if [[ -z "$input_alias" ]]; then
                print_warning "This field is required."
            fi
        done
        _write_tfvar "project_name_alias" "$input_alias"
    fi

    local existing_email_domains
    existing_email_domains=$(_read_tfvar "cognito_allowed_email_domains")
    if [[ -n "$existing_email_domains" ]]; then
        print_info "cognito_allowed_email_domains = $existing_email_domains (keeping existing)"
    else
        read -p "Cognito allowed email domains (e.g. example.com) [amazon.com]: " input_email_domains
        input_email_domains="${input_email_domains:-amazon.com}"
        # Write as HCL list - need special handling
        if ! grep -qE "^cognito_allowed_email_domains\s*=" "$TFVARS_FILE" 2>/dev/null; then
            echo "cognito_allowed_email_domains = [\"${input_email_domains}\"]" >> "$TFVARS_FILE"
        fi
    fi

    # 5. Export for subsequent steps
    export FRONTEND_DOMAIN="$input_fe_domain"
    export API_DOMAIN="$input_api_domain"

    echo ""
    print_substep "Current terraform.tfvars:"
    cat "$TFVARS_FILE"
    echo ""
    print_success "Step 0 complete: terraform.tfvars configured"
}

# Create Cognito admin user (extracted from setup_cognito_post_terraform)
create_cognito_admin_user() {
    cd "$IAC_DIR"

    local cognito_enabled
    cognito_enabled=$(_tf_output cognito_enabled || echo "false")
    if [[ "$cognito_enabled" != "true" ]]; then
        return 0
    fi

    local pool_id
    pool_id=$(_tf_output cognito_user_pool_id || echo "")
    local cognito_region
    cognito_region=$(_tf_output region || echo "$AWS_REGION")

    if [[ -z "$pool_id" ]]; then
        print_warning "Could not retrieve Cognito User Pool ID. Skipping admin user creation."
        return 0
    fi

    # Check if any users exist
    local user_count
    user_count=$(aws cognito-idp list-users --user-pool-id "$pool_id" --region "$cognito_region" --query 'Users | length(@)' --output text 2>/dev/null || echo "0")

    if [[ "$user_count" -gt 0 ]]; then
        print_info "Cognito user pool already has $user_count user(s), skipping admin creation"
        return 0
    fi

    print_substep "Cognito user pool is empty. Creating initial admin user..."
    echo ""
    local admin_email=""
    while [[ -z "$admin_email" ]]; do
        read -p "Admin email: " admin_email
        if [[ -z "$admin_email" ]]; then
            print_warning "This field is required."
        fi
    done

    local admin_username="${admin_email%%@*}"

    if aws cognito-idp admin-create-user \
        --user-pool-id "$pool_id" \
        --username "$admin_username" \
        --user-attributes Name=email,Value="$admin_email" Name=email_verified,Value=true \
        --desired-delivery-mediums EMAIL \
        --region "$cognito_region" \
        --no-cli-pager &> /dev/null; then
        print_success "Admin user created (username: $admin_username). Temporary password sent to $admin_email"
    else
        print_error "Failed to create admin user. Create manually:"
        echo "  aws cognito-idp admin-create-user \\"
        echo "    --user-pool-id $pool_id \\"
        echo "    --username $admin_username \\"
        echo "    --user-attributes Name=email,Value=$admin_email Name=email_verified,Value=true \\"
        echo "    --desired-delivery-mediums EMAIL \\"
        echo "    --region $cognito_region"
    fi
}

# Generate k8s config files (non-interactive, from tfvars + terraform outputs)
generate_k8s_configs() {
    local app_dir="$K8S_DIR/application"

    print_substep "Generating k8s configuration files..."

    # Read domains from tfvars
    local cfg_frontend_domain
    cfg_frontend_domain=$(_read_tfvar "frontend_domain")
    local cfg_api_domain
    cfg_api_domain=$(_read_tfvar "api_domain")

    if [[ -z "$cfg_frontend_domain" || -z "$cfg_api_domain" ]]; then
        print_error "frontend_domain or api_domain not set in terraform.tfvars. Run Step 0 first."
        exit 1
    fi

    cd "$IAC_DIR"

    local cfg_region
    cfg_region=$(_tf_output region || echo "$AWS_REGION")
    local cfg_secrets_manager_name
    cfg_secrets_manager_name=$(_tf_output backend_secrets_manager_name || echo "")

    if [[ -z "$cfg_secrets_manager_name" ]]; then
        print_error "Secrets Manager name not found in Terraform outputs. Run Step 1 first."
        exit 1
    fi

    # If DEPLOY_ENV not set, derive from workspace
    if [[ -z "$DEPLOY_ENV" ]]; then
        detect_environment
    fi

    export FRONTEND_DOMAIN="$cfg_frontend_domain"
    export API_DOMAIN="$cfg_api_domain"
    export API_PORT_SUFFIX=""
    export AWS_REGION="$cfg_region"
    export KBR_ENV="$DEPLOY_ENV"
    export SECRETS_MANAGER_SECRET_NAME="$cfg_secrets_manager_name"

    # Get COGNITO_DOMAIN from Terraform output (only relevant when Cognito is enabled)
    export COGNITO_DOMAIN=""
    local cognito_flag
    cognito_flag=$(_read_tfvar "enable_cognito")
    if [[ "$cognito_flag" == "true" ]]; then
        COGNITO_DOMAIN=$(_tf_output cognito_domain || echo "")
        if [[ -z "$COGNITO_DOMAIN" ]]; then
            COGNITO_DOMAIN=$(echo "$cfg_frontend_domain" | tr '.' '-')
            print_warning "Could not get Cognito domain from Terraform, using derived: $COGNITO_DOMAIN"
        fi
    fi

    envsubst < "$app_dir/backend-configmap.yaml.template" > "$app_dir/backend-configmap.yaml"
    envsubst < "$app_dir/frontend-configmap.yaml.template" > "$app_dir/frontend-configmap.yaml"
    print_success "Generated: backend-configmap.yaml, frontend-configmap.yaml"

    envsubst < "$app_dir/secret-store.yaml.template" > "$app_dir/secret-store.yaml"
    envsubst < "$app_dir/external-secret.yaml.template" > "$app_dir/external-secret.yaml"
    print_success "Generated: secret-store.yaml, external-secret.yaml"

    print_info "Ingress will be auto-generated during deploy (depends on ESO secret sync)"
}

# Push secrets to AWS Secrets Manager
push_secrets_to_sm() {
    cd "$IAC_DIR"

    local cfg_region
    cfg_region=$(_tf_output region || echo "$AWS_REGION")
    local secret_name
    secret_name=$(_tf_output backend_secrets_manager_name || echo "")

    if [[ -z "$secret_name" ]]; then
        print_error "Secrets Manager name not found. Run Step 1 first."
        exit 1
    fi

    # Read domains from tfvars
    local cfg_frontend_domain
    cfg_frontend_domain=$(_read_tfvar "frontend_domain")
    local cfg_api_domain
    cfg_api_domain=$(_read_tfvar "api_domain")

    local cfg_account_id
    cfg_account_id=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")

    # Retrieve RDS password
    local cfg_rds_endpoint
    cfg_rds_endpoint=$(_tf_output rds_cluster_endpoint || echo "")
    local cfg_rds_database
    cfg_rds_database=$(_tf_output rds_cluster_database_name || echo "")
    local cfg_rds_port
    cfg_rds_port=$(_tf_output rds_cluster_port || echo "5432")

    local cfg_db_password=""
    local rds_secret_name
    rds_secret_name=$(_tf_output rds_secret_name || echo "")
    if [[ -n "$rds_secret_name" ]]; then
        cfg_db_password=$(aws secretsmanager get-secret-value --secret-id "$rds_secret_name" --query SecretString --output text 2>/dev/null | jq -r '.password' 2>/dev/null || echo "")
    fi

    local cfg_database_url=""
    if [[ -n "$cfg_rds_endpoint" && -n "$cfg_db_password" && -n "$cfg_rds_database" ]]; then
        cfg_database_url="postgresql+asyncpg://postgres:${cfg_db_password}@${cfg_rds_endpoint}:${cfg_rds_port}/${cfg_rds_database}"
    fi

    # JWT secret - generate if not already in SM
    local existing_jwt=""
    existing_jwt=$(aws secretsmanager get-secret-value --secret-id "$secret_name" --query SecretString --output text 2>/dev/null | jq -r '."jwt-secret-key" // empty' 2>/dev/null || echo "")
    local cfg_jwt_secret="${existing_jwt}"
    if [[ -z "$cfg_jwt_secret" ]]; then
        cfg_jwt_secret=$(openssl rand -base64 32)
        print_info "Generated new JWT secret"
    fi

    # Cognito config from terraform outputs
    local cfg_cognito_user_pool_id=""
    local cfg_cognito_client_id=""
    local cfg_cognito_client_secret=""
    local cfg_cognito_region="$cfg_region"
    local cognito_enabled
    cognito_enabled=$(_tf_output cognito_enabled || echo "false")
    if [[ "$cognito_enabled" == "true" ]]; then
        cfg_cognito_user_pool_id=$(_tf_output cognito_user_pool_id || echo "")
        cfg_cognito_client_id=$(_tf_output cognito_app_client_id || echo "")
        cfg_cognito_client_secret=$(_tf_output cognito_app_client_secret || echo "")
    fi

    # Read existing MS config from SM (preserve if present)
    local cfg_ms_client_id=""
    local cfg_ms_client_secret=""
    local cfg_ms_tenant_id=""
    cfg_ms_client_id=$(aws secretsmanager get-secret-value --secret-id "$secret_name" --query SecretString --output text 2>/dev/null | jq -r '."microsoft-client-id" // empty' 2>/dev/null || echo "")
    cfg_ms_client_secret=$(aws secretsmanager get-secret-value --secret-id "$secret_name" --query SecretString --output text 2>/dev/null | jq -r '."microsoft-client-secret" // empty' 2>/dev/null || echo "")
    cfg_ms_tenant_id=$(aws secretsmanager get-secret-value --secret-id "$secret_name" --query SecretString --output text 2>/dev/null | jq -r '."microsoft-tenant-id" // empty' 2>/dev/null || echo "")

    # Read existing cert ARNs from SM (preserve if present)
    local cfg_frontend_cert_arn=""
    local cfg_api_cert_arn=""
    cfg_frontend_cert_arn=$(aws secretsmanager get-secret-value --secret-id "$secret_name" --query SecretString --output text 2>/dev/null | jq -r '."acm-certificate-frontend-arn" // empty' 2>/dev/null || echo "")
    cfg_api_cert_arn=$(aws secretsmanager get-secret-value --secret-id "$secret_name" --query SecretString --output text 2>/dev/null | jq -r '."acm-certificate-api-arn" // empty' 2>/dev/null || echo "")

    # If cert ARNs are missing, ask user
    if [[ -z "$cfg_frontend_cert_arn" || -z "$cfg_api_cert_arn" ]]; then
        echo ""
        print_substep "ACM certificate configuration"
        aws acm list-certificates --region "${cfg_region}" --output table --no-cli-pager 2>/dev/null || true
        echo ""
        read -p "Frontend ACM Certificate ARN: " cfg_frontend_cert_arn
        read -p "API ACM Certificate ARN: " cfg_api_cert_arn
    fi

    print_substep "Pushing secrets to AWS Secrets Manager..."
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
}

# Print functions
print_banner() {
    echo ""
    echo -e "${CYAN}╔═══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║                                                               ║${NC}"
    echo -e "${CYAN}║         Kolya BR Proxy - Unified Deployment Script            ║${NC}"
    echo -e "${CYAN}║         Complete Deployment Automation                        ║${NC}"
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
    echo -e "${MAGENTA}▶ Step $1/5: $2${NC}"
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
    cat << EOF
Kolya BR Proxy - Unified Deployment Script

Usage: ./deploy-all.sh [options]

Options:
  --step <0-5>        Run a specific step only
                      0: Configure terraform.tfvars (single source of truth)
                      1: Deploy Terraform infrastructure
                      2: Deploy Kubernetes infrastructure (Helm)
                      3: Build and push Docker images
                      4: Deploy application to EKS
                      5: Toggle Global Accelerator (enable/disable)

  --yes               Skip all confirmation prompts (dangerous!)
  --region <region>   Specify AWS region (default: us-west-2)
  --help              Show this help message

Examples:
  # Full deployment (interactive)
  ./deploy-all.sh

  # Deploy infrastructure only
  ./deploy-all.sh --step 1

  # Build and push images only
  ./deploy-all.sh --step 3

  # Full deployment (skip confirmations)
  ./deploy-all.sh --yes

Deployment flow:
  1️⃣  Terraform - Deploy AWS infrastructure
     • VPC, Subnets, Security Groups
     • EKS Cluster
     • RDS Aurora PostgreSQL
     • IAM Roles and Policies

  2️⃣  Helm - Deploy Kubernetes infrastructure
     • AWS Load Balancer Controller
     • Karpenter (Auto-scaling)
     • Metrics Server
     • Karpenter Node Configuration

  3️⃣  Docker - Build and push images
     • Backend Docker image
     • Frontend Docker image
     • Push to Amazon ECR

  4️⃣  Kubernetes - Deploy application
     • Backend Deployment
     • Frontend Deployment
     • Services, Ingress, HPA
     • Create ALB

More info: See README.md
EOF
}

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --step)
                SPECIFIC_STEP="$2"
                if [[ ! "$SPECIFIC_STEP" =~ ^[0-5]$ ]]; then
                    print_error "Invalid step number: $SPECIFIC_STEP (must be 0-5)"
                    exit 1
                fi
                shift 2
                ;;
            --yes)
                SKIP_CONFIRMATION=true
                shift
                ;;
            --region)
                AWS_REGION="$2"
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

# Check dependencies
check_dependencies() {
    print_header "Checking Dependencies"

    local missing_deps=()

    # Check required tools
    local required_tools=(
        "terraform:Terraform:https://www.terraform.io/downloads"
        "kubectl:Kubectl:https://kubernetes.io/docs/tasks/tools/"
        "helm:Helm:https://helm.sh/docs/intro/install/"
        "aws:AWS CLI:https://aws.amazon.com/cli/"
        "docker:Docker:https://docs.docker.com/get-docker/"
        "jq:jq:brew install jq"
    )

    for tool_info in "${required_tools[@]}"; do
        IFS=':' read -r cmd name url <<< "$tool_info"
        print_substep "Checking $name..."
        if ! command -v "$cmd" &> /dev/null; then
            missing_deps+=("$name ($url)")
            print_error "$name not installed"
        else
            local version=""
            case $cmd in
                terraform) version=$(terraform version | head -1) ;;
                kubectl) version=$(kubectl version --client --short 2>/dev/null | head -1) ;;
                helm) version=$(helm version --short 2>/dev/null) ;;
                aws) version=$(aws --version 2>&1 | cut -d' ' -f1) ;;
                docker) version=$(docker --version 2>/dev/null | cut -d' ' -f3 | tr -d ',') ;;
                jq) version=$(jq --version 2>/dev/null) ;;
            esac
            print_success "$name installed ($version)"
        fi
    done

    if [ ${#missing_deps[@]} -ne 0 ]; then
        echo ""
        print_error "Missing dependencies:"
        for dep in "${missing_deps[@]}"; do
            echo "  • $dep"
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

    AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    local user_arn=$(aws sts get-caller-identity --query Arn --output text)

    print_success "AWS credentials valid"
    print_info "Account ID: $AWS_ACCOUNT_ID"
    print_info "User: $user_arn"

    # Prompt for region if auto-detection failed and --region was not provided
    if [[ -z "$AWS_REGION" ]]; then
        print_warning "AWS region could not be detected automatically"
        while [[ -z "$AWS_REGION" ]]; do
            read -p "Enter AWS region (e.g. us-west-2): " AWS_REGION
            if [[ -z "$AWS_REGION" ]]; then
                print_warning "Region is required"
            fi
        done
    fi

    print_info "Region: $AWS_REGION"
}

# Verify Terraform backend state is correct
# Call this before any step that reads terraform output (step 2, 4, etc.)
verify_terraform_state() {
    print_header "Verifying Terraform State"

    cd "$IAC_DIR"

    local need_configure=false

    # Check if providers.tf exists
    if [[ ! -f "$IAC_DIR/providers.tf" ]]; then
        print_warning "providers.tf not found, need to configure Terraform backend"
        need_configure=true
    else
        # Show current backend config and let user confirm
        local current_bucket=$(grep 'bucket' "$IAC_DIR/providers.tf" | head -1 | sed 's/.*= *"\(.*\)"/\1/')
        local current_region=$(grep 'region' "$IAC_DIR/providers.tf" | head -1 | sed 's/.*= *"\(.*\)"/\1/')
        local current_key=$(grep 'key' "$IAC_DIR/providers.tf" | head -1 | sed 's/.*= *"\(.*\)"/\1/')

        echo ""
        print_info "Current Terraform backend configuration:"
        echo "  Bucket: $current_bucket"
        echo "  Region: $current_region"
        echo "  Key:    $current_key"
        echo ""

        read -p "Is this the correct state backend? (yes/no): " state_confirm
        if [[ "$state_confirm" != "yes" ]]; then
            need_configure=true
            rm -f "$IAC_DIR/providers.tf"
        fi
    fi

    if [[ "$need_configure" == "true" ]]; then
        print_substep "Configuring Terraform S3 backend..."

        if [[ ! -f "$IAC_DIR/providers.tf.template" ]]; then
            print_error "providers.tf.template not found in $IAC_DIR"
            exit 1
        fi

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

        print_substep "Initializing Terraform..."
        if ! terraform init -reconfigure -upgrade; then
            print_error "Terraform init failed"
            exit 1
        fi
        print_success "Terraform initialized"
    else
        # Ensure terraform is initialized
        if [[ ! -d "$IAC_DIR/.terraform" ]]; then
            print_substep "Initializing Terraform..."
            if ! terraform init -upgrade; then
                print_error "Terraform init failed"
                exit 1
            fi
            print_success "Terraform initialized"
        fi
    fi

    # Verify and confirm workspace
    local current_workspace=$(terraform workspace show 2>/dev/null || echo "default")
    print_info "Current Terraform workspace: $current_workspace"

    read -p "Use workspace '$current_workspace'? (yes/no) [yes]: " ws_confirm
    ws_confirm="${ws_confirm:-yes}"
    if [[ "$ws_confirm" != "yes" ]]; then
        # Show available workspaces
        print_substep "Available workspaces:"
        terraform workspace list
        echo ""
        local new_ws=""
        while [[ -z "$new_ws" ]]; do
            read -p "Enter workspace name: " new_ws
            if [[ -z "$new_ws" ]]; then
                print_warning "Workspace name is required"
            fi
        done
        if ! terraform workspace list | grep -q "^[* ]*${new_ws}$"; then
            print_error "Workspace '$new_ws' does not exist"
            exit 1
        fi
        terraform workspace select "$new_ws"
        print_success "Switched to workspace: $new_ws"
    fi

    # Verify state has resources
    local state_count=$(terraform state list 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$state_count" == "0" ]]; then
        print_warning "Terraform state is empty for current workspace ($(terraform workspace show))"
        print_info "This may mean you need to switch workspace or the state backend is incorrect"
    else
        print_success "Terraform state verified ($state_count resources)"
    fi
}

# Step 1: Deploy Terraform
deploy_terraform() {
    print_step "1" "Deploy AWS Infrastructure (Terraform)"

    cd "$IAC_DIR"

    # --- Backend & Init (must happen before any workspace operations) ---

    # Generate providers.tf from template if it doesn't exist
    local backend_changed=false
    if [[ ! -f "$IAC_DIR/providers.tf" ]]; then
        backend_changed=true
        print_substep "Configuring Terraform S3 backend..."
        if [[ ! -f "$IAC_DIR/providers.tf.template" ]]; then
            print_error "providers.tf.template not found in $IAC_DIR"
            exit 1
        fi

        echo ""
        print_info "Terraform remote state requires an S3 bucket."
        print_info "Please create the bucket first if it doesn't exist."
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

    # Terraform init (use -reconfigure when backend config just changed)
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

    # --- Workspace selection (requires initialized backend) ---

    print_substep "Checking Terraform workspace..."
    local current_workspace=$(terraform workspace show 2>/dev/null || echo "default")

    # Get all available workspaces
    local workspaces=($(terraform workspace list | sed 's/\*//g' | tr -d ' '))

    # Show current workspace
    print_info "Current Terraform workspace: $current_workspace"

    # Show available workspaces with numbers
    echo ""
    print_substep "Available Terraform workspaces:"
    local i=1
    for ws in "${workspaces[@]}"; do
        if [[ "$ws" == "$current_workspace" ]]; then
            echo "  $i) $ws (current)"
        else
            echo "  $i) $ws"
        fi
        ((i++))
    done
    echo "  $i) Enter custom workspace name"

    # Ask user to select
    echo ""
    read -p "Select workspace [1-$i, or press Enter to use current]: " ws_choice

    local selected_workspace="$current_workspace"

    if [[ -n "$ws_choice" ]]; then
        if [[ "$ws_choice" =~ ^[0-9]+$ ]]; then
            if [[ "$ws_choice" -eq "$i" ]]; then
                # User chose to enter custom name
                read -p "Enter workspace name: " custom_workspace
                if [[ -z "$custom_workspace" ]]; then
                    print_error "Workspace name cannot be empty"
                    exit 1
                fi
                selected_workspace="$custom_workspace"

                # Check if workspace exists, create if not
                if ! terraform workspace list | grep -q "^[* ]*${selected_workspace}$"; then
                    print_warning "Workspace '$selected_workspace' does not exist"
                    read -p "Create new workspace '$selected_workspace'? (yes/no): " create_confirm
                    if [[ "$create_confirm" == "yes" ]]; then
                        terraform workspace new "$selected_workspace"
                        print_success "Workspace '$selected_workspace' created"
                    else
                        print_info "Deployment cancelled"
                        exit 0
                    fi
                fi
            elif [[ "$ws_choice" -ge 1 && "$ws_choice" -lt "$i" ]]; then
                # User selected an existing workspace
                selected_workspace="${workspaces[$((ws_choice-1))]}"
            else
                print_error "Invalid selection: $ws_choice"
                exit 1
            fi
        else
            print_error "Invalid input: $ws_choice (must be a number)"
            exit 1
        fi
    fi

    # Switch to selected workspace if different from current
    if [[ "$selected_workspace" != "$current_workspace" ]]; then
        print_substep "Switching to workspace: $selected_workspace"
        terraform workspace select "$selected_workspace"
        print_success "Switched to workspace: $selected_workspace"
    fi

    # Update current workspace variable
    current_workspace="$selected_workspace"

    # Environment auto-derived: workspace == "prod" -> prod, otherwise non-prod
    if [[ "$current_workspace" == "prod" ]]; then
        DEPLOY_ENV="prod"
        print_info "Deployment environment: PRODUCTION"
    else
        DEPLOY_ENV="non-prod"
        print_info "Deployment environment: NON-PRODUCTION"
    fi

    # Final confirmation
    echo ""
    print_warning "You are about to deploy to workspace: $current_workspace ($DEPLOY_ENV)"
    read -p "Confirm deployment? (yes/no): " ws_confirm
    if [[ "$ws_confirm" != "yes" ]]; then
        echo ""
        print_info "Deployment cancelled"
        exit 0
    fi

    # Ensure account/region are in tfvars
    if [[ -n "$AWS_ACCOUNT_ID" ]]; then
        _write_tfvar "account" "$AWS_ACCOUNT_ID"
    fi
    if [[ -n "$AWS_REGION" ]]; then
        _write_tfvar "region" "$AWS_REGION"
    fi

    # Terraform plan
    print_substep "Generating Terraform execution plan..."
    if ! terraform plan -out=tfplan; then
        print_error "Terraform plan failed"
        exit 1
    fi
    print_success "Execution plan generated"

    # Confirm apply
    if [[ "$SKIP_CONFIRMATION" == "false" ]]; then
        echo ""
        print_warning "About to deploy AWS infrastructure, this will incur costs"
        read -p "Confirm Terraform apply? (yes/no): " confirm
        if [[ "$confirm" != "yes" ]]; then
            print_info "Deployment cancelled"
            exit 0
        fi
    fi

    # Terraform apply
    print_substep "Deploying infrastructure..."
    if ! terraform apply tfplan; then
        print_error "Terraform apply failed"
        exit 1
    fi

    # Clean up plan file
    rm -f tfplan

    print_success "Step 1 complete: AWS infrastructure deployed successfully"

    # Show outputs
    echo ""
    print_info "Fetching Terraform outputs..."
    terraform output

    # Optionally create initial Cognito admin user (first-time deploy)
    create_cognito_admin_user
}

# Step 2: Deploy Kubernetes infrastructure
deploy_k8s_infrastructure() {
    print_step "2" "Deploy Kubernetes Infrastructure (Helm)"

    # Verify terraform state before reading outputs
    verify_terraform_state

    # Configure kubectl
    print_substep "Configuring kubectl..."
    cd "$IAC_DIR"
    local cluster_name=$(_tf_output cluster_name || echo "")

    if [[ -z "$cluster_name" ]]; then
        print_error "Cannot get cluster name, please complete step 1 first"
        exit 1
    fi

    aws eks update-kubeconfig --name "$cluster_name" --region "$AWS_REGION"
    print_success "kubectl configured"

    # Verify connection
    print_substep "Verifying cluster connection..."
    if ! kubectl cluster-info &> /dev/null; then
        print_error "Cannot connect to EKS cluster"
        exit 1
    fi
    print_success "Cluster connection OK"

    # Authenticate to ECR Public for Karpenter
    print_substep "Authenticating to ECR Public..."
    if aws ecr-public get-login-password --region us-east-1 | helm registry login --username AWS --password-stdin public.ecr.aws 2>/dev/null; then
        print_success "ECR Public authentication successful"
    else
        print_warning "ECR Public authentication failed, trying docker login..."
        if aws ecr-public get-login-password --region us-east-1 | docker login --username AWS --password-stdin public.ecr.aws 2>/dev/null; then
            print_success "ECR Public authentication successful (via docker)"
        else
            print_error "ECR Public authentication failed"
            print_info "Karpenter installation may fail. Please run manually:"
            echo "  aws ecr-public get-login-password --region us-east-1 | helm registry login --username AWS --password-stdin public.ecr.aws"
        fi
    fi

    # Install Helm charts
    print_substep "Installing Kubernetes infrastructure components..."
    cd "$K8S_DIR/infrastructure/helm-installations"

    # Generate Helm values
    print_substep "Generating Helm values..."
    ./generate-values.sh "$IAC_DIR"

    # Install components
    print_substep "Installing Helm charts..."
    ./install.sh

    print_success "Step 2 complete: Kubernetes infrastructure deployed successfully"
}

# Step 3: Build and push Docker images
build_and_push_images() {
    print_step "3" "Build and Push Docker Images to ECR"

    cd "$IAC_DIR"

    # Get AWS account ID
    print_substep "Getting AWS account info..."
    local account_id=$(aws sts get-caller-identity --query Account --output text)
    print_info "AWS Account ID: $account_id"

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

    # Collect domain names for frontend build args (VITE_* are compiled at build time)
    local fe_domain="${FRONTEND_DOMAIN:-$(_read_tfvar "frontend_domain")}"
    local api_domain="${API_DOMAIN:-$(_read_tfvar "api_domain")}"
    if [[ -z "$fe_domain" || -z "$api_domain" ]]; then
        print_error "frontend_domain or api_domain not set. Run './deploy-all.sh --step 0' first."
        exit 1
    fi
    print_info "Frontend build args: API=https://$api_domain, Frontend=$fe_domain"

    if ! docker build --network host --platform linux/arm64 \
        --build-arg VITE_API_BASE_URL="https://$api_domain" \
        --build-arg VITE_MICROSOFT_REDIRECT_URI="https://$fe_domain/auth/microsoft/callback" \
        --build-arg VITE_COGNITO_REDIRECT_URI="https://$fe_domain/auth/cognito/callback" \
        -t "$frontend_image" -t "$frontend_tag" .; then
        print_error "Frontend image build failed"
        exit 1
    fi
    print_success "Frontend image built"

    print_substep "Pushing Frontend image to ECR..."
    docker push "$frontend_image"
    docker push "$frontend_tag"
    print_success "Frontend image pushed"

    print_success "Step 3 complete: Docker images built and pushed"

    echo ""
    print_info "Image info:"
    echo "  Backend:  $backend_image"
    echo "  Frontend: $frontend_image"
}

# Derive environment from Terraform workspace
detect_environment() {
    cd "$IAC_DIR"
    local current_workspace=$(terraform workspace show 2>/dev/null || echo "default")
    if [[ "$current_workspace" == "prod" ]]; then
        DEPLOY_ENV="prod"
    else
        DEPLOY_ENV="non-prod"
    fi
}

# Step 4: Deploy application to EKS
deploy_application() {
    print_step "4" "Deploy Application to EKS"

    # Verify terraform state before reading outputs (used by config wizard)
    verify_terraform_state

    # If DEPLOY_ENV not set (single step execution), derive from workspace
    if [[ -z "$DEPLOY_ENV" ]]; then
        detect_environment
    fi
    print_info "Deployment environment: $DEPLOY_ENV"

    cd "$K8S_DIR"

    # Generate k8s configs from tfvars (non-interactive)
    generate_k8s_configs

    # Push secrets if not yet present
    local secret_name
    secret_name=$(cd "$IAC_DIR" && _tf_output backend_secrets_manager_name || echo "")
    if [[ -n "$secret_name" ]]; then
        local existing_secret
        existing_secret=$(aws secretsmanager get-secret-value --secret-id "$secret_name" --query SecretString --output text 2>/dev/null || echo "")
        if [[ -z "$existing_secret" || "$existing_secret" == "{}" ]]; then
            print_info "Secrets Manager is empty, pushing secrets..."
            push_secrets_to_sm
        else
            print_success "Secrets already present in Secrets Manager"
        fi
    fi

    # Always generate Deployment and HPA from templates (env-aware resources)
    local app_dir="$K8S_DIR/application"
    export AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
    export AWS_REGION
    print_substep "Generating Deployment and HPA ($DEPLOY_ENV resources)..."
    if [[ "$DEPLOY_ENV" == "prod" ]]; then
        export BACKEND_CPU_REQUEST="500m"  BACKEND_CPU_LIMIT="1000m"
        export BACKEND_MEMORY_REQUEST="512Mi"  BACKEND_MEMORY_LIMIT="1024Mi"
        export FRONTEND_CPU_REQUEST="50m"  FRONTEND_CPU_LIMIT="200m"
        export FRONTEND_MEMORY_REQUEST="128Mi"  FRONTEND_MEMORY_LIMIT="256Mi"
        export BACKEND_HPA_MIN="2"  BACKEND_HPA_MAX="8"
        export FRONTEND_HPA_MIN="1"  FRONTEND_HPA_MAX="2"
    else
        export BACKEND_CPU_REQUEST="250m"  BACKEND_CPU_LIMIT="500m"
        export BACKEND_MEMORY_REQUEST="384Mi"  BACKEND_MEMORY_LIMIT="768Mi"
        export FRONTEND_CPU_REQUEST="30m"  FRONTEND_CPU_LIMIT="100m"
        export FRONTEND_MEMORY_REQUEST="64Mi"  FRONTEND_MEMORY_LIMIT="128Mi"
        export BACKEND_HPA_MIN="1"  BACKEND_HPA_MAX="5"
        export FRONTEND_HPA_MIN="1"  FRONTEND_HPA_MAX="2"
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

    print_success "Step 4 complete: Application deployed successfully"

    # Get ALB addresses
    echo ""
    print_info "Waiting for ALB creation (this may take a few minutes)..."
    sleep 15

    print_substep "Getting ALB addresses..."
    local frontend_alb=$(kubectl get ingress kolya-br-proxy-frontend -n kbp -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "creating...")
    local api_alb=$(kubectl get ingress kolya-br-proxy-api -n kbp -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "creating...")

    # Wait for ALB to be ready if still creating
    local max_wait=180  # 3 minutes
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
        print_warning "ALB creation timed out. Please check manually:"
        echo "  kubectl get ingress -n kbp"
        print_warning "Skipping WAF auto-enable (ALBs not ready)"
        return 0
    fi

    # Auto-enable WAF now that ALBs are ready
    print_substep "Auto-enabling WAF (ALBs are ready)..."
    cd "$IAC_DIR"
    _write_tfvar "enable_waf" "true" "bare"
    if terraform apply -target=module.waf -auto-approve; then
        print_success "WAF enabled successfully"
    else
        print_warning "WAF auto-enable failed. You can retry manually:"
        echo "  cd $IAC_DIR && terraform apply -target=module.waf -auto-approve"
    fi

    # Get domain names from tfvars
    local frontend_domain
    frontend_domain=$(_read_tfvar "frontend_domain")
    local api_domain
    api_domain=$(_read_tfvar "api_domain")

    if [[ -z "$frontend_domain" || -z "$api_domain" ]]; then
        print_warning "Could not determine domain names from configmaps"
        print_info "Manual DNS configuration required:"
        echo "  <your-frontend-domain> → CNAME → $frontend_alb"
        echo "  <your-api-domain>      → CNAME → $api_alb"
        return 0
    fi

    # Try to update DNS automatically
    echo ""
    print_header "DNS Configuration"

    # Check if domains are in Route53
    print_substep "Checking if domains are managed in Route53..."
    local frontend_zone_id=$(aws route53 list-hosted-zones-by-name --query "HostedZones[?Name=='${frontend_domain#*.}.'].Id" --output text 2>/dev/null | cut -d'/' -f3)
    local api_zone_id=$(aws route53 list-hosted-zones-by-name --query "HostedZones[?Name=='${api_domain#*.}.'].Id" --output text 2>/dev/null | cut -d'/' -f3)

    if [[ -n "$frontend_zone_id" && -n "$api_zone_id" ]]; then
        print_success "Domains found in Route53"
        print_info "Frontend zone: $frontend_zone_id"
        print_info "API zone: $api_zone_id"

        echo ""
        print_warning "Do you want to automatically update DNS records in Route53?"
        echo "  This will create/update CNAME records:"
        echo "    $frontend_domain → $frontend_alb"
        echo "    $api_domain      → $api_alb"
        echo ""
        read -p "Update DNS automatically? (yes/no): " update_dns

        if [[ "$update_dns" == "yes" ]]; then
            print_substep "Updating DNS records..."

            # Update frontend CNAME
            local frontend_change_batch=$(cat <<EOF
{
  "Changes": [{
    "Action": "UPSERT",
    "ResourceRecordSet": {
      "Name": "$frontend_domain",
      "Type": "CNAME",
      "TTL": 300,
      "ResourceRecords": [{"Value": "$frontend_alb"}]
    }
  }]
}
EOF
)
            if aws route53 change-resource-record-sets \
                --hosted-zone-id "$frontend_zone_id" \
                --change-batch "$frontend_change_batch" \
                --output text &> /dev/null; then
                print_success "Updated: $frontend_domain → $frontend_alb"
            else
                print_error "Failed to update frontend DNS record"
            fi

            # Update API CNAME
            local api_change_batch=$(cat <<EOF
{
  "Changes": [{
    "Action": "UPSERT",
    "ResourceRecordSet": {
      "Name": "$api_domain",
      "Type": "CNAME",
      "TTL": 300,
      "ResourceRecords": [{"Value": "$api_alb"}]
    }
  }]
}
EOF
)
            if aws route53 change-resource-record-sets \
                --hosted-zone-id "$api_zone_id" \
                --change-batch "$api_change_batch" \
                --output text &> /dev/null; then
                print_success "Updated: $api_domain → $api_alb"
            else
                print_error "Failed to update API DNS record"
            fi

            echo ""
            print_success "DNS records updated successfully!"
            print_info "DNS propagation may take a few minutes"
            print_info "You can check with: dig $frontend_domain"
        else
            print_info "Skipped automatic DNS update"
            echo ""
            print_info "Manual DNS configuration required:"
            echo "  $frontend_domain → CNAME → $frontend_alb"
            echo "  $api_domain      → CNAME → $api_alb"
        fi
    else
        print_warning "Domains not found in Route53 (or different hosted zones)"
        echo ""
        print_info "Manual DNS configuration required:"
        echo "  $frontend_domain → CNAME → $frontend_alb"
        echo "  $api_domain      → CNAME → $api_alb"
    fi
}

# Helper: read current config values from tfvars and terraform outputs
_read_configmap_env_vars() {
    export FRONTEND_DOMAIN=$(_read_tfvar "frontend_domain")
    export API_DOMAIN=$(_read_tfvar "api_domain")

    # These still come from cluster configmaps or terraform outputs as fallback
    export KBR_ENV=$(kubectl get configmap backend-config -n kbp -o jsonpath='{.data.KBR_ENV}' 2>/dev/null)
    export AWS_REGION="${AWS_REGION:-$(kubectl get configmap backend-config -n kbp -o jsonpath='{.data.KBR_AWS_REGION}' 2>/dev/null)}"
    export COGNITO_DOMAIN=$(kubectl get configmap backend-config -n kbp -o jsonpath='{.data.KBR_COGNITO_DOMAIN}' 2>/dev/null)

    if [[ -z "$FRONTEND_DOMAIN" || -z "$API_DOMAIN" ]]; then
        return 1
    fi
    return 0
}

# Helper: regenerate configmaps, apply, and restart pods
_regenerate_and_apply_configmaps() {
    local port_suffix="$1"  # ":8443" or ""
    local app_dir="$K8S_DIR/application"

    if ! _read_configmap_env_vars; then
        print_warning "Could not read current configmap values. Please regenerate configmaps manually."
        print_info "Set API_PORT_SUFFIX='$port_suffix' and re-run: envsubst < template > configmap"
        return 1
    fi

    export API_PORT_SUFFIX="$port_suffix"

    envsubst < "$app_dir/backend-configmap.yaml.template" > "$app_dir/backend-configmap.yaml"
    envsubst < "$app_dir/frontend-configmap.yaml.template" > "$app_dir/frontend-configmap.yaml"

    if [[ -n "$port_suffix" ]]; then
        print_success "Regenerated configmaps with API port 8443"
    else
        print_success "Regenerated configmaps with default API port (443)"
    fi

    kubectl apply -f "$app_dir/backend-configmap.yaml" -f "$app_dir/frontend-configmap.yaml"
    kubectl rollout restart deployment/backend deployment/frontend -n kbp
    print_info "Waiting for pods to restart..."
    kubectl rollout status deployment/backend -n kbp --timeout=120s || true
    kubectl rollout status deployment/frontend -n kbp --timeout=120s || true
    print_success "Pods restarted with updated configmaps"
}

# Step 5: Toggle Global Accelerator (enable/disable)
deploy_global_accelerator() {
    print_step "5" "Global Accelerator (Toggle)"

    # Verify terraform state before reading outputs
    verify_terraform_state

    cd "$IAC_DIR"

    # Detect current GA status from terraform state
    local ga_currently_enabled=false
    local ga_dns=$(_tf_output global_accelerator_dns_name || echo "")
    if [[ -n "$ga_dns" && "$ga_dns" != "" ]]; then
        ga_currently_enabled=true
    fi

    if [[ "$ga_currently_enabled" == "true" ]]; then
        print_info "Global Accelerator is currently: ENABLED"
        print_info "DNS: $ga_dns"
        echo ""
        echo "  1) Disable Global Accelerator"
        echo "  2) Cancel (keep current state)"
        echo ""
        read -p "Select [1/2]: " ga_choice
        ga_choice="${ga_choice:-2}"

        if [[ "$ga_choice" != "1" ]]; then
            print_info "Keeping Global Accelerator enabled, no changes made"
            return 0
        fi

        # --- Disable GA ---
        print_header "Disabling Global Accelerator"

        # Write to tfvars (WAF state is already persisted there)
        _write_tfvar "enable_global_accelerator" "false" "bare"

        # Terraform plan & apply
        print_substep "Running Terraform to destroy Global Accelerator..."
        terraform plan -out=tfplan-ga
        if [[ $? -ne 0 ]]; then
            print_error "Terraform plan failed"
            rm -f tfplan-ga
            exit 1
        fi

        echo ""
        read -p "Apply the plan above? (yes/no): " confirm_apply
        if [[ "$confirm_apply" != "yes" ]]; then
            print_info "Terraform apply cancelled"
            rm -f tfplan-ga
            return 0
        fi

        if ! terraform apply tfplan-ga; then
            print_error "Terraform apply failed"
            rm -f tfplan-ga
            exit 1
        fi
        rm -f tfplan-ga

        print_success "Global Accelerator destroyed"

        # Regenerate configmaps without port suffix
        echo ""
        print_substep "Updating configmaps (removing API port 8443)..."
        _regenerate_and_apply_configmaps ""

        # Show DNS instructions
        echo ""
        local frontend_alb=$(kubectl get ingress kolya-br-proxy-frontend -n kbp -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "<frontend-alb>")
        local api_alb=$(kubectl get ingress kolya-br-proxy-api -n kbp -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "<api-alb>")

        print_warning "Next steps - Update DNS records to point back to ALBs:"
        echo "  kbp.kolya.fun      → CNAME $frontend_alb"
        echo "  api.kbp.kolya.fun  → CNAME $api_alb"
        echo ""
        print_success "Step 5 complete: Global Accelerator disabled"

    else
        print_info "Global Accelerator is currently: DISABLED"
        echo ""

        # Verify ALBs exist
        print_substep "Verifying ALBs exist..."
        local ga_frontend_alb_name=$(_tf_output ga_frontend_alb_name || echo "kolya-br-proxy-frontend-alb")
        local ga_api_alb_name=$(_tf_output ga_api_alb_name || echo "kolya-br-proxy-api-alb")
        local ga_region=$(_tf_output region || echo "$AWS_REGION")
        local frontend_alb_arn=$(aws elbv2 describe-load-balancers \
            --names "$ga_frontend_alb_name" \
            --region "$ga_region" \
            --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || echo "")
        local api_alb_arn=$(aws elbv2 describe-load-balancers \
            --names "$ga_api_alb_name" \
            --region "$ga_region" \
            --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || echo "")

        if [[ -z "$frontend_alb_arn" || "$frontend_alb_arn" == "None" ]]; then
            print_error "Frontend ALB ($ga_frontend_alb_name) not found. Run Steps 1-4 first."
            exit 1
        fi
        if [[ -z "$api_alb_arn" || "$api_alb_arn" == "None" ]]; then
            print_error "API ALB ($ga_api_alb_name) not found. Run Steps 1-4 first."
            exit 1
        fi
        print_success "Frontend ALB: $frontend_alb_arn"
        print_success "API ALB: $api_alb_arn"

        # Confirm enable
        echo ""
        print_warning "Global Accelerator incurs additional cost (~\$19.50/month)."
        print_info "It routes traffic over the AWS backbone network, reducing latency for distant users."
        echo ""
        read -p "Enable Global Accelerator? (yes/no): " confirm_ga
        if [[ "$confirm_ga" != "yes" ]]; then
            print_info "Global Accelerator setup cancelled"
            return 0
        fi

        # --- Enable GA ---
        print_substep "Running Terraform to create Global Accelerator..."

        local current_workspace=$(terraform workspace show 2>/dev/null || echo "default")
        print_info "Terraform workspace: $current_workspace"

        # Write to tfvars (WAF state is already persisted there)
        _write_tfvar "enable_global_accelerator" "true" "bare"

        terraform plan -out=tfplan-ga
        if [[ $? -ne 0 ]]; then
            print_error "Terraform plan failed"
            rm -f tfplan-ga
            exit 1
        fi

        echo ""
        read -p "Apply the plan above? (yes/no): " confirm_apply
        if [[ "$confirm_apply" != "yes" ]]; then
            print_info "Terraform apply cancelled"
            rm -f tfplan-ga
            return 0
        fi

        if ! terraform apply tfplan-ga; then
            print_error "Terraform apply failed"
            rm -f tfplan-ga
            exit 1
        fi
        rm -f tfplan-ga

        # Show results
        echo ""
        ga_dns=$(_tf_output global_accelerator_dns_name || echo "N/A")
        local ga_ips=$(terraform output -json global_accelerator_static_ips 2>/dev/null || echo "[]")

        print_success "Global Accelerator deployed!"
        echo ""
        print_info "Global Accelerator DNS: $ga_dns"
        print_info "Static IPs: $ga_ips"
        echo ""
        print_info "Port mappings:"
        echo "  Frontend HTTPS: 443 → ALB:443"
        echo "  Frontend HTTP:  80  → ALB:80"
        echo "  API HTTPS:      8443 → ALB:443"
        echo "  API HTTP:       8080 → ALB:80"
        echo ""

        # Regenerate configmaps with port 8443
        print_substep "Updating configmaps for Global Accelerator (API port 8443)..."
        _regenerate_and_apply_configmaps ":8443"

        echo ""
        print_warning "Next steps - Update DNS records:"
        echo "  kbp.kolya.fun      → CNAME $ga_dns"
        echo "  api.kbp.kolya.fun  → CNAME $ga_dns (clients use port 8443 for HTTPS)"
        echo ""
        print_success "Step 5 complete: Global Accelerator enabled"
    fi
}

# Show deployment summary
show_deployment_summary() {
    print_header "Deployment Summary"

    cd "$IAC_DIR"

    echo ""
    print_success "All steps completed!"
    echo ""

    # Get key information
    local cluster_name=$(_tf_output cluster_name || echo "N/A")
    local vpc_id=$(_tf_output vpc_id || echo "N/A")
    local rds_endpoint=$(_tf_output rds_cluster_endpoint || echo "N/A")

    print_info "Infrastructure info:"
    echo "  EKS Cluster: $cluster_name"
    echo "  VPC ID: $vpc_id"
    echo "  RDS Endpoint: $rds_endpoint"

    echo ""
    print_info "Application access:"
    echo "  Frontend: https://kbp.kolya.fun"
    echo "  API: https://api.kbp.kolya.fun"

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

        case $SPECIFIC_STEP in
            0)
                check_dependencies
                check_aws_credentials
                configure_tfvars
                ;;
            1)
                check_dependencies
                check_aws_credentials
                deploy_terraform
                ;;
            2)
                check_dependencies
                check_aws_credentials
                deploy_k8s_infrastructure
                ;;
            3)
                check_dependencies
                check_aws_credentials
                build_and_push_images
                ;;
            4)
                check_dependencies
                check_aws_credentials
                deploy_application
                ;;
            5)
                check_dependencies
                check_aws_credentials
                deploy_global_accelerator
                ;;
        esac

        echo ""
        print_success "Step $SPECIFIC_STEP complete"
        exit 0
    fi

    # Full deployment flow
    print_info "Starting full deployment flow"
    echo ""

    # Check environment
    check_dependencies
    check_aws_credentials

    # Confirm execution
    if [[ "$SKIP_CONFIRMATION" == "false" ]]; then
        echo ""
        print_warning "About to run the full deployment flow, including:"
        echo "  0️⃣  Configure terraform.tfvars"
        echo "  1️⃣  Terraform - AWS infrastructure"
        echo "  2️⃣  Helm - Kubernetes infrastructure"
        echo "  3️⃣  Docker - Build and push images"
        echo "  4️⃣  Kubernetes - Deploy application"
        echo ""
        echo "  (Step 5 - Global Accelerator is optional, run separately with --step 5)"
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
    configure_tfvars
    deploy_terraform
    deploy_k8s_infrastructure
    build_and_push_images
    deploy_application

    # Show summary
    show_deployment_summary
}

# Execute main function
main "$@"

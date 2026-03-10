#!/bin/bash
#
# Kolya BR Proxy - 应用部署脚本
# 统一的应用发布入口
#
# 用法：
#   ./deploy.sh init      # 首次初始化配置
#   ./deploy.sh deploy    # 部署应用
#   ./deploy.sh update    # 更新配置
#   ./deploy.sh status    # 查看部署状态
#   ./deploy.sh logs      # 查看日志
#   ./deploy.sh delete    # 删除部署

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 目录定义
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$SCRIPT_DIR/application"
INFRA_DIR="$SCRIPT_DIR/infrastructure"
TERRAFORM_DIR="$SCRIPT_DIR/../iac-612674025488-us-west-2"

# 命名空间
NAMESPACE="kbp"

# 打印函数
print_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
    echo ""
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

# 检查依赖
check_dependencies() {
    print_header "检查依赖"

    local missing_deps=()

    if ! command -v kubectl &> /dev/null; then
        missing_deps+=("kubectl")
    fi

    if ! command -v yq &> /dev/null; then
        missing_deps+=("yq")
    fi

    if ! command -v aws &> /dev/null; then
        missing_deps+=("aws-cli")
    fi

    if [ ${#missing_deps[@]} -ne 0 ]; then
        print_error "缺少依赖：${missing_deps[*]}"
        echo ""
        echo "请安装缺少的依赖："
        for dep in "${missing_deps[@]}"; do
            case $dep in
                kubectl)
                    echo "  kubectl: https://kubernetes.io/docs/tasks/tools/"
                    ;;
                yq)
                    echo "  yq: brew install yq"
                    ;;
                aws-cli)
                    echo "  aws-cli: https://aws.amazon.com/cli/"
                    ;;
            esac
        done
        exit 1
    fi

    print_success "所有依赖已安装"
}

# 检查kubectl连接
check_kubectl_connection() {
    print_info "检查 Kubernetes 连接..."

    if ! kubectl cluster-info &> /dev/null; then
        print_error "无法连接到 Kubernetes 集群"
        echo ""
        echo "请确保："
        echo "  1. EKS 集群已创建"
        echo "  2. kubectl 已配置（运行: aws eks update-kubeconfig）"
        echo ""
        exit 1
    fi

    local context=$(kubectl config current-context)
    print_success "已连接到集群: $context"
}

# 初始化配置
init_config() {
    print_header "初始化应用配置"

    cd "$APP_DIR"

    # 检查是否已存在配置
    if [ -f "secrets.yaml" ]; then
        print_warning "secrets.yaml 已存在"
        read -p "是否覆盖？(y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "保持现有配置"
            return
        fi
    fi

    print_info "从模板创建 secrets.yaml..."
    cp secrets.yaml.template secrets.yaml

    print_header "配置向导"
    echo "请填写以下配置信息（留空使用默认值）"
    echo ""

    # 获取 Terraform 输出
    print_info "尝试从 Terraform 获取配置..."
    if [ -d "$TERRAFORM_DIR" ]; then
        cd "$TERRAFORM_DIR"

        if terraform output region &> /dev/null; then
            AWS_REGION=$(terraform output -raw region 2>/dev/null || echo "us-west-2")
            RDS_ENDPOINT=$(terraform output -raw rds_cluster_endpoint 2>/dev/null || echo "")
            RDS_DATABASE=$(terraform output -raw rds_cluster_database_name 2>/dev/null || echo "")
            RDS_PORT=$(terraform output -raw rds_cluster_port 2>/dev/null || echo "5432")

            print_success "从 Terraform 获取了以下信息："
            echo "  AWS Region: $AWS_REGION"
            [ -n "$RDS_ENDPOINT" ] && echo "  RDS Endpoint: $RDS_ENDPOINT"
            [ -n "$RDS_DATABASE" ] && echo "  RDS Database: $RDS_DATABASE"
        else
            print_warning "Terraform 输出不可用，需要手动输入"
        fi
    fi

    cd "$APP_DIR"

    # 获取 AWS Account ID
    print_info "获取 AWS Account ID..."
    AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")
    if [ -n "$AWS_ACCOUNT_ID" ]; then
        print_success "AWS Account ID: $AWS_ACCOUNT_ID"
    else
        print_warning "无法自动获取 AWS Account ID"
        read -p "请输入 AWS Account ID: " AWS_ACCOUNT_ID
    fi

    # 域名配置
    echo ""
    print_info "域名配置"
    read -p "Frontend 域名 (例如 kbp.kolya.fun): " FRONTEND_DOMAIN
    read -p "API 域名 (例如 api.kbp.kolya.fun): " API_DOMAIN

    if [[ -z "$FRONTEND_DOMAIN" || -z "$API_DOMAIN" ]]; then
        print_error "域名不能为空"
        exit 1
    fi

    # 数据库密码
    echo ""
    print_info "数据库配置"
    read -sp "RDS 数据库密码: " DB_PASSWORD
    echo ""

    # JWT Secret
    echo ""
    print_info "JWT 配置"
    echo "JWT Secret Key（留空自动生成）:"
    read -p "> " JWT_SECRET
    if [ -z "$JWT_SECRET" ]; then
        JWT_SECRET=$(openssl rand -base64 32)
        print_success "已生成随机 JWT Secret"
    fi

    # Auth Provider 选择
    echo ""
    print_info "认证提供者配置"
    echo "  1) AWS Cognito (default - press Enter)"
    echo "  2) Microsoft Entra ID"
    echo "  3) 两者都配置"
    read -p "选择认证方式 [1/2/3]: " AUTH_CHOICE
    AUTH_CHOICE="${AUTH_CHOICE:-1}"

    MS_CLIENT_ID=""
    MS_CLIENT_SECRET=""
    MS_TENANT_ID=""
    COGNITO_USER_POOL_ID=""
    COGNITO_CLIENT_ID=""
    COGNITO_CLIENT_SECRET=""
    COGNITO_REGION=""

    if [[ "$AUTH_CHOICE" == "2" || "$AUTH_CHOICE" == "3" ]]; then
        echo ""
        print_info "Microsoft Entra ID 配置"
        read -p "Microsoft Client ID: " MS_CLIENT_ID
        read -sp "Microsoft Client Secret: " MS_CLIENT_SECRET
        echo ""
        read -p "Microsoft Tenant ID: " MS_TENANT_ID
    fi

    if [[ "$AUTH_CHOICE" == "1" || "$AUTH_CHOICE" == "3" ]]; then
        echo ""
        print_info "AWS Cognito 配置"
        read -p "Cognito User Pool ID: " COGNITO_USER_POOL_ID
        read -p "Cognito Client ID: " COGNITO_CLIENT_ID
        read -sp "Cognito Client Secret: " COGNITO_CLIENT_SECRET
        echo ""
        read -p "Cognito Region (留空使用 ${AWS_REGION}): " COGNITO_REGION
        COGNITO_REGION="${COGNITO_REGION:-$AWS_REGION}"
    fi

    # ACM 证书
    echo ""
    print_info "ACM 证书配置"
    echo "获取证书列表..."
    aws acm list-certificates --region ${AWS_REGION} --output table 2>/dev/null || true
    echo ""
    read -p "Frontend ACM Certificate ARN: " FRONTEND_CERT_ARN
    read -p "API ACM Certificate ARN: " API_CERT_ARN

    # 生成数据库 URL
    if [ -n "$RDS_ENDPOINT" ] && [ -n "$DB_PASSWORD" ] && [ -n "$RDS_DATABASE" ]; then
        DATABASE_URL="postgresql+asyncpg://postgres:${DB_PASSWORD}@${RDS_ENDPOINT}:${RDS_PORT}/${RDS_DATABASE}"
    else
        read -p "完整的数据库 URL: " DATABASE_URL
    fi

    # 写入配置文件
    print_info "生成配置文件..."

    cat > secrets.yaml << EOF
apiVersion: v1
kind: Secret
metadata:
  name: backend-secrets
  namespace: ${NAMESPACE}
type: Opaque
stringData:
  # Database connection
  database-url: "${DATABASE_URL}"

  # JWT secrets
  jwt-secret-key: "${JWT_SECRET}"

  # AWS credentials (optional - prefer IAM roles)
  aws-access-key-id: ""
  aws-secret-access-key: ""

  # Microsoft Entra ID OAuth
  microsoft-client-id: "${MS_CLIENT_ID}"
  microsoft-client-secret: "${MS_CLIENT_SECRET}"
  microsoft-tenant-id: "${MS_TENANT_ID}"

  # AWS Cognito OAuth
  cognito-user-pool-id: "${COGNITO_USER_POOL_ID}"
  cognito-client-id: "${COGNITO_CLIENT_ID}"
  cognito-client-secret: "${COGNITO_CLIENT_SECRET}"
  cognito-region: "${COGNITO_REGION}"

  # ACM Certificate ARNs
  acm-certificate-frontend-arn: "${FRONTEND_CERT_ARN}"
  acm-certificate-api-arn: "${API_CERT_ARN}"

  # AWS Account and Region
  aws-account-id: "${AWS_ACCOUNT_ID}"
  aws-region: "${AWS_REGION}"
EOF

    print_success "配置文件已创建: application/secrets.yaml"

    # 从 Terraform workspace 推导环境
    local KBR_ENV="non-prod"
    if [ -d "$TERRAFORM_DIR" ]; then
        local tf_workspace=$(cd "$TERRAFORM_DIR" && terraform workspace show 2>/dev/null || echo "default")
        if [[ "$tf_workspace" == "prod" ]]; then
            KBR_ENV="prod"
        fi
    fi
    print_info "环境: $KBR_ENV (由 Terraform workspace 推导)"

    # 根据环境设置资源配额
    print_info "根据环境 ($KBR_ENV) 设置资源配额..."
    if [[ "$KBR_ENV" == "prod" ]]; then
        # 生产环境 — 更大的资源配额
        export BACKEND_CPU_REQUEST="200m"
        export BACKEND_CPU_LIMIT="1000m"
        export BACKEND_MEMORY_REQUEST="512Mi"
        export BACKEND_MEMORY_LIMIT="1024Mi"
        export FRONTEND_CPU_REQUEST="100m"
        export FRONTEND_CPU_LIMIT="500m"
        export FRONTEND_MEMORY_REQUEST="256Mi"
        export FRONTEND_MEMORY_LIMIT="512Mi"
        export BACKEND_HPA_MIN="2"
        export BACKEND_HPA_MAX="10"
        export FRONTEND_HPA_MIN="2"
        export FRONTEND_HPA_MAX="5"
    else
        # 非生产环境
        export BACKEND_CPU_REQUEST="100m"
        export BACKEND_CPU_LIMIT="500m"
        export BACKEND_MEMORY_REQUEST="256Mi"
        export BACKEND_MEMORY_LIMIT="512Mi"
        export FRONTEND_CPU_REQUEST="50m"
        export FRONTEND_CPU_LIMIT="200m"
        export FRONTEND_MEMORY_REQUEST="128Mi"
        export FRONTEND_MEMORY_LIMIT="256Mi"
        export BACKEND_HPA_MIN="1"
        export BACKEND_HPA_MAX="10"
        export FRONTEND_HPA_MIN="1"
        export FRONTEND_HPA_MAX="5"
    fi

    # 生成 ConfigMap
    print_info "生成 ConfigMap 配置..."
    export FRONTEND_DOMAIN API_DOMAIN AWS_REGION KBR_ENV
    export API_PORT_SUFFIX=""  # Set to ":8443" when Global Accelerator is enabled
    envsubst < backend-configmap.yaml.template > backend-configmap.yaml
    envsubst < frontend-configmap.yaml.template > frontend-configmap.yaml
    print_success "ConfigMap 已生成"

    # 生成 Deployment 和 HPA 配置
    print_info "生成 Deployment 配置 ($KBR_ENV)..."
    envsubst < backend-deployment.yaml.template > backend-deployment.yaml
    envsubst < frontend-deployment.yaml.template > frontend-deployment.yaml
    envsubst < hpa-backend.yaml.template > hpa-backend.yaml
    envsubst < hpa-frontend.yaml.template > hpa-frontend.yaml
    print_success "Deployment 和 HPA 已生成"

    # 生成 ingress 文件
    print_info "生成 Ingress 配置..."
    ./generate-ingress.sh

    print_success "初始化完成！"
    echo ""
    print_info "下一步："
    echo "  1. 检查配置文件: application/secrets.yaml"
    echo "  2. 检查 ConfigMap: application/backend-configmap.yaml, application/frontend-configmap.yaml"
    echo "  3. 部署应用: ./deploy.sh deploy"
}

# 部署应用
deploy_app() {
    print_header "部署应用到 Kubernetes"

    cd "$APP_DIR"

    # 检查配置文件
    if [ ! -f "secrets.yaml" ]; then
        print_error "secrets.yaml 不存在"
        echo ""
        echo "请先运行: ./deploy.sh init"
        exit 1
    fi

    if [ ! -f "ingress-frontend.yaml" ] || [ ! -f "ingress-api.yaml" ]; then
        print_warning "Ingress 配置不存在，正在生成..."
        ./generate-ingress.sh
    fi

    # 确认部署
    echo ""
    print_warning "即将部署到集群: $(kubectl config current-context)"
    print_warning "命名空间: ${NAMESPACE}"
    echo ""
    read -p "确认部署？(y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "已取消部署"
        exit 0
    fi

    # 部署步骤
    print_info "步骤 1/8: 创建命名空间..."

    # 检查命名空间状态
    local ns_status=$(kubectl get namespace ${NAMESPACE} -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")

    if [ "$ns_status" == "Terminating" ]; then
        print_warning "检测到命名空间 ${NAMESPACE} 处于删除状态（可能是之前的操作未完成）"
        print_info "等待删除完成后再创建新的命名空间（最多等待 60 秒）..."

        local wait_count=0
        local max_wait=60

        while [ $wait_count -lt $max_wait ]; do
            ns_status=$(kubectl get namespace ${NAMESPACE} -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")

            if [ "$ns_status" == "NotFound" ]; then
                print_success "命名空间已删除完成"
                break
            fi

            echo -n "."
            sleep 1
            ((wait_count++))
        done
        echo ""

        # 如果超时，提供强制清理选项
        if [ $wait_count -ge $max_wait ]; then
            print_warning "命名空间删除超时"
            echo ""
            read -p "是否强制清理命名空间？这将移除所有 finalizers (y/N): " -n 1 -r
            echo ""

            if [[ $REPLY =~ ^[Yy]$ ]]; then
                print_info "强制清理命名空间..."

                # 移除 finalizers
                kubectl get namespace ${NAMESPACE} -o json | \
                    jq '.spec.finalizers = []' | \
                    kubectl replace --raw "/api/v1/namespaces/${NAMESPACE}/finalize" -f - 2>/dev/null || true

                # 再次等待
                sleep 5
                ns_status=$(kubectl get namespace ${NAMESPACE} -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")

                if [ "$ns_status" == "NotFound" ]; then
                    print_success "命名空间已强制删除"
                else
                    print_error "强制删除失败，请手动清理"
                    echo ""
                    echo "手动清理步骤："
                    echo "  1. 检查命名空间中的资源: kubectl get all -n ${NAMESPACE}"
                    echo "  2. 删除有 finalizers 的资源"
                    echo "  3. 或联系集群管理员"
                    exit 1
                fi
            else
                print_error "无法继续部署，命名空间仍在删除中"
                exit 1
            fi
        fi
    fi

    # 创建或更新命名空间
    kubectl apply -f namespace.yaml

    print_info "步骤 2/8: 部署 Secrets..."
    kubectl apply -f secrets.yaml

    print_info "步骤 3/8: 部署 ConfigMaps..."
    kubectl apply -f backend-configmap.yaml
    kubectl apply -f frontend-configmap.yaml

    print_info "步骤 4/8: 部署 Backend..."
    kubectl apply -f backend-deployment.yaml

    print_info "步骤 5/8: 部署 Frontend..."
    kubectl apply -f frontend-deployment.yaml

    print_info "步骤 6/8: 创建 Services..."
    kubectl apply -f backend-service.yaml
    kubectl apply -f frontend-service.yaml

    print_info "步骤 7/8: 创建 Ingress (ALB)..."
    kubectl apply -f ingress-frontend.yaml
    kubectl apply -f ingress-api.yaml

    print_info "步骤 8/8: 配置 HPA (自动扩缩容)..."
    kubectl apply -f hpa-backend.yaml
    kubectl apply -f hpa-frontend.yaml

    print_success "部署完成！"

    # 等待 Pod 启动
    echo ""
    print_info "等待 Pod 启动..."
    kubectl wait --for=condition=ready pod -l app=backend -n ${NAMESPACE} --timeout=300s || true
    kubectl wait --for=condition=ready pod -l app=frontend -n ${NAMESPACE} --timeout=300s || true

    # 显示状态
    show_status

    # 获取 ALB 地址
    echo ""
    print_header "ALB 信息"
    print_info "等待 ALB 创建（这可能需要几分钟）..."
    sleep 10

    FRONTEND_ALB=$(kubectl get ingress kolya-br-proxy-frontend -n ${NAMESPACE} -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "创建中...")
    API_ALB=$(kubectl get ingress kolya-br-proxy-api -n ${NAMESPACE} -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "创建中...")

    echo "Frontend ALB: $FRONTEND_ALB"
    echo "API ALB: $API_ALB"

    if [ "$FRONTEND_ALB" != "创建中..." ]; then
        echo ""
        print_success "部署成功！请更新 DNS 记录指向 ALB"
    fi
}

# 更新配置
update_config() {
    print_header "更新应用配置"

    cd "$APP_DIR"

    echo "选择更新内容："
    echo "  1) 更新 Secrets"
    echo "  2) 更新 ConfigMaps"
    echo "  3) 更新 Ingress (证书)"
    echo "  4) 全部更新"
    read -p "请选择 (1-4): " choice

    case $choice in
        1)
            print_info "更新 Secrets..."
            kubectl apply -f secrets.yaml
            kubectl rollout restart deployment/backend -n ${NAMESPACE}
            kubectl rollout restart deployment/frontend -n ${NAMESPACE}
            ;;
        2)
            print_info "更新 ConfigMaps..."
            kubectl apply -f backend-configmap.yaml
            kubectl apply -f frontend-configmap.yaml
            kubectl rollout restart deployment/backend -n ${NAMESPACE}
            kubectl rollout restart deployment/frontend -n ${NAMESPACE}
            ;;
        3)
            print_info "重新生成 Ingress..."
            ./generate-ingress.sh
            kubectl apply -f ingress-frontend.yaml
            kubectl apply -f ingress-api.yaml
            ;;
        4)
            print_info "更新所有配置..."
            kubectl apply -f secrets.yaml
            kubectl apply -f backend-configmap.yaml
            kubectl apply -f frontend-configmap.yaml
            ./generate-ingress.sh
            kubectl apply -f ingress-frontend.yaml
            kubectl apply -f ingress-api.yaml
            kubectl rollout restart deployment/backend -n ${NAMESPACE}
            kubectl rollout restart deployment/frontend -n ${NAMESPACE}
            ;;
        *)
            print_error "无效选择"
            exit 1
            ;;
    esac

    print_success "配置已更新"

    # 等待更新完成
    print_info "等待 Pod 重启..."
    kubectl rollout status deployment/backend -n ${NAMESPACE} || true
    kubectl rollout status deployment/frontend -n ${NAMESPACE} || true
}

# 查看状态
show_status() {
    print_header "应用状态"

    echo ""
    print_info "命名空间: ${NAMESPACE}"
    echo ""

    print_info "Pods:"
    kubectl get pods -n ${NAMESPACE}

    echo ""
    print_info "Services:"
    kubectl get svc -n ${NAMESPACE}

    echo ""
    print_info "Ingress:"
    kubectl get ingress -n ${NAMESPACE}

    echo ""
    print_info "HPA:"
    kubectl get hpa -n ${NAMESPACE}
}

# 查看日志
show_logs() {
    print_header "查看日志"

    echo "选择要查看的日志："
    echo "  1) Backend"
    echo "  2) Frontend"
    echo "  3) 同时查看两者"
    read -p "请选择 (1-3): " choice

    case $choice in
        1)
            kubectl logs -f -l app=backend -n ${NAMESPACE} --tail=100
            ;;
        2)
            kubectl logs -f -l app=frontend -n ${NAMESPACE} --tail=100
            ;;
        3)
            kubectl logs -f -l 'app in (backend,frontend)' -n ${NAMESPACE} --tail=100
            ;;
        *)
            print_error "无效选择"
            exit 1
            ;;
    esac
}

# 删除部署
delete_app() {
    print_header "删除应用"

    print_warning "⚠️  警告：这将删除所有应用资源（不包括基础设施）"
    echo ""
    read -p "确认删除？输入 'yes' 继续: " confirm

    if [ "$confirm" != "yes" ]; then
        print_info "已取消删除"
        exit 0
    fi

    print_info "删除应用资源..."

    cd "$APP_DIR"

    kubectl delete -f hpa-frontend.yaml --ignore-not-found=true
    kubectl delete -f hpa-backend.yaml --ignore-not-found=true
    kubectl delete -f ingress-api.yaml --ignore-not-found=true
    kubectl delete -f ingress-frontend.yaml --ignore-not-found=true
    kubectl delete -f frontend-service.yaml --ignore-not-found=true
    kubectl delete -f backend-service.yaml --ignore-not-found=true
    kubectl delete -f frontend-deployment.yaml --ignore-not-found=true
    kubectl delete -f backend-deployment.yaml --ignore-not-found=true
    kubectl delete -f frontend-configmap.yaml --ignore-not-found=true
    kubectl delete -f backend-configmap.yaml --ignore-not-found=true
    kubectl delete -f secrets.yaml --ignore-not-found=true

    print_info "等待资源清理..."
    sleep 5

    read -p "是否同时删除命名空间？(y/N): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        kubectl delete -f namespace.yaml --ignore-not-found=true
        print_success "命名空间已删除"
    fi

    print_success "应用已删除"
}

# 显示帮助
show_help() {
    cat << EOF
Kolya BR Proxy - 应用部署脚本

用法: ./deploy.sh <command>

命令:
  init      首次初始化配置（交互式向导）
  deploy    部署应用到 Kubernetes
  update    更新配置并重启 Pods
  status    查看部署状态
  logs      查看应用日志
  delete    删除应用部署
  help      显示此帮助信息

示例:
  # 首次使用
  ./deploy.sh init     # 配置向导
  ./deploy.sh deploy   # 部署应用

  # 日常使用
  ./deploy.sh status   # 查看状态
  ./deploy.sh logs     # 查看日志
  ./deploy.sh update   # 更新配置

目录结构:
  infrastructure/      基础设施配置（Karpenter、Helm等）
  application/         应用配置（Deployments、Services等）

更多信息: 查看 README.md
EOF
}

# 主函数
main() {
    cd "$SCRIPT_DIR"

    if [ $# -eq 0 ]; then
        show_help
        exit 0
    fi

    case "$1" in
        init)
            check_dependencies
            check_kubectl_connection
            init_config
            ;;
        deploy)
            check_dependencies
            check_kubectl_connection
            deploy_app
            ;;
        update)
            check_dependencies
            check_kubectl_connection
            update_config
            ;;
        status)
            check_kubectl_connection
            show_status
            ;;
        logs)
            check_kubectl_connection
            show_logs
            ;;
        delete)
            check_kubectl_connection
            delete_app
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "未知命令: $1"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

main "$@"

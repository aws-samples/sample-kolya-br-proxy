#!/bin/bash
#
# Kolya BR Proxy - Application Resource Cleanup
# Deletes all Step 4 (application) resources from the cluster
#
# Usage:
#   ./cleanup-app.sh              # Delete app resources, keep namespace
#   ./cleanup-app.sh --all        # Delete app resources + namespace
#

set -e

NAMESPACE="kbp"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$SCRIPT_DIR/application"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info()    { echo -e "${BLUE}ℹ️  $1${NC}"; }
print_success() { echo -e "${GREEN}✅ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
print_error()   { echo -e "${RED}❌ $1${NC}"; }

DELETE_NS=false
if [[ "$1" == "--all" ]]; then
    DELETE_NS=true
fi

echo ""
print_warning "This will delete all Step 4 application resources in namespace '${NAMESPACE}'"
if [[ "$DELETE_NS" == "true" ]]; then
    print_warning "Namespace '${NAMESPACE}' will also be deleted"
fi
echo ""
echo "  Cluster: $(kubectl config current-context)"
echo ""
read -p "Confirm? (yes/no): " confirm
if [[ "$confirm" != "yes" ]]; then
    print_info "Cancelled"
    exit 0
fi

echo ""

# Delete in reverse dependency order
print_info "Deleting HPA..."
kubectl delete hpa --all -n ${NAMESPACE} --ignore-not-found=true

print_info "Deleting Ingress..."
kubectl delete ingress --all -n ${NAMESPACE} --ignore-not-found=true

print_info "Deleting Services..."
kubectl delete svc --all -n ${NAMESPACE} --ignore-not-found=true

print_info "Deleting Deployments..."
kubectl delete deployment --all -n ${NAMESPACE} --ignore-not-found=true

print_info "Deleting ConfigMaps..."
kubectl delete configmap --all -n ${NAMESPACE} --ignore-not-found=true

print_info "Deleting ExternalSecrets..."
kubectl delete externalsecret --all -n ${NAMESPACE} --ignore-not-found=true

print_info "Deleting Secrets (non-default)..."
kubectl get secrets -n ${NAMESPACE} -o name 2>/dev/null | while read secret; do
    kubectl delete "$secret" -n ${NAMESPACE} --ignore-not-found=true
done

print_info "Deleting ClusterSecretStore..."
kubectl delete clustersecretstore aws-secrets-manager --ignore-not-found=true

print_info "Deleting ServiceAccounts (non-default)..."
kubectl get sa -n ${NAMESPACE} -o name 2>/dev/null | grep -v 'serviceaccount/default' | while read sa; do
    kubectl delete "$sa" -n ${NAMESPACE} --ignore-not-found=true
done

# Wait for ALB cleanup (ALB Controller needs time to deregister)
print_info "Waiting for ALB cleanup..."
sleep 10

if [[ "$DELETE_NS" == "true" ]]; then
    print_info "Deleting namespace '${NAMESPACE}'..."
    kubectl delete namespace ${NAMESPACE} --ignore-not-found=true

    # Wait for namespace deletion
    local max_wait=60
    local waited=0
    while kubectl get namespace ${NAMESPACE} &>/dev/null && [[ $waited -lt $max_wait ]]; do
        echo -n "."
        sleep 2
        waited=$((waited + 2))
    done
    echo ""
fi

# Clean up generated YAML files
print_info "Cleaning up generated YAML files..."
cd "$APP_DIR"
rm -f backend-deployment.yaml frontend-deployment.yaml
rm -f backend-configmap.yaml frontend-configmap.yaml
rm -f hpa-backend.yaml hpa-frontend.yaml
rm -f ingress-frontend.yaml ingress-api.yaml
rm -f secret-store.yaml external-secret.yaml

echo ""
print_success "Cleanup complete!"
echo ""
print_info "To redeploy, run: ./deploy-all.sh --step 4"

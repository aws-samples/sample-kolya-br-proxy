#!/bin/bash
#
# Generate Ingress YAML files from Kubernetes secret (synced by External Secrets Operator)
#
# This script reads ACM certificate ARNs and other config from the k8s secret
# 'backend-secrets' in namespace 'kbp', which is populated by ESO from AWS Secrets Manager.
#
# Usage:
#   ./generate-ingress.sh
#
# Prerequisites:
#   - kubectl configured with cluster access
#   - External Secrets Operator has synced backend-secrets in namespace kbp

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

NAMESPACE="kbp"
SECRET_NAME="backend-secrets"  # pragma: allowlist secret

# Check if kubectl can access the secret
echo "Reading configuration from k8s secret '$SECRET_NAME' in namespace '$NAMESPACE'..."
if ! kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" &> /dev/null; then
    echo "❌ Error: secret '$SECRET_NAME' not found in namespace '$NAMESPACE'"
    echo "   Ensure External Secrets Operator has synced the secret from AWS Secrets Manager"
    echo "   Check: kubectl get externalsecret -n $NAMESPACE"
    exit 1
fi

# Extract values from k8s secret
FRONTEND_ACM_CERT=$(kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o jsonpath='{.data.acm-certificate-frontend-arn}' | base64 -d)
API_ACM_CERT=$(kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o jsonpath='{.data.acm-certificate-api-arn}' | base64 -d)
AWS_ACCOUNT_ID=$(kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o jsonpath='{.data.aws-account-id}' | base64 -d)
AWS_REGION=$(kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o jsonpath='{.data.aws-region}' | base64 -d)

# 从 Terraform workspace 推导环境：prod workspace = prod，其他一律 non-prod
TERRAFORM_DIR="$SCRIPT_DIR/../../iac"
if [[ -d "$TERRAFORM_DIR" ]]; then
    TF_WORKSPACE=$(cd "$TERRAFORM_DIR" && terraform workspace show 2>/dev/null || echo "default")
    if [[ "$TF_WORKSPACE" == "prod" ]]; then
        ENVIRONMENT="prod"
    else
        ENVIRONMENT="non-prod"
    fi
else
    ENVIRONMENT="non-prod"
fi

# Validate required values
if [[ -z "$FRONTEND_ACM_CERT" ]]; then
    echo "❌ Error: acm-certificate-frontend-arn not found in secret '$SECRET_NAME'"
    exit 1
fi

if [[ -z "$API_ACM_CERT" ]]; then
    echo "❌ Error: acm-certificate-api-arn not found in secret '$SECRET_NAME'"
    exit 1
fi

# Validate certificate ARN region matches deployment region
if [[ -n "$AWS_REGION" && "$FRONTEND_ACM_CERT" != *":acm:${AWS_REGION}:"* ]]; then
    echo "⚠️  Warning: Frontend certificate ARN region does not match deployment region ($AWS_REGION)"
    echo "   Certificate: $FRONTEND_ACM_CERT"
fi

if [[ -n "$AWS_REGION" && "$API_ACM_CERT" != *":acm:${AWS_REGION}:"* ]]; then
    echo "⚠️  Warning: API certificate ARN region does not match deployment region ($AWS_REGION)"
    echo "   Certificate: $API_ACM_CERT"
fi

echo "✅ Configuration loaded:"
echo "   AWS Account ID: $AWS_ACCOUNT_ID"
echo "   AWS Region: $AWS_REGION"
echo "   Frontend ACM Cert: ${FRONTEND_ACM_CERT:0:50}..."
echo "   API ACM Cert: ${API_ACM_CERT:0:50}..."
echo ""

# Generate ingress-frontend.yaml
echo "🔨 Generating ingress-frontend.yaml..."
cat > ingress-frontend.yaml << EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: kolya-br-proxy-frontend
  namespace: kbp
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTP": 80}, {"HTTPS": 443}]'
    alb.ingress.kubernetes.io/ssl-redirect: '443'
    alb.ingress.kubernetes.io/certificate-arn: ${FRONTEND_ACM_CERT}
    alb.ingress.kubernetes.io/load-balancer-name: kolya-br-proxy-frontend-alb
    alb.ingress.kubernetes.io/tags: Environment=${ENVIRONMENT},Project=kolya-br-proxy,Service=frontend
    # Connection optimizations
    alb.ingress.kubernetes.io/load-balancer-attributes: idle_timeout.timeout_seconds=300
    alb.ingress.kubernetes.io/target-group-attributes: deregistration_delay.timeout_seconds=30
    # Health check settings
    alb.ingress.kubernetes.io/healthcheck-interval-seconds: '15'
    alb.ingress.kubernetes.io/healthcheck-timeout-seconds: '5'
    alb.ingress.kubernetes.io/healthcheck-path: /
    alb.ingress.kubernetes.io/healthy-threshold-count: '2'
    alb.ingress.kubernetes.io/unhealthy-threshold-count: '2'
spec:
  ingressClassName: alb
  rules:
  - host: kbp.kolya.fun
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: frontend
            port:
              number: 3000
EOF

# Generate ingress-api.yaml
echo "🔨 Generating ingress-api.yaml..."
cat > ingress-api.yaml << EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: kolya-br-proxy-api
  namespace: kbp
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTP": 80}, {"HTTPS": 443}]'
    alb.ingress.kubernetes.io/ssl-redirect: '443'
    alb.ingress.kubernetes.io/certificate-arn: ${API_ACM_CERT}
    alb.ingress.kubernetes.io/load-balancer-name: kolya-br-proxy-api-alb
    alb.ingress.kubernetes.io/tags: Environment=${ENVIRONMENT},Project=kolya-br-proxy,Service=api
    # Streaming response optimizations
    alb.ingress.kubernetes.io/load-balancer-attributes: idle_timeout.timeout_seconds=600
    alb.ingress.kubernetes.io/target-group-attributes: deregistration_delay.timeout_seconds=30,load_balancing.algorithm.type=round_robin
    # Health check settings
    alb.ingress.kubernetes.io/healthcheck-interval-seconds: '15'
    alb.ingress.kubernetes.io/healthcheck-timeout-seconds: '5'
    alb.ingress.kubernetes.io/healthcheck-path: /health/
    alb.ingress.kubernetes.io/healthy-threshold-count: '2'
    alb.ingress.kubernetes.io/unhealthy-threshold-count: '2'
spec:
  ingressClassName: alb
  rules:
  - host: api.kbp.kolya.fun
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: backend
            port:
              number: 8000
EOF

echo "✅ Ingress files generated successfully!"
echo ""
echo "Next steps:"
echo "  1. Review the generated files: ingress-frontend.yaml, ingress-api.yaml"
echo "  2. Apply to cluster: kubectl apply -f ingress-frontend.yaml -f ingress-api.yaml"
echo ""

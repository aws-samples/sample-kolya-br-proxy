#!/bin/bash
#
# Generate Ingress YAML files from secrets.yaml
#
# This script reads ACM certificate ARNs and other config from secrets.yaml
# and generates the final ingress files with proper values.
#
# Usage:
#   ./generate-ingress.sh
#
# Prerequisites:
#   - yq (brew install yq)
#   - secrets.yaml must exist (copy from secrets.yaml.template)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if secrets.yaml exists
if [[ ! -f "secrets.yaml" ]]; then
    echo "❌ Error: secrets.yaml not found"
    echo "   Copy secrets.yaml.template to secrets.yaml and fill in values"
    exit 1
fi

# Check if yq is installed
if ! command -v yq &> /dev/null; then
    echo "❌ Error: yq is not installed"
    echo "   Install with: brew install yq"
    exit 1
fi

echo "📊 Reading configuration from secrets.yaml..."

# Extract values from secrets.yaml
FRONTEND_ACM_CERT=$(yq '.stringData.acm-certificate-frontend-arn' secrets.yaml)
API_ACM_CERT=$(yq '.stringData.acm-certificate-api-arn' secrets.yaml)
AWS_ACCOUNT_ID=$(yq '.stringData.aws-account-id' secrets.yaml)
AWS_REGION=$(yq '.stringData.aws-region' secrets.yaml)

# 从 Terraform workspace 推导环境：prod workspace = prod，其他一律 non-prod
TERRAFORM_DIR="$SCRIPT_DIR/../../iac-612674025488-us-west-2"
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
if [[ -z "$FRONTEND_ACM_CERT" || "$FRONTEND_ACM_CERT" == "null" ]]; then
    echo "❌ Error: acm-certificate-frontend-arn not found in secrets.yaml"
    exit 1
fi

if [[ -z "$API_ACM_CERT" || "$API_ACM_CERT" == "null" ]]; then
    echo "❌ Error: acm-certificate-api-arn not found in secrets.yaml"
    exit 1
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
    alb.ingress.kubernetes.io/target-group-attributes: deregistration_delay.timeout_seconds=30
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

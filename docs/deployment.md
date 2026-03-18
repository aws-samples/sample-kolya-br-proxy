# Deployment Guide

This document covers the full deployment lifecycle of Kolya BR Proxy, from local development to production on AWS EKS.

## Prerequisites

### Required Tools

| Tool | Version | Installation |
|------|---------|-------------|
| Terraform | >= 1.0 | https://www.terraform.io/downloads |
| kubectl | latest | https://kubernetes.io/docs/tasks/tools/ |
| Helm | latest | https://helm.sh/docs/intro/install/ |
| AWS CLI | v2 | https://aws.amazon.com/cli/ |
| Docker | latest | https://docs.docker.com/get-docker/ |
| jq | latest | `brew install jq` |
| yq | latest | `brew install yq` |
| Node.js | 20+ | https://nodejs.org/ |
| Python | 3.12+ | https://www.python.org/ |
| uv | latest | https://astral.sh/uv |

### AWS Account

- An AWS account with permissions to create VPC, EKS, RDS, IAM, ACM, Route 53, and ECR resources.
- AWS CLI configured with valid credentials (`aws configure` or environment variables).
- A registered domain managed via Route 53 (default: `kolya.fun`).

---

## Local Development Setup

### 1. Clone the Repository

```bash
git clone https://github.com/kolya-amazon/kolya-br-proxy.git
cd kolya-br-proxy
```

### 2. Backend Setup

```bash
cd backend
cp .env.example .env
# Edit .env with your local settings (database URL, JWT secret, etc.)
```

Key environment variables in `.env`:

```bash
KBR_ENV=non-prod
KBR_DEBUG=true
KBR_PORT=8000
KBR_DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/kolyabrproxy  # pragma: allowlist secret
KBR_JWT_SECRET_KEY=your-secret-key-min-32-characters-long  # pragma: allowlist secret
KBR_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:9000
KBR_AWS_REGION=us-west-2
KBR_MICROSOFT_CLIENT_ID=your-client-id
KBR_MICROSOFT_CLIENT_SECRET=your-client-secret
KBR_MICROSOFT_TENANT_ID=your-tenant-id
```

Start the backend:

```bash
uv sync
KBR_ENV=local uv run python main.py
```

The API will be available at `http://localhost:8000`. Health check: `http://localhost:8000/health/`.

### 3. Frontend Setup

```bash
cd frontend
npm ci
npm run dev
```

The frontend will be available at `http://localhost:9000`.

### 4. Database Setup

Ensure PostgreSQL is running locally, then run migrations:

```bash
cd backend
KBR_ENV=local uv run alembic upgrade head
```

---

## Production Deployment Overview

The production deployment follows a strict 4-step flow. Each step can be run independently or as a single automated process.

```mermaid
flowchart LR
    S1["Step 1\nTerraform\n(AWS Infra)"]
    S2["Step 2\nHelm\n(K8s Infra)"]
    S3["Step 3\nDocker\n(Build Images)"]
    S4["Step 4\nK8s Deploy\n(Application)"]
    S5["Step 5\nGlobal Accelerator\n(Optional)"]
    S1 --> S2 --> S3 --> S4 -.-> S5
```

### Unified Deployment Script

The `deploy-all.sh` script orchestrates all four steps:

```bash
# Full interactive deployment (Steps 1-4)
./deploy-all.sh

# Run a single step
./deploy-all.sh --step 1   # Terraform only (AWS infra + Cognito setup)
./deploy-all.sh --step 2   # Helm only (K8s infra)
./deploy-all.sh --step 3   # Docker build only
./deploy-all.sh --step 4   # App deploy only
./deploy-all.sh --step 5   # Global Accelerator toggle (enable/disable, requires Steps 1-4)

# Skip confirmations (use with caution)
./deploy-all.sh --yes
```

---

## Step 1: Terraform -- AWS Infrastructure

Terraform provisions all cloud resources: VPC, EKS, RDS Aurora PostgreSQL, IAM roles, security groups, ACM certificates, and Route 53 DNS.

```bash
cd iac-612674025488-us-west-2

# Select workspace (determines environment)
terraform workspace select non-prod   # or: terraform workspace select prod

# Deploy
terraform init -upgrade
terraform plan -out=tfplan
terraform apply tfplan
```

The Terraform workspace determines whether the deployment uses production or non-production settings. See the configuration differences table below.

### Prod vs Non-Prod Configuration Differences

| Category | Setting | Non-Prod | Prod |
|----------|---------|----------|------|
| **Backend Pod** | CPU request / limit | 100m / 500m | 200m / 1000m |
| | Memory request / limit | 256Mi / 512Mi | 512Mi / 1024Mi |
| | HPA min replicas | 1 | 2 |
| **Frontend Pod** | CPU request / limit | 50m / 200m | 100m / 500m |
| | Memory request / limit | 128Mi / 256Mi | 256Mi / 512Mi |
| | HPA min replicas | 1 | 2 |
| **EKS Core Nodes** | Instance type | `t4g.small` | `t4g.medium` |
| | EBS volume size | 30 GB | 100 GB |
| **Karpenter Nodes** | Instance category | `t` (t4g) | `m` (m7g) |
| | EBS volume size | 30 GB | 100 GB |
| | CPU limit | 100 | 1000 |
| | Memory limit | 100 Gi | 1000 Gi |
| **RDS Aurora** | Deletion protection | Disabled | Enabled |
| | Backup retention (days) | 1 | 7 |
| | Preferred backup window | Not set | 03:00-04:00 UTC |
| | Copy tags to snapshot | No | Yes |
| | Skip final snapshot | Yes | No |
| | Apply immediately | Yes | No |
| | CloudWatch log exports | None | `["postgresql"]` |
| | Monitoring interval (sec) | 0 (disabled) | 60 |
| | Performance Insights | Disabled | Enabled |
| **Cognito** | Advanced security mode | `AUDIT` | `ENFORCED` |
| | Deletion protection | Disabled | Enabled |
| **Global Accelerator** | Flow logs | Disabled | Enabled |

Pod resource and HPA differences are driven by `deploy-all.sh` and `deploy.sh` during configuration generation (templates in `k8s/application/*.yaml.template`). Infrastructure differences are driven by conditionals in `iac-612674025488-us-west-2/main.tf` and `modules/eks-karpenter/eks.tf` using `workspace == "prod"`.

---

## Step 2: Helm -- Kubernetes Infrastructure

After Terraform provisions the EKS cluster, install the required cluster-level components via Helm charts.

```bash
# Configure kubectl
aws eks update-kubeconfig --name <cluster-name> --region us-west-2

# Generate Helm values from Terraform outputs
cd k8s/infrastructure/helm-installations
./generate-values.sh ../../iac-612674025488-us-west-2

# Install Helm charts (ALB Controller, Karpenter, Metrics Server)
./install.sh

# Apply Karpenter node configuration
cd ../karpenter
./apply-karpenter-config.sh
```

Components installed:
- **AWS Load Balancer Controller** (v3.0.0) -- manages ALB creation from Ingress resources
- **Karpenter** (v1.9.0) -- automatic node provisioning and scaling
- **Metrics Server** (v3.13.0) -- provides CPU/memory metrics for HPA

---

## Step 3: Docker Image Build

Both backend and frontend images target `linux/arm64` for Graviton-based instances.

### Using the Build Script

```bash
# Build and push both images
./build-and-push.sh

# Build a single target
./build-and-push.sh backend
./build-and-push.sh frontend

# Custom tag
./build-and-push.sh --tag v1.2.3
```

### Manual Build

```bash
# ECR login
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr get-login-password --region us-west-2 | \
  docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com

# Backend (context is project root, Dockerfile in backend/)
docker build --platform linux/arm64 -f backend/Dockerfile \
  -t $ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com/kolya-br-proxy-backend:latest .

# Frontend (context is frontend/)
cd frontend
docker build --platform linux/arm64 \
  --build-arg VITE_API_BASE_URL=https://api.kbp.kolya.fun \
  --build-arg VITE_MICROSOFT_REDIRECT_URI=https://kbp.kolya.fun/auth/microsoft/callback \
  -t $ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com/kolya-br-proxy-frontend:latest .

# Push
docker push $ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com/kolya-br-proxy-backend:latest
docker push $ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com/kolya-br-proxy-frontend:latest
```

### Image Details

| Image | Base | Platform | Health Check | Port |
|-------|------|----------|-------------|------|
| Backend | `python:3.12-slim` | `linux/arm64` | `curl http://localhost:8000/health/` | 8000 |
| Frontend | `nginx:alpine` (multi-stage) | `linux/arm64` | `wget http://localhost:3000/` | 3000 |

---

## Step 4: Kubernetes Application Deploy

### First-Time Initialization

When running `deploy-all.sh`, Step 4 includes an **inline config wizard** that automatically detects whether configuration files already exist. On first run, it launches the interactive wizard directly -- there is no need to run `deploy.sh init` separately.

The config wizard fetches Terraform outputs (RDS endpoint, region, Cognito credentials) automatically and prompts for:
- **Auth provider selection** -- Cognito (default) or Microsoft Entra ID
- Domain names (frontend and API)
- Database password
- JWT secret (auto-generated if left blank)
- OAuth provider credentials (based on the selected auth provider)
- ACM certificate ARNs

On subsequent runs, the wizard is skipped if configuration files are already present.

> **Note on Cognito users:** Self-registration is disabled. The first admin user is created automatically at the end of Step 1 (Terraform), and a temporary password is emailed. Additional users must be created by an admin via `aws cognito-idp admin-create-user`. See the [OAuth Setup Guide](oauth-setup.md) for details.

> **Note:** You can still run `./deploy.sh init` standalone from the `k8s/` directory to re-configure or update settings at any time.

```bash
# Full deployment (wizard runs automatically on first deploy)
./deploy-all.sh

# Or run Step 4 individually
./deploy-all.sh --step 4

# Standalone re-configuration (if needed later)
cd k8s
./deploy.sh init
```

### Day-to-Day Operations

```bash
./deploy.sh status    # View pods, services, ingress, HPA
./deploy.sh logs      # Stream application logs
./deploy.sh update    # Update secrets/configmaps and restart pods
./deploy.sh delete    # Remove the application
```

### Resources Created

| Resource | Name | Namespace |
|----------|------|-----------|
| Namespace | `kbp` | -- |
| Deployment | `backend` (1-10 replicas) | `kbp` |
| Deployment | `frontend` (1-5 replicas) | `kbp` |
| Service | `backend` (ClusterIP) | `kbp` |
| Service | `frontend` (ClusterIP) | `kbp` |
| Ingress | `kolya-br-proxy-frontend` | `kbp` |
| Ingress | `kolya-br-proxy-api` | `kbp` |
| HPA | `backend-hpa` | `kbp` |
| HPA | `frontend-hpa` | `kbp` |
| Secret | `backend-secrets` | `kbp` |
| ConfigMap | `backend-config` | `kbp` |
| ConfigMap | `frontend-config` | `kbp` |

---

## DNS Configuration

After the Ingress resources create ALBs (takes 2-3 minutes), configure DNS records:

```bash
# Get ALB addresses
kubectl get ingress -n kbp
```

Create CNAME records in your DNS provider:

| Record | Type | Value |
|--------|------|-------|
| `kbp.kolya.fun` | CNAME | Frontend ALB hostname |
| `api.kbp.kolya.fun` | CNAME | API ALB hostname |

For Route 53:

```bash
ZONE_ID=$(aws route53 list-hosted-zones-by-name \
  --dns-name kolya.fun \
  --query 'HostedZones[0].Id' --output text | cut -d'/' -f3)

FRONTEND_ALB=$(kubectl get ingress kolya-br-proxy-frontend -n kbp \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

aws route53 change-resource-record-sets --hosted-zone-id $ZONE_ID --change-batch '{
  "Changes": [{"Action":"UPSERT","ResourceRecordSet":{
    "Name":"kbp.kolya.fun","Type":"CNAME","TTL":300,
    "ResourceRecords":[{"Value":"'$FRONTEND_ALB'"}]
  }}]
}'
```

Repeat for the API ALB with `api.kbp.kolya.fun`.

---

## Step 5: Global Accelerator (Optional)

AWS Global Accelerator routes traffic over the AWS backbone network, reducing latency for geographically distant users by 40-60%.

> **Important:** Global Accelerator requires ALBs created in Step 4. It cannot be deployed together with Step 1 because the ALBs do not exist yet. Always run Steps 1-4 first.

### Architecture

```
Without GA:  User (Asia) --> Public Internet --> us-west-2 ALB --> EKS
With GA:     User (Asia) --> Nearest AWS Edge --> AWS Backbone --> us-west-2 ALB --> EKS
```

### Enable / Disable Global Accelerator

```bash
# Toggle via deploy-all.sh (recommended)
./deploy-all.sh --step 5
```

The script automatically detects the current GA state and offers the appropriate action:

**When GA is disabled** (enable flow):
1. Verify that both ALBs (`kolya-br-proxy-frontend-alb` and `kolya-br-proxy-api-alb`) exist
2. Update `terraform.tfvars` with `enable_global_accelerator = true`
3. Run `terraform plan` and ask for confirmation
4. Apply and display the Global Accelerator DNS name and static IPs
5. Regenerate configmaps with API port 8443 (`API_PORT_SUFFIX=":8443"`)
6. Apply configmaps and restart pods

**When GA is enabled** (disable flow):
1. Update `terraform.tfvars` with `enable_global_accelerator = false`
2. Run `terraform plan` and ask for confirmation
3. Apply to destroy the Global Accelerator
4. Regenerate configmaps with default API port (`API_PORT_SUFFIX=""`)
5. Apply configmaps and restart pods
6. Display ALB hostnames for DNS rollback

### Port Mapping

| Service | GA Port | ALB Port | Protocol |
|---------|---------|----------|----------|
| Frontend | 443 | 443 | HTTPS |
| Frontend | 80 | 80 | HTTP |
| API | 8443 | 443 | HTTPS |
| API | 8080 | 80 | HTTP |

### DNS with Global Accelerator

Update DNS to point at the GA DNS name:

```bash
GA_DNS=$(terraform output -raw global_accelerator_dns_name)

# kbp.kolya.fun      CNAME  $GA_DNS
# ga-api.kbp.kolya.fun  CNAME  $GA_DNS
```

For a safe rollout, use a gradual migration approach: keep existing ALB DNS as primary, add GA as a secondary subdomain (`ga.kbp.kolya.fun`), test, then switch.

### Cost

| Component | Monthly Cost |
|-----------|-------------|
| Fixed fee | $18.00 |
| Data transfer (100 GB) | $1.50 |
| **Total (typical)** | **~$19.50** |

---

## Database Migrations

Migrations use Alembic and run inside the backend context.

### Run Migrations Locally

```bash
cd backend
uv run alembic upgrade head
```

### Run Migrations on EKS

```bash
# Exec into a running backend pod
kubectl exec -it deployment/backend -n kbp -- uv run alembic upgrade head
```

### Create a New Migration

```bash
cd backend
uv run alembic revision --autogenerate -m "describe your change"
```

---

## Health Checks

### Backend

```bash
curl http://localhost:8000/health/
```

The Dockerfile configures a health check that runs every 30 seconds with a 10-second timeout and 3 retries:

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/ || exit 1
```

### Frontend

```bash
wget --quiet --tries=1 --spider http://localhost:3000/
```

### Kubernetes-Level Checks

```bash
# Pod status
kubectl get pods -n kbp

# HPA metrics
kubectl top pods -n kbp

# Ingress / ALB status
kubectl get ingress -n kbp
kubectl describe ingress -n kbp
```

---

## Troubleshooting

### Ingress Not Creating ALB

```bash
# Check ALB Controller is running
kubectl get pods -n kube-system | grep aws-load-balancer
kubectl logs -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller

# Check Ingress events
kubectl describe ingress -n kbp
```

### Pods Failing to Start

```bash
kubectl get pods -n kbp
kubectl describe pod <pod-name> -n kbp
kubectl logs <pod-name> -n kbp
```

Common causes:
- Image pull failure (check ECR permissions and image existence)
- Configuration error (check `secrets.yaml` values)
- Insufficient resources (check Karpenter provisioner status)

### Database Connection Issues

```bash
# Verify secret content
kubectl get secret backend-secrets -n kbp -o yaml

# Test connectivity from inside the cluster
kubectl run -it --rm debug --image=postgres:15 --restart=Never -- \
  psql "postgresql://postgres:PASSWORD@RDS_ENDPOINT:5432/DATABASE"  # pragma: allowlist secret
```

### HPA Not Scaling

```bash
kubectl top nodes
kubectl top pods -n kbp

# Restart Metrics Server if metrics are unavailable
kubectl rollout restart deployment metrics-server -n kube-system
```

### Cognito Login Issues

**Authorize request canceled (browser shows "canceled")**

The `KBR_COGNITO_DOMAIN` in the backend ConfigMap does not match the actual Cognito domain. Verify the real domain:

```bash
aws cognito-idp describe-user-pool \
  --user-pool-id <pool-id> \
  --region us-west-2 \
  --query 'UserPool.Domain' --output text
```

Update `KBR_COGNITO_DOMAIN` in `k8s/application/backend-configmap.yaml` to match, then reapply and restart:

```bash
kubectl apply -f k8s/application/backend-configmap.yaml
kubectl rollout restart deployment/backend -n kbp
```

**Cognito redirects with "redirect_mismatch" error**

The production callback URL is not registered in the Cognito app client. Add it:

```bash
aws cognito-idp update-user-pool-client \
  --user-pool-id <pool-id> \
  --client-id <client-id> \
  --callback-urls "https://<frontend-domain>/auth/cognito/callback" "http://localhost:9000/auth/cognito/callback" \
  --logout-urls "https://<frontend-domain>/" "http://localhost:9000/" \
  --allowed-o-auth-flows code \
  --allowed-o-auth-scopes email openid profile \
  --allowed-o-auth-flows-user-pool-client \
  --supported-identity-providers COGNITO \
  --region us-west-2
```

**No users can log in after fresh deployment**

The Cognito user pool is empty after initial creation. Create the first admin user (note: `--username` must not be an email since the pool uses email as alias):

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <pool-id> \
  --username admin \
  --user-attributes Name=email,Value=admin@example.com Name=email_verified,Value=true \
  --desired-delivery-mediums EMAIL \
  --region us-west-2
```

> If you deployed via `deploy-all.sh`, Step 1 handles this automatically.

### Global Accelerator -- "No Matching LB Found"

```bash
# Verify ALB names match Terraform vars
kubectl get ingress -n kbp -o jsonpath='{.items[*].metadata.annotations.alb\.ingress\.kubernetes\.io/load-balancer-name}'
aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName'
```

---

## Rollback

### Application Rollback

```bash
# Roll back deployment to previous revision
kubectl rollout undo deployment/backend -n kbp
kubectl rollout undo deployment/frontend -n kbp

# Verify
kubectl rollout status deployment/backend -n kbp
kubectl rollout status deployment/frontend -n kbp
```

### Configuration Rollback

```bash
# Restore previous secrets or configmaps, then apply
kubectl apply -f application/secrets.yaml
kubectl rollout restart deployment/backend -n kbp
kubectl rollout restart deployment/frontend -n kbp
```

### Infrastructure Rollback

```bash
cd iac-612674025488-us-west-2

# Revert to previous Terraform state (if saved)
terraform plan    # Review changes
terraform apply
```

### Global Accelerator Rollback

The recommended approach is to use the toggle command which handles everything automatically:

```bash
./deploy-all.sh --step 5   # detects GA is enabled, offers to disable
```

This will destroy the GA resource, regenerate configmaps (removing port 8443), restart pods, and display the ALB hostnames for DNS rollback.

If you need to rollback manually:
1. **DNS rollback** -- point DNS records back to the ALB hostnames.
2. **Disable module** -- set `enable_global_accelerator = false` in `terraform.tfvars` and run `terraform apply`.
3. **Regenerate configmaps** -- set `API_PORT_SUFFIX=""` and regenerate from templates, then `kubectl apply` and restart pods.

### Full Teardown

```bash
# Remove application
cd k8s && ./deploy.sh delete

# Destroy infrastructure (WARNING: destroys all data)
cd iac-612674025488-us-west-2
terraform destroy
```

# Kolya BR Proxy — Deployment SOP

This document covers the full deployment and teardown lifecycle on AWS EKS.

For local development setup, see the [Quick Start](../README.md#quick-start) section in README.

---

## Prerequisites

| Tool | Install |
|------|---------|
| AWS CLI v2 | `brew install awscli` |
| Terraform >= 1.0 | `brew install terraform` |
| kubectl | `brew install kubectl` |
| Helm | `brew install helm` |
| Docker | Docker Desktop / OrbStack |
| jq | `brew install jq` |

`deploy-all.sh` will verify all tools are installed before proceeding.

### AWS Account

- An AWS account with permissions to create VPC, EKS, RDS, IAM, ACM, Route 53, and ECR resources.
- AWS CLI configured with valid credentials (`aws configure`, SSO, or environment variables).
- A registered domain managed via Route 53 (default: `kolya.fun`).

---

## A. First-Time Deployment (New Account or New Region)

### 1. Configure AWS credentials

```bash
# Option 1: SSO profile
aws sso login --profile <your-profile>
export AWS_PROFILE=<your-profile>

# Option 2: environment variables
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...

# Set target region
export AWS_REGION=us-west-1   # or whatever region you want
```

### 2. Create ACM certificate

ACM cert must be in the same region as the ALBs. One cert can cover multiple domains via SAN.

```bash
aws acm request-certificate \
  --region $AWS_REGION \
  --domain-name kbp.kolya.fun \
  --subject-alternative-names "api.kbp.kolya.fun" \
  --validation-method DNS

# Add the DNS validation CNAME records to Route53, then wait for ISSUED status:
aws acm describe-certificate \
  --region $AWS_REGION \
  --certificate-arn <arn-from-above> \
  --query 'Certificate.Status'
```

Record the certificate ARN — you'll need it in Step 4 when `k8s/deploy.sh` prompts for it.

### 3. Create S3 bucket for Terraform state

```bash
aws s3 mb s3://tf-state-<account-id>-${AWS_REGION}-kolya --region $AWS_REGION
```

### 4. Run deployment

```bash
./deploy-all.sh --region $AWS_REGION
```

The script will interactively:

1. Validate AWS credentials and region
2. Prompt for S3 backend config (bucket name) — generates `iac/providers.tf` from template
3. Select or create a Terraform workspace
4. Run `terraform init` + `plan` + `apply` (VPC, EKS, RDS, etc.)
5. Deploy Helm charts (ALB Controller, Karpenter, Metrics Server)
6. Build and push Docker images to ECR
7. Deploy K8s application (prompts for domains, secrets via ESO, etc.)
8. Auto-enable WAF after ALBs are ready

### 5. (Optional) Enable Global Accelerator

```bash
./deploy-all.sh --step 5
```

---

## B. Deploying to a New Region (Already Have Another Region Running)

Each region uses its own Terraform state — no conflicts. Resource names include the region, so resources don't overlap.

**Key step: reset `providers.tf`**

If `iac/providers.tf` already exists (pointing to the old region's state bucket), delete it first:

```bash
rm iac/providers.tf
```

`deploy-all.sh` will then prompt you to configure the new region's S3 backend.

Then follow [Section A](#a-first-time-deployment-new-account-or-new-region) from Step 1.

---

## C. Day-to-Day Operations

```bash
# Run a specific step only
./deploy-all.sh --step 1       # Terraform only
./deploy-all.sh --step 2       # Helm only
./deploy-all.sh --step 3       # Docker build only
./deploy-all.sh --step 4       # K8s app deploy only
./deploy-all.sh --step 5       # Toggle Global Accelerator

# Skip confirmations (CI/CD)
./deploy-all.sh --yes

# K8s management
cd k8s && ./deploy.sh status   # View app status
cd k8s && ./deploy.sh logs     # View logs
cd k8s && ./deploy.sh update   # Update app config
```

---

## D. Switching Between Regions

`iac/providers.tf` determines which region's state Terraform operates on. To switch:

```bash
# 1. Delete current providers.tf
rm iac/providers.tf

# 2. Re-run deploy-all.sh for the target region
./deploy-all.sh --region <target-region>
# It will prompt for the new S3 backend config
```

Or manually:

```bash
# 1. Delete current providers.tf
rm iac/providers.tf

# 2. Regenerate providers.tf (edit from template)
cd iac
# Enter the target region's S3 bucket and region

# 3. Re-init Terraform
terraform init -reconfigure
```

---

## E. What `deploy-all.sh` Handles Automatically

| Concern | How it's handled |
|---------|-----------------|
| Account / region variables | Passed via `-var` flags (no tfvars file needed) |
| Terraform backend | Generated from `providers.tf.template` on first run |
| Terraform workspace | Interactive selection with confirmation at each step |
| WAF ordering | Disabled in Step 1, auto-enabled after ALBs in Step 4 |
| Global Accelerator | Disabled by default, toggle via `--step 5` |
| Cognito callback URLs | Configured from Terraform outputs after apply |
| ESO credentials | Pod Identity → ESO controller in `external-secrets` namespace |

---

## F. Destroy (Teardown)

Use `destroy.sh` to safely tear down all resources for a specific account, region, and workspace.

### Usage

```bash
# Interactive mode (prompts for everything)
./destroy.sh

# Specify account and region
./destroy.sh --account 123456789012 --region us-west-1

# Specify all parameters
./destroy.sh --account 123456789012 --region us-west-1 --workspace kolya
```

### What it does

1. **Verify AWS identity** — validates credentials, confirms account ID, region, and workspace
2. **Check EKS cluster** — if the cluster exists, connects and lists all resources in namespace `kbp`
3. **Clean up K8s resources** — deletes Ingress first (triggers ALB cleanup), waits 30s, then deletes ExternalSecrets, remaining resources, and namespace
4. **Configure Terraform backend** — prompts for S3 bucket if `providers.tf` is missing
5. **Verify workspace** — ensures the workspace exists in the backend
6. **Run `terraform plan -destroy`** — shows what will be destroyed
7. **Final confirmation** — requires typing `destroy` to proceed
8. **Run `terraform destroy`** — destroys all infrastructure

### Important notes

- K8s resources (especially Ingress/ALB) **must** be deleted before Terraform destroy, otherwise ALBs and target groups will block Terraform
- The script handles this automatically by cleaning up K8s resources first
- If the EKS cluster doesn't exist (already destroyed), K8s cleanup is skipped
- `--account` and `--region` have the highest priority; if provided they skip auto-detect but still verify against current credentials

### Example: Full teardown

```bash
# 1. Ensure AWS credentials are configured for the target account
export AWS_PROFILE=my-profile
aws sso login --profile my-profile

# 2. Run destroy
./destroy.sh --account 123456789012 --region us-west-1 --workspace kolya

# 3. (Optional) Delete the S3 state bucket if no longer needed
aws s3 rb s3://tf-state-123456789012-us-west-1-kolya --force --region us-west-1
```

---

## Prod vs Non-Prod Configuration Differences

The Terraform workspace (`prod` vs anything else) determines resource sizing:

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

---

## Global Accelerator (Step 5)

AWS Global Accelerator routes traffic over the AWS backbone network, reducing latency for geographically distant users by 40-60%.

> **Important:** Global Accelerator requires ALBs created in Step 4. Always run Steps 1-4 first.

### Enable / Disable

```bash
./deploy-all.sh --step 5
```

The script detects the current GA state and offers the appropriate action (enable or disable).

### Port Mapping

| Service | GA Port | ALB Port | Protocol |
|---------|---------|----------|----------|
| Frontend | 443 | 443 | HTTPS |
| Frontend | 80 | 80 | HTTP |
| API | 8443 | 443 | HTTPS |
| API | 8080 | 80 | HTTP |

### DNS with Global Accelerator

```bash
GA_DNS=$(terraform output -raw global_accelerator_dns_name)

# kbp.kolya.fun         CNAME  $GA_DNS
# ga-api.kbp.kolya.fun  CNAME  $GA_DNS
```

### Cost

| Component | Monthly Cost |
|-----------|-------------|
| Fixed fee | $18.00 |
| Data transfer (100 GB) | $1.50 |
| **Total (typical)** | **~$19.50** |

---

## DNS Configuration

After Ingress resources create ALBs, configure DNS records:

```bash
# Get ALB addresses
kubectl get ingress -n kbp
```

| Record | Type | Value |
|--------|------|-------|
| `kbp.kolya.fun` | CNAME | Frontend ALB hostname |
| `api.kbp.kolya.fun` | CNAME | API ALB hostname |

---

## Database Migrations

```bash
# Local
cd backend && uv run alembic upgrade head

# On EKS
kubectl exec -it deployment/backend -n kbp -- uv run alembic upgrade head

# Create a new migration
cd backend && uv run alembic revision --autogenerate -m "describe your change"
```

---

## Rollback

### Application Rollback

```bash
kubectl rollout undo deployment/backend -n kbp
kubectl rollout undo deployment/frontend -n kbp
```

### Global Accelerator Rollback

```bash
./deploy-all.sh --step 5   # detects GA is enabled, offers to disable
```

---

## Troubleshooting

### Ingress Not Creating ALB

```bash
kubectl get pods -n kube-system | grep aws-load-balancer
kubectl logs -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller
kubectl describe ingress -n kbp
```

### Pods Failing to Start

```bash
kubectl describe pod <pod-name> -n kbp
kubectl logs <pod-name> -n kbp
```

Common causes: image pull failure (ECR permissions), config error (check ESO sync), insufficient resources (check Karpenter).

### Database Connection Issues

```bash
kubectl get secret backend-secrets -n kbp -o yaml
kubectl run -it --rm debug --image=postgres:15 --restart=Never -- \
  psql "postgresql://postgres:PASSWORD@RDS_ENDPOINT:5432/DATABASE"  # pragma: allowlist secret
```

### HPA Not Scaling

```bash
kubectl top nodes
kubectl top pods -n kbp
kubectl rollout restart deployment metrics-server -n kube-system
```

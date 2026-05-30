# Kolya BR Proxy — Deployment SOP

This document covers the full deployment and teardown lifecycle on AWS EKS.

For local development setup, see the [Quick Start](../README.md#quick-start) section in README.

---

## Architecture Overview

| Component | Technology | Notes |
|-----------|-----------|-------|
| **Compute** | EKS (Standard or Auto Mode) | Standard: Managed Node Groups + Karpenter; Auto: fully AWS-managed |
| **Database** | Aurora PostgreSQL 16 (Provisioned or Serverless v2) | Provisioned: `db.r6g.large`; Serverless: 0.5–8 ACU auto-scaling |
| **Authentication** | AWS Cognito and/or Microsoft Entra ID | Dual SSO supported — choose one or both during Step 0 |
| **RBAC** | Entra ID Group Sync | Map Azure AD security groups → roles/permissions |
| **Secrets** | AWS Secrets Manager + ExternalSecret Operator | Zero secrets in git; ESO syncs to K8s pods |
| **Networking** | ALB (via AWS LB Controller) + optional Global Accelerator | WAF auto-enabled after ALBs are created |

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

### Authentication (choose during deployment)

| Option | Description |
|--------|-------------|
| **AWS Cognito** | Managed user pool with email/password sign-up. Good for self-service registration. |
| **Microsoft Entra ID** | Enterprise SSO via Azure AD. Supports Group Sync RBAC for org-level access control. |
| **Both** | Cognito for external users + Entra ID for internal team. Users can link accounts. |

`deploy-all.sh` Step 0 will prompt you to select the auth method. You can change it later via `./deploy-all.sh --configure auth`.

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

One certificate covers both domains (`kbp.kolya.fun` and `api.kbp.kolya.fun`) using Subject Alternative Names (SAN). The cert must be in the **same region** as the ALBs.

#### 2a. Request the certificate

```bash
CERT_ARN=$(aws acm request-certificate \
  --region $AWS_REGION \
  --domain-name kbp.kolya.fun \
  --subject-alternative-names "api.kbp.kolya.fun" \
  --validation-method DNS \
  --query 'CertificateArn' \
  --output text)

echo "Certificate ARN: $CERT_ARN"
```

#### 2b. Get DNS validation CNAME records

ACM generates one CNAME record per domain. Retrieve them:

```bash
aws acm describe-certificate \
  --region $AWS_REGION \
  --certificate-arn $CERT_ARN \
  --query 'Certificate.DomainValidationOptions[*].{Domain:DomainName,Name:ResourceRecord.Name,Value:ResourceRecord.Value}' \
  --output table
```

You will see two records (one for each domain):

```
-----------------------------------------------------------------------
|                       DescribeCertificate                           |
+---------------------+----------------------+------------------------+
|       Domain        |         Name         |         Value          |
+---------------------+----------------------+------------------------+
|  kbp.kolya.fun      |  _abc123.kbp...      |  _def456.acm-...       |
|  api.kbp.kolya.fun  |  _abc123.api.kbp...  |  _ghi789.acm-...       |
+---------------------+----------------------+------------------------+
```

> **Note:** Both domains may share the same CNAME record if they share the same root domain. In that case only one record needs to be added.

#### 2c. Add CNAME records to Route 53

Get your hosted zone ID first:

```bash
ZONE_ID=$(aws route53 list-hosted-zones-by-name \
  --dns-name kolya.fun \
  --query 'HostedZones[0].Id' \
  --output text | cut -d'/' -f3)

echo "Hosted Zone ID: $ZONE_ID"
```

Add each CNAME record returned in the previous step. Repeat for each unique record:

```bash
aws route53 change-resource-record-sets \
  --hosted-zone-id $ZONE_ID \
  --change-batch '{
    "Changes": [
      {
        "Action": "UPSERT",
        "ResourceRecordSet": {
          "Name": "<Name-from-table-above>",
          "Type": "CNAME",
          "TTL": 300,
          "ResourceRecords": [{"Value": "<Value-from-table-above>"}]
        }
      }
    ]
  }'
```

#### 2d. Wait for certificate to be issued

DNS propagation usually takes 1–5 minutes. Poll until status is `ISSUED`:

```bash
while true; do
  STATUS=$(aws acm describe-certificate \
    --region $AWS_REGION \
    --certificate-arn $CERT_ARN \
    --query 'Certificate.Status' \
    --output text)
  echo "$(date '+%H:%M:%S')  Status: $STATUS"
  [[ "$STATUS" == "ISSUED" ]] && break
  sleep 15
done
echo "Certificate issued: $CERT_ARN"
```

#### 2e. Save the ARN

Record `$CERT_ARN` — `deploy-all.sh` will prompt for it during Step 4 (K8s app deployment).

```bash
echo $CERT_ARN
# arn:aws:acm:us-west-1:612674025488:certificate/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

### 3. Create S3 bucket for Terraform state

```bash
aws s3 mb s3://tf-state-<account-id>-${AWS_REGION}-kolya --region $AWS_REGION
```

### 4. Run deployment

```bash
./deploy-all.sh --region $AWS_REGION
```

The script will interactively guide you through all steps:

| Step | What it does |
|------|-------------|
| Pre-flight | Validate AWS credentials, verify tools installed |
| **Step 0** | Configure `terraform.tfvars` — auto-detect account/region, choose **auth provider** (Cognito / Entra ID / Both), choose **ops mode** (Standard / Low-Ops), set domains |
| S3 backend | Prompt for state bucket name, generate `iac/providers.tf` |
| Workspace | Select or create Terraform workspace |
| **Step 1** | `terraform init` + `plan` + `apply` (VPC, EKS, Aurora PostgreSQL, Cognito, IAM) |
| **Step 2** | Deploy Helm charts (ALB Controller, Karpenter, Metrics Server, ESO, Redis). In Low-Ops mode, EKS built-in components are skipped. |
| **Step 3** | Build and push Docker images to ECR |
| **Step 4** | Deploy K8s app (ConfigMap, ExternalSecrets, Deployments, Ingress). Auto-enables WAF after ALBs are ready. |
| **Step 5** | (Optional) Toggle Global Accelerator |

#### Step Dependencies

```
Step 0 ─── writes ──→ terraform.tfvars (single source of truth)
  │
  ├──→ Step 1 reads tfvars ──→ terraform apply ──→ produces state + outputs
  │         │
  │         ├──→ Step 2 reads tfvars (EKS mode) + terraform output (cluster_name)
  │         │         │
  │         │         └──→ Step 4 reads terraform output (ECR URI, domain, etc.)
  │         │
  │         └──→ Step 3 reads terraform output (ECR repo URL)
  │
  └──→ Step 5 reads/writes tfvars + runs terraform apply
```

- **Step 0 → all other steps**: Step 0 writes `ops_low`, `enable_cognito`, `region`, etc. to `terraform.tfvars`. All subsequent steps read from this file.
- **Step 1 → Step 2/3/4**: Step 1 produces Terraform state. Step 2 reads `cluster_name` from `terraform output` to configure kubectl. Step 3 reads ECR repository URLs. Step 4 reads domain, DB endpoint, etc.
- **Step 2 → Step 4**: Helm charts (ESO, Redis, ALB Controller) must be running before app deployment.
- **Running a single step**: `--step N` skips prior steps but assumes they completed successfully. If Step 0 config changed, re-run Step 1 before Step 2.

After deployment, configure Microsoft Entra ID SSO if desired:

```bash
./deploy-all.sh --configure auth
```

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
./deploy-all.sh --step 0       # Configure terraform.tfvars
./deploy-all.sh --step 1       # Terraform only
./deploy-all.sh --step 2       # Helm only
./deploy-all.sh --step 3       # Docker build only
./deploy-all.sh --step 4       # K8s app deploy only
./deploy-all.sh --step 5       # Toggle Global Accelerator

# Configure authentication providers interactively
./deploy-all.sh --configure auth       # Add/update Microsoft or Cognito OAuth
./deploy-all.sh --configure secrets    # Update individual secrets in Secrets Manager
./deploy-all.sh --configure view       # View current configuration status

# Skip confirmations (CI/CD)
./deploy-all.sh --yes

# K8s management
cd k8s && ./deploy.sh status   # View app status
cd k8s && ./deploy.sh logs     # View logs
cd k8s && ./deploy.sh update   # Update app config
```

### Adding or Changing Auth Provider

You can add or switch auth providers at any time post-deployment:

```bash
./deploy-all.sh --configure auth
# Options:
#   1) Add/Update Microsoft Entra ID (SSO)  → prompts for Client ID, Secret, Tenant ID
#   2) Toggle Cognito on/off                → updates terraform.tfvars + runs terraform apply
#   3) View current auth status
```

The script writes credentials to AWS Secrets Manager → ExternalSecret syncs to pod → restart backend:

```bash
kubectl rollout restart deploy/backend -n kbp
```

> **First time setting up Entra ID?** You need to register an app in Azure Portal first. See [Microsoft Entra ID Configuration](#microsoft-entra-id-configuration) below for the full walkthrough (3 minutes).

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
| Account / region variables | Written to `terraform.tfvars` by Step 0 (single source of truth) |
| Domain names | Written to `terraform.tfvars` by Step 0; read by all subsequent steps |
| Terraform backend | Generated from `providers.tf.template` on first run |
| Terraform workspace | Interactive selection with confirmation at each step |
| WAF / GA / Cognito toggles | Persisted in `terraform.tfvars`; auto-detected from state by Step 0 |
| WAF ordering | Auto-enabled in `terraform.tfvars` after ALBs are ready in Step 4 |
| Global Accelerator | Disabled by default, toggle via `--step 5` (updates `terraform.tfvars`) |
| Cognito callback URLs | Auto-derived from `frontend_domain` in `terraform.tfvars` |
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
| **Backend Pod** | CPU request / limit | 250m / 500m | 500m / 1000m |
| | Memory request / limit | 384Mi / 768Mi | 512Mi / 1024Mi |
| | HPA replica range | 2–5 | 3–16 |
| **Frontend Pod** | CPU request / limit | 30m / 100m | 50m / 200m |
| | Memory request / limit | 64Mi / 128Mi | 128Mi / 256Mi |
| | HPA replica range | 1–2 | 2–4 |
| **EKS Core Nodes (Standard)** | Instance type | `t4g.small` | `t4g.medium` |
| | EBS volume size | 30 GB | 100 GB |
| **Karpenter Nodes (Standard)** | Instance category | `t` (t4g) | `m` (m7g) |
| | EBS volume size | 30 GB | 100 GB |
| | CPU limit | 100 | 1000 |
| | Memory limit | 100 Gi | 1000 Gi |
| **EKS Auto Mode NodePool** | Architecture | arm64 (Graviton) | arm64 (Graviton) |
| | Instance category | `c`, `m`, `r` (gen > 4) | `c`, `m`, `r` (gen > 4) |
| | CPU limit | 1000 | 1000 |
| | Memory limit | 1000 Gi | 1000 Gi |
| | Capacity type | On-Demand | On-Demand |
| **RDS Aurora PostgreSQL** | Instance (Standard ops) | `db.r6g.large` (2 vCPU / 16 GB) | `db.r6g.large` (2 vCPU / 16 GB) |
| | Instance (Low-Ops) | `db.serverless` (0.5–4 ACU) | `db.serverless` (0.5–8 ACU) |
| | Storage | Auto-scaling (10 GB → 128 TB) | Auto-scaling (10 GB → 128 TB) |
| | Performance Insights | Enabled | Enabled |
| | Deletion protection | Disabled | Enabled |
| | Backup retention (days) | 1 | 7 |
| | Preferred backup window | Not set | 03:00-04:00 UTC |
| | Copy tags to snapshot | No | Yes |
| | Skip final snapshot | Yes | No |
| | Apply immediately | Yes | No |
| | CloudWatch log exports | None | `["postgresql"]` |
| | Enhanced Monitoring (sec) | 0 (disabled) | 60 |
| **Cognito** | Advanced security mode | `AUDIT` | `ENFORCED` |
| | Deletion protection | Disabled | Enabled |
| **Global Accelerator** | Flow logs | Disabled | Enabled |

---

## Aurora PostgreSQL Storage & Sizing

The deployment supports two Aurora modes, selected via the **ops mode** choice in Step 0:

| Mode | Instance | Scaling | Best for |
|------|----------|---------|----------|
| **Provisioned** (Standard ops) | `db.r6g.large` (2 vCPU, 16 GB) | Fixed | Predictable workloads, stable cost |
| **Serverless v2** (Low-Ops) | `db.serverless` (0.5–8 ACU) | Auto-scaling in seconds | Elastic workloads, cost-optimized idle |

### Storage

Aurora storage is **fully managed and auto-scaling** in both modes — no disk size to configure:

- Starts at 10 GB, grows automatically in 10 GB increments
- Maximum: 128 TB
- Billing: $0.10/GB/month (only pay for actual usage)
- For an AI Gateway workload (metadata + usage records), expect < 10 GB for years

### Cost Comparison (us-west-2)

| Mode | Idle Cost | Active Cost |
|------|-----------|-------------|
| Provisioned `db.r6g.large` | ~$185/month (always on) | ~$185/month |
| Serverless v2 (min 0.5 ACU) | ~$44/month | Scales with load (up to ~$350/month at 8 ACU) |

### Provisioned: When to Scale Up

| Metric | Current (`db.r6g.large`) | Consider upgrading |
|--------|--------------------------|-------------------|
| Concurrent DB connections | Comfortable up to ~500 | > 500 → `db.r6g.xlarge` |
| CPU utilization (CloudWatch) | < 70% sustained | > 70% sustained |
| Freeable memory | > 4 GB | < 2 GB |

For the AI Gateway use case (lightweight CRUD, most latency is Bedrock-side), `db.r6g.large` is sufficient well into thousands of concurrent users.

### Serverless v2: ACU Configuration

| Environment | Min ACU | Max ACU | Notes |
|-------------|---------|---------|-------|
| Non-prod | 0.5 | 4 | Scales down to near-zero idle |
| Prod | 0.5 | 8 | Higher ceiling for traffic spikes |

1 ACU (Aurora Capacity Unit) ≈ 2 GB RAM + corresponding CPU. Scaling is automatic and takes seconds.

---

## Microsoft Entra ID Configuration

For full OAuth setup guide, see [OAuth Setup Guide](oauth-setup.md#microsoft-entra-id-azure-ad).

### Quick Setup (3 minutes)

**1. Azure Portal — Register App:**

```
Azure Portal > App registrations > New registration
  Name:              Kolya BR Proxy
  Account types:     Multi-tenant (any org + personal)
  Redirect URI:      Web → https://<frontend-domain>/auth/microsoft/callback
```

**2. Create Client Secret:**

```
Certificates & secrets > New client secret
  Description:   Kolya BR Proxy
  Expiry:        24 months
  → Copy the Value immediately (shown only once)
```

**3. API Permissions (Critical):**

```
API permissions > Add permission > Microsoft Graph > Delegated
  Add: openid, profile, email, User.Read, GroupMember.Read.All
  → Click "Grant admin consent for [tenant]"
```

> **Without admin consent for `GroupMember.Read.All`**, Entra Group Sync will fail with 403.

**4. Inject into cluster:**

```bash
./deploy-all.sh --configure auth
# Select "Add/Update Microsoft Entra ID (SSO)"
# Enter: Client ID, Client Secret, Tenant ID
# Script writes to AWS Secrets Manager → ESO syncs to pod
```

**5. Restart backend to pick up secrets:**

```bash
kubectl rollout restart deploy/backend -n kbp
```

### Entra ID Group Sync (RBAC via Azure Groups)

Group Sync maps Azure AD security groups → roles and permissions. When enabled, access is controlled by group membership:

```bash
# Enable group sync
KBR_MICROSOFT_ENABLE_GROUP_SYNC=true
```

**First login (bootstrap):** The first Microsoft user to log in automatically receives `super_admin` — this solves the chicken-and-egg problem. The bootstrap window closes immediately after.

**Setup flow:**
1. Create security groups in Azure Portal (e.g., `KBP-Admins`, `KBP-Users`)
2. Add members to groups in Azure Portal
3. First login to KBP → gets super_admin
4. Go to admin dashboard > **Entra Groups** > Add mappings:

| Entra Group ID (Object ID) | Display Name | Role | Priority |
|-----------------------------|--------------|------|----------|
| `aaaaaaaa-bbbb-...` | KBP-Admins | `super_admin` | 100 |
| `cccccccc-dddd-...` | KBP-Users | `admin` | 50 |

**Behavior:**
- User in a mapped group → assigned that group's role on every login
- User not in any mapped group → 403 denied
- Graph API unreachable → 503 denied (fail-closed design)
- User in multiple groups → highest priority wins

For detailed behavior matrix and troubleshooting, see [OAuth Setup — Entra ID Group Sync](oauth-setup.md#entra-id-group-sync).

---

## Backend Environment Variables

The following environment variables control backend runtime behavior. They can be set in the K8s ConfigMap or via ESO-managed secrets.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `KBR_STREAM_FIRST_CONTENT_TIMEOUT` | int | `600` | Seconds to wait for the first content chunk after a stream starts. If exceeded, the request fails over to the next region/model. Set to `0` to disable failover. |
| `KBR_STREAM_MODEL_FALLBACK_CHAIN` | string | `""` | Comma-separated model fallback chain for Level 2 degradation. Example: `anthropic.claude-opus-4-0-20250514-v1:0,anthropic.claude-sonnet-4-20250514-v1:0`. Empty string disables model degradation. |

---

## Log Format

Logs include a `[token_name]` field that identifies which API key produced each log line, enabling per-key filtering.

```
%(asctime)s - %(name)s - %(levelname)s - [%(token_name)s] %(message)s
```

When no token context is available the field shows `[-]`.

Example output:

```
2026-04-11 08:23:01,234 - app.api.v1.endpoints.chat - INFO - [my-team-key] streaming request to us-west-2
2026-04-11 08:23:05,678 - app.api.v1.endpoints.chat - WARNING - [-] health check from unknown caller
```

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

If Global Accelerator is enabled, point both records to the GA DNS name instead (see [DNS with Global Accelerator](#dns-with-global-accelerator)).

### Where to configure

| DNS Provider | How |
|-------------|-----|
| **Route 53** | Create CNAME records in your hosted zone (or use Alias records for zone apex) |
| **Cloudflare** | Add CNAME records in the Cloudflare dashboard. Set proxy status to "DNS only" (grey cloud) to avoid double-proxying with ALB |
| **Other providers** | Add CNAME records pointing to the ALB hostname (or GA DNS name) in your provider's DNS management console |

> **Note:** CNAME records cannot be used at the zone apex (e.g., `example.com` without subdomain). If your domain is a bare apex, use your provider's equivalent of an ALIAS/ANAME record, or add a subdomain prefix.

---

## Database Migrations

```bash
# Local
cd backend && uv run alembic upgrade head

# On EKS (uv is not in the production image, use python directly)
kubectl exec -it deployment/backend -n kbp -- alembic upgrade head

# Create a new migration (local only)
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

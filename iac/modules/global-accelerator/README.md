# AWS Global Accelerator Module

This module creates an AWS Global Accelerator to optimize global access latency for the Kolya BR Proxy application.

## Overview

AWS Global Accelerator provides static anycast IP addresses that route traffic over the AWS global network, reducing latency and improving availability for global users.

## Architecture

```
Global Users
     |
     v
[Global Accelerator]
(Static Anycast IPs)
     |
     v
[AWS Global Network]
     |
     v
[ALB in us-west-2]
     |
     v
[EKS Pods]
```

## Features

- **Static IP Addresses**: Two static anycast IPs that don't change
- **Global Routing**: Traffic routed via AWS backbone network
- **Health Checks**: Automatic endpoint health monitoring
- **Client IP Preservation**: Original client IP preserved for applications
- **Automatic Failover**: Traffic redirected to healthy endpoints
- **DDoS Protection**: Built-in AWS Shield Standard protection

## Port Mappings

The module creates separate listeners to avoid port conflicts:

| Service | Protocol | GA Port | ALB Port | Purpose |
|---------|----------|---------|----------|---------|
| Frontend | HTTPS | 443 | 443 | Main frontend traffic |
| Frontend | HTTP | 80 | 80 | HTTP to HTTPS redirect |
| API | HTTPS | 8443 | 443 | API traffic |
| API | HTTP | 8080 | 80 | HTTP to HTTPS redirect |

**Why different ports for API?**
- Global Accelerator requires unique port numbers per listener
- API uses ports 8443/8080 on GA, mapping to standard 443/80 on ALB
- This allows both services to use the same GA instance

## Prerequisites

### 1. ALB Naming Requirement (CRITICAL)

**IMPORTANT**: This module discovers ALBs by name. Your Ingress resources **MUST** explicitly specify ALB names using the annotation:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  annotations:
    alb.ingress.kubernetes.io/load-balancer-name: your-alb-name  # REQUIRED
```

**Why is this required?**

- **With annotation**: ALB Controller creates ALB with the specified name → Terraform can discover it
- **Without annotation**: ALB Controller generates random names like `k8s-kbp-kolyabr-a1b2c3d4` → Terraform cannot predict the name

**Verify your Ingress configuration:**

```bash
# Check if Ingress specifies ALB name
kubectl get ingress -n kbp kolya-br-proxy-frontend \
  -o jsonpath='{.metadata.annotations.alb\.ingress\.kubernetes\.io/load-balancer-name}'

# Expected output: kolya-br-proxy-frontend-alb

kubectl get ingress -n kbp kolya-br-proxy-api \
  -o jsonpath='{.metadata.annotations.alb\.ingress\.kubernetes\.io/load-balancer-name}'

# Expected output: kolya-br-proxy-api-alb
```

If the annotation is missing, you must add it to your Ingress resources before enabling Global Accelerator.

### 2. Deployment Prerequisites

ALBs must exist before enabling Global Accelerator.

1. Deploy Kubernetes infrastructure:
   ```bash
   terraform apply
   ```

2. Deploy Kubernetes resources (creates ALBs):
   ```bash
   cd ../k8s
   kubectl apply -f namespace.yaml
   kubectl apply -f ingress-api.yaml
   kubectl apply -f ingress-frontend.yaml
   ```

3. Wait for ALBs to be created (~2-3 minutes):
   ```bash
   kubectl get ingress -n kbp -w
   # Wait for ADDRESS column to show ALB DNS
   ```

4. Verify ALB names match the configuration:
   ```bash
   # Check actual ALB names in AWS
   aws elbv2 describe-load-balancers \
     --query 'LoadBalancers[?contains(LoadBalancerName, `kolya-br-proxy`)].LoadBalancerName' \
     --output table

   # Expected output:
   # kolya-br-proxy-api-alb
   # kolya-br-proxy-frontend-alb
   ```

5. Verify names match Terraform configuration:
   ```bash
   # Check Terraform default values
   grep -A2 "ga_.*_alb_name" iac-612674025488-us-west-2/variables.tf

   # If names don't match, override in terraform.tfvars:
   # ga_frontend_alb_name = "actual-frontend-alb-name"
   # ga_api_alb_name      = "actual-api-alb-name"
   ```

## Usage

### Enable Global Accelerator

Add to your `terraform.tfvars`:

```hcl
enable_global_accelerator = true

# Optional: Override default ALB names if different
ga_frontend_alb_name = "kolya-br-proxy-frontend-alb"
ga_api_alb_name      = "kolya-br-proxy-api-alb"
```

### Apply Configuration

```bash
terraform apply
```

### Get Global Accelerator Information

```bash
# Get static IPs and DNS
terraform output global_accelerator_static_ips
terraform output global_accelerator_dns_name

# Get usage instructions
terraform output global_accelerator_usage_instructions
```

## DNS Configuration

After deploying Global Accelerator, update your DNS:

### Option 1: CNAME to GA DNS (Recommended)

```
kbp.kolya.fun          CNAME  <ga-dns-name>
api.kbp.kolya.fun      CNAME  <ga-dns-name>
```

**Access URLs:**
- Frontend: `https://kbp.kolya.fun:443`
- API: `https://api.kbp.kolya.fun:8443`

### Option 2: A Records to Static IPs

```
kbp.kolya.fun          A      <static-ip-1>
kbp.kolya.fun          A      <static-ip-2>
api.kbp.kolya.fun      A      <static-ip-1>
api.kbp.kolya.fun      A      <static-ip-2>
```

**Note:** With this option, you'll need to use non-standard ports for API (8443/8080).

### Option 3: Dual Stack (Both ALB and GA)

Keep existing ALB DNS records and add GA as secondary:

```
# Direct ALB access (standard ports)
alb.kbp.kolya.fun      CNAME  <alb-dns>
alb-api.kbp.kolya.fun  CNAME  <api-alb-dns>

# Global Accelerator access (optimized routing)
kbp.kolya.fun          CNAME  <ga-dns-name>
api.kbp.kolya.fun      CNAME  <ga-dns-name>
```

This allows gradual migration and fallback.

## Security Considerations

### ALB Security Groups

Global Accelerator uses specific IP ranges to communicate with ALBs. Your ALB security groups should allow:

1. **Direct Internet Traffic** (if keeping ALB public):
   ```hcl
   ingress {
     from_port   = 443
     to_port     = 443
     protocol    = "tcp"
     cidr_blocks = ["0.0.0.0/0"]
   }
   ```

2. **Global Accelerator IPs** (if restricting ALB):
   ```bash
   # Get GA IP ranges
   aws ec2 describe-managed-prefix-lists \
     --query "PrefixLists[?PrefixListName=='com.amazonaws.global-accelerator'].PrefixListId"
   ```

### Client IP Preservation

The module enables `client_ip_preservation`, so your application receives:
- Original client IP in `X-Forwarded-For` header
- Client IP preserved at network layer

Configure your application to trust these IPs.

## Health Checks

Health checks are configured as follows:

| Parameter | Value | Description |
|-----------|-------|-------------|
| Interval | 30 seconds | How often to check |
| Threshold | 3 | Checks before marking healthy/unhealthy |
| Protocol | HTTPS/HTTP | Matches ALB listener |
| Path | `/` (frontend), `/health/` (API) | Health check endpoints |

**Monitor health**: AWS Console → Global Accelerator → Endpoints

## Traffic Control

### Traffic Dial

Control traffic percentage to endpoints (0-100%):

```hcl
traffic_dial_percentage = 50  # Send only 50% of traffic
```

Use cases:
- Gradual rollout
- Blue/green deployments
- Maintenance windows

### Endpoint Weights

Currently set to 100 (all traffic to primary endpoint). For multi-region:

```hcl
endpoint_configuration {
  endpoint_id = var.frontend_alb_arn
  weight      = 80  # 80% traffic
}

endpoint_configuration {
  endpoint_id = var.frontend_alb_arn_secondary
  weight      = 20  # 20% traffic
}
```

## Monitoring

### CloudWatch Metrics

Global Accelerator publishes metrics to CloudWatch:

- `NewFlowCount`: New connections
- `ProcessedBytesIn/Out`: Data transferred
- `HealthyEndpointCount`: Number of healthy endpoints

### Flow Logs

Enable flow logs for production:

```hcl
enable_global_accelerator = true
# Flow logs automatically enabled for prod workspace
```

Flow logs capture:
- Source/destination IPs
- Ports and protocols
- Bytes transferred
- Actions (accept/reject)

## Cost Considerations

AWS Global Accelerator pricing:

1. **Fixed Fee**: $0.025/hour per accelerator (~$18/month)
2. **Data Transfer Premium**: $0.015/GB (in addition to standard data transfer)
3. **No charge for**: Health checks, DDoS protection

**Cost optimization:**
- Single GA instance serves both frontend and API (different ports)
- Disable for non-production environments
- Monitor data transfer costs

## Performance Testing

### Compare Latency

Test from different global locations:

```bash
# Direct ALB access
curl -w "@curl-format.txt" -o /dev/null -s https://alb.kbp.kolya.fun

# Global Accelerator access
curl -w "@curl-format.txt" -o /dev/null -s https://kbp.kolya.fun
```

**curl-format.txt:**
```
time_namelookup:  %{time_namelookup}\n
time_connect:     %{time_connect}\n
time_appconnect:  %{time_appconnect}\n
time_total:       %{time_total}\n
```

Expected improvements:
- **Nearby users** (<1000km): 5-10% faster
- **Regional users** (1000-3000km): 20-40% faster
- **Global users** (>3000km): 40-60% faster

## Disaster Recovery

### Endpoint Failover

GA automatically detects unhealthy endpoints and stops routing traffic:

1. Health check fails for 3 consecutive checks (90 seconds)
2. GA marks endpoint unhealthy
3. Traffic redirected to healthy endpoints (if multi-region)
4. Automatic recovery when health restored

### Manual Failover

```bash
# Reduce traffic to endpoint (for maintenance)
aws globalaccelerator update-endpoint-group \
  --endpoint-group-arn <arn> \
  --traffic-dial-percentage 0
```

## Troubleshooting

### ALB Not Found

```
Error: no matching LB found
```

**Cause**: Terraform cannot find ALBs with the specified names.

**Diagnosis Steps:**

1. **Check if ALBs exist:**
   ```bash
   kubectl get ingress -n kbp
   # Verify ADDRESS column is populated (not <pending>)

   aws elbv2 describe-load-balancers \
     --query 'LoadBalancers[].LoadBalancerName' \
     --output table
   ```

2. **Check if Ingress specifies ALB names:**
   ```bash
   # Frontend
   kubectl get ingress kolya-br-proxy-frontend -n kbp \
     -o jsonpath='{.metadata.annotations.alb\.ingress\.kubernetes\.io/load-balancer-name}'

   # API
   kubectl get ingress kolya-br-proxy-api -n kbp \
     -o jsonpath='{.metadata.annotations.alb\.ingress\.kubernetes\.io/load-balancer-name}'
   ```

   **If empty**: ALB Controller is using auto-generated names. You must either:
   - Option A: Add `load-balancer-name` annotation to Ingress and recreate ALB
   - Option B: Find actual ALB names and update Terraform variables

3. **Find actual ALB names (if annotation missing):**
   ```bash
   # Get ALB DNS from Ingress status
   kubectl get ingress -n kbp -o jsonpath='{.items[*].status.loadBalancer.ingress[0].hostname}'

   # Extract ALB name from DNS (e.g., k8s-kbp-kolyabr-abc123.region.elb.amazonaws.com)
   kubectl get ingress kolya-br-proxy-frontend -n kbp \
     -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' | cut -d'-' -f1-4
   ```

4. **Check name matching:**
   ```bash
   # Compare Terraform configuration with actual ALB names
   echo "Terraform expects:"
   terraform console <<< "var.ga_frontend_alb_name"
   terraform console <<< "var.ga_api_alb_name"

   echo "AWS has:"
   aws elbv2 describe-load-balancers \
     --query 'LoadBalancers[?contains(LoadBalancerName, `kolya`)].LoadBalancerName'
   ```

**Solutions:**

**Solution 1: Update Terraform variables (if names differ)**
```hcl
# terraform.tfvars
ga_frontend_alb_name = "k8s-kbp-kolyabrf-a1b2c3d4"  # Actual name from AWS
ga_api_alb_name      = "k8s-kbp-kolyabra-e5f6g7h8"  # Actual name from AWS
```

**Solution 2: Add annotation to Ingress (recommended for new deployments)**
```bash
# This will recreate the ALB with the specified name
kubectl annotate ingress kolya-br-proxy-frontend -n kbp \
  alb.ingress.kubernetes.io/load-balancer-name=kolya-br-proxy-frontend-alb \
  --overwrite

kubectl annotate ingress kolya-br-proxy-api -n kbp \
  alb.ingress.kubernetes.io/load-balancer-name=kolya-br-proxy-api-alb \
  --overwrite

# Wait for new ALBs to be created (~3 minutes)
kubectl get ingress -n kbp -w
```

**Solution 3: Manually provide ARNs (bypass name discovery)**
```hcl
# In module call
module "global_accelerator" {
  ...
  frontend_alb_arn = "arn:aws:elasticloadbalancing:us-west-2:123456789012:loadbalancer/app/k8s-kbp-kolyabrf-a1b2c3d4/1234567890abcdef"
  api_alb_arn      = "arn:aws:elasticloadbalancing:us-west-2:123456789012:loadbalancer/app/k8s-kbp-kolyabra-e5f6g7h8/1234567890abcdef"

  # Leave names empty to skip name-based discovery
  frontend_alb_name = ""
  api_alb_name      = ""
}
```

5. **Verify region:**
   ```bash
   # Ensure ALBs are in the same region as Terraform
   aws elbv2 describe-load-balancers \
     --query 'LoadBalancers[?contains(LoadBalancerName, `kolya`)].{Name:LoadBalancerName,Region:AvailabilityZones[0].ZoneName}'
   ```

### Health Checks Failing

**Symptoms:** Endpoints marked unhealthy

**Troubleshooting:**
1. Check ALB target health: AWS Console → EC2 → Target Groups
2. Verify health check paths are accessible
3. Check security groups allow GA traffic
4. Review ALB access logs

### High Latency

**Expected:** Latency should be lower than direct ALB access

**If higher:**
1. Check endpoint health
2. Verify routing to correct region
3. Test from multiple locations
4. Compare with direct ALB access

### Port Conflicts

**Issue:** API accessible on non-standard ports (8443/8080)

**Solutions:**
1. **Application proxy:** Set up reverse proxy to map ports
2. **Client-side handling:** Update API clients to use port 8443
3. **Separate GA:** Create second GA for API (increases cost)

## Migration Strategy

### Phase 1: Deploy GA Alongside ALB

1. Keep existing ALB DNS records
2. Deploy Global Accelerator
3. Test GA endpoints separately
4. Monitor performance and health

### Phase 2: Gradual Traffic Shift

1. Add GA DNS as secondary records
2. Shift small percentage of users to GA
3. Monitor metrics and errors
4. Gradually increase traffic

### Phase 3: Full Cutover

1. Update primary DNS to GA
2. Keep ALB DNS as fallback
3. Monitor for issues
4. Remove old DNS after verification

### Rollback Plan

If issues occur:

1. **Immediate:** Update DNS back to ALB (5-60 min propagation)
2. **Traffic dial:** Reduce GA traffic to 0% (instant)
3. **Disable module:** Set `enable_global_accelerator = false` and `terraform apply`

## Multi-Region Setup (Future)

To expand to multiple regions:

1. Deploy EKS clusters in additional regions
2. Add endpoint configurations for each region:
   ```hcl
   endpoint_configuration {
     endpoint_id = var.frontend_alb_arn_us_west
     weight      = 60
   }

   endpoint_configuration {
     endpoint_id = var.frontend_alb_arn_eu_west
     weight      = 40
   }
   ```
3. Configure health checks for each region
4. Test failover scenarios

## Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `enable_global_accelerator` | Enable Global Accelerator | `false` |
| `ga_frontend_alb_name` | Frontend ALB name for discovery | `kolya-br-proxy-frontend-alb` |
| `ga_api_alb_name` | API ALB name for discovery | `kolya-br-proxy-api-alb` |

## Outputs

| Output | Description |
|--------|-------------|
| `accelerator_dns_name` | DNS name of Global Accelerator |
| `accelerator_static_ips` | Static anycast IP addresses |
| `usage_instructions` | Setup and configuration instructions |

## References

- [AWS Global Accelerator Documentation](https://docs.aws.amazon.com/global-accelerator/)
- [Best Practices](https://docs.aws.amazon.com/global-accelerator/latest/dg/best-practices.html)
- [Pricing](https://aws.amazon.com/global-accelerator/pricing/)
- [Global Accelerator vs CloudFront](https://aws.amazon.com/global-accelerator/faqs/#General)

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
|------|---------|
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | >= 1.0 |
| <a name="requirement_aws"></a> [aws](#requirement\_aws) | >= 5.0 |

## Providers

| Name | Version |
|------|---------|
| <a name="provider_aws"></a> [aws](#provider\_aws) | >= 5.0 |

## Modules

No modules.

## Resources

| Name | Type |
|------|------|
| [aws_globalaccelerator_accelerator.main](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/globalaccelerator_accelerator) | resource |
| [aws_globalaccelerator_endpoint_group.api_http](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/globalaccelerator_endpoint_group) | resource |
| [aws_globalaccelerator_endpoint_group.api_https](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/globalaccelerator_endpoint_group) | resource |
| [aws_globalaccelerator_endpoint_group.frontend_http](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/globalaccelerator_endpoint_group) | resource |
| [aws_globalaccelerator_endpoint_group.frontend_https](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/globalaccelerator_endpoint_group) | resource |
| [aws_globalaccelerator_listener.api_http](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/globalaccelerator_listener) | resource |
| [aws_globalaccelerator_listener.api_https](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/globalaccelerator_listener) | resource |
| [aws_globalaccelerator_listener.frontend_http](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/globalaccelerator_listener) | resource |
| [aws_globalaccelerator_listener.frontend_https](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/globalaccelerator_listener) | resource |
| [aws_lb.api](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/lb) | data source |
| [aws_lb.frontend](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/lb) | data source |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_api_alb_arn"></a> [api\_alb\_arn](#input\_api\_alb\_arn) | ARN of the API ALB (leave empty to auto-discover by name) | `string` | `""` | no |
| <a name="input_api_alb_name"></a> [api\_alb\_name](#input\_api\_alb\_name) | Name of the API ALB for auto-discovery | `string` | `"kolya-br-proxy-api-alb"` | no |
| <a name="input_api_health_check_path"></a> [api\_health\_check\_path](#input\_api\_health\_check\_path) | Health check path for API ALB | `string` | `"/health/"` | no |
| <a name="input_default_tags"></a> [default\_tags](#input\_default\_tags) | Default tags to apply to resources | `map(string)` | `{}` | no |
| <a name="input_flow_logs_enabled"></a> [flow\_logs\_enabled](#input\_flow\_logs\_enabled) | Enable flow logs for Global Accelerator | `bool` | `false` | no |
| <a name="input_flow_logs_s3_bucket"></a> [flow\_logs\_s3\_bucket](#input\_flow\_logs\_s3\_bucket) | S3 bucket for flow logs (required if flow\_logs\_enabled is true) | `string` | `""` | no |
| <a name="input_flow_logs_s3_prefix"></a> [flow\_logs\_s3\_prefix](#input\_flow\_logs\_s3\_prefix) | S3 prefix for flow logs | `string` | `"global-accelerator-logs/"` | no |
| <a name="input_frontend_alb_arn"></a> [frontend\_alb\_arn](#input\_frontend\_alb\_arn) | ARN of the frontend ALB (leave empty to auto-discover by name) | `string` | `""` | no |
| <a name="input_frontend_alb_name"></a> [frontend\_alb\_name](#input\_frontend\_alb\_name) | Name of the frontend ALB for auto-discovery | `string` | `"kolya-br-proxy-frontend-alb"` | no |
| <a name="input_frontend_health_check_path"></a> [frontend\_health\_check\_path](#input\_frontend\_health\_check\_path) | Health check path for frontend ALB | `string` | `"/"` | no |
| <a name="input_health_check_interval"></a> [health\_check\_interval](#input\_health\_check\_interval) | Health check interval in seconds (10 or 30) | `number` | `30` | no |
| <a name="input_health_check_threshold"></a> [health\_check\_threshold](#input\_health\_check\_threshold) | Number of consecutive health checks before marking endpoint healthy/unhealthy | `number` | `3` | no |
| <a name="input_project_name_alias"></a> [project\_name\_alias](#input\_project\_name\_alias) | The short name of the project | `string` | n/a | yes |
| <a name="input_region"></a> [region](#input\_region) | AWS region where ALBs are deployed | `string` | n/a | yes |
| <a name="input_traffic_dial_percentage"></a> [traffic\_dial\_percentage](#input\_traffic\_dial\_percentage) | Percentage of traffic to dial to the endpoint group (0-100) | `number` | `100` | no |
| <a name="input_workspace"></a> [workspace](#input\_workspace) | The workspace/environment name | `string` | n/a | yes |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_accelerator_arn"></a> [accelerator\_arn](#output\_accelerator\_arn) | The ARN of the Global Accelerator |
| <a name="output_accelerator_dns_name"></a> [accelerator\_dns\_name](#output\_accelerator\_dns\_name) | The DNS name of the Global Accelerator |
| <a name="output_accelerator_hosted_zone_id"></a> [accelerator\_hosted\_zone\_id](#output\_accelerator\_hosted\_zone\_id) | The hosted zone ID of the Global Accelerator |
| <a name="output_accelerator_id"></a> [accelerator\_id](#output\_accelerator\_id) | The ID of the Global Accelerator |
| <a name="output_accelerator_static_ips"></a> [accelerator\_static\_ips](#output\_accelerator\_static\_ips) | List of static IP addresses assigned to the Global Accelerator |
| <a name="output_api_http_listener_arn"></a> [api\_http\_listener\_arn](#output\_api\_http\_listener\_arn) | ARN of the API HTTP listener (port 8080) |
| <a name="output_api_https_listener_arn"></a> [api\_https\_listener\_arn](#output\_api\_https\_listener\_arn) | ARN of the API HTTPS listener (port 8443) |
| <a name="output_frontend_http_listener_arn"></a> [frontend\_http\_listener\_arn](#output\_frontend\_http\_listener\_arn) | ARN of the frontend HTTP listener |
| <a name="output_frontend_https_listener_arn"></a> [frontend\_https\_listener\_arn](#output\_frontend\_https\_listener\_arn) | ARN of the frontend HTTPS listener |
| <a name="output_usage_instructions"></a> [usage\_instructions](#output\_usage\_instructions) | Instructions for using Global Accelerator |
<!-- END_TF_DOCS -->

# Kolya BR Proxy -- Terraform Infrastructure

Terraform IaC for the Kolya BR Proxy project on AWS EKS.

> **IMPORTANT**: Run all Terraform commands from this directory (`iac-612674025488-us-west-2/`), not from the project root.

## What Terraform Manages

- VPC (`10.1.8.0/22`), subnets, routing
- EKS cluster with Karpenter auto-scaling
- RDS Aurora PostgreSQL
- IAM roles, policies, Pod Identity Associations
- Security groups, ACM certificates, Route 53
- Global Accelerator (optional)

Helm charts and Kubernetes resources are managed separately -- see `k8s/`.

## Quick Start

```bash
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your account/region

terraform workspace new non-prod   # or: terraform workspace select non-prod
terraform init
terraform plan
terraform apply
```

After Terraform completes, proceed to Kubernetes add-ons and application deployment.

## Documentation

- **[Deployment Guide](../docs/deployment.md)** -- end-to-end deployment instructions (Terraform + K8s + application)
- **[Architecture](../docs/architecture.md)** -- system design and infrastructure overview

## Terraform Documentation

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
|------|---------|
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | >= 1.0 |
| <a name="requirement_aws"></a> [aws](#requirement\_aws) | ~> 6.20 |
| <a name="requirement_random"></a> [random](#requirement\_random) | ~> 3.6 |
| <a name="requirement_tls"></a> [tls](#requirement\_tls) | ~> 4.0 |

## Providers

No providers.

## Modules

| Name | Source | Version |
|------|--------|---------|
| <a name="module_cognito"></a> [cognito](#module\_cognito) | ./modules/cognito | n/a |
| <a name="module_eks_addons"></a> [eks\_addons](#module\_eks\_addons) | ./modules/eks-addons | n/a |
| <a name="module_eks_karpenter"></a> [eks\_karpenter](#module\_eks\_karpenter) | ./modules/eks-karpenter | n/a |
| <a name="module_global_accelerator"></a> [global\_accelerator](#module\_global\_accelerator) | ./modules/global-accelerator | n/a |
| <a name="module_rds_aurora_postgresql"></a> [rds\_aurora\_postgresql](#module\_rds\_aurora\_postgresql) | ./modules/rds-aurora-postgresql | n/a |
| <a name="module_vpc"></a> [vpc](#module\_vpc) | ./modules/vpc | n/a |
| <a name="module_waf"></a> [waf](#module\_waf) | ./modules/waf | n/a |

## Resources

No resources.

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_account"></a> [account](#input\_account) | AWS account | `string` | n/a | yes |
| <a name="input_api_domain"></a> [api\_domain](#input\_api\_domain) | API domain (e.g. api.kbp.kolya.fun) | `string` | `""` | no |
| <a name="input_cognito_access_token_validity"></a> [cognito\_access\_token\_validity](#input\_cognito\_access\_token\_validity) | Cognito access token validity in minutes | `number` | `60` | no |
| <a name="input_cognito_allowed_email_domains"></a> [cognito\_allowed\_email\_domains](#input\_cognito\_allowed\_email\_domains) | List of allowed email domains for Cognito user registration (e.g., ['example.com', 'company.com']) | `list(string)` | <pre>[<br/>  "amazon.com"<br/>]</pre> | no |
| <a name="input_cognito_callback_urls"></a> [cognito\_callback\_urls](#input\_cognito\_callback\_urls) | List of allowed callback URLs for Cognito OAuth | `list(string)` | <pre>[<br/>  "http://localhost:9000/auth/cognito/callback"<br/>]</pre> | no |
| <a name="input_cognito_id_token_validity"></a> [cognito\_id\_token\_validity](#input\_cognito\_id\_token\_validity) | Cognito ID token validity in minutes | `number` | `60` | no |
| <a name="input_cognito_logout_urls"></a> [cognito\_logout\_urls](#input\_cognito\_logout\_urls) | List of allowed logout URLs for Cognito | `list(string)` | <pre>[<br/>  "http://localhost:9000"<br/>]</pre> | no |
| <a name="input_cognito_refresh_token_validity"></a> [cognito\_refresh\_token\_validity](#input\_cognito\_refresh\_token\_validity) | Cognito refresh token validity in days | `number` | `30` | no |
| <a name="input_eks_version"></a> [eks\_version](#input\_eks\_version) | EKS Kubernetes version | `string` | `"1.35"` | no |
| <a name="input_enable_cognito"></a> [enable\_cognito](#input\_enable\_cognito) | Enable AWS Cognito for user authentication | `bool` | `true` | no |
| <a name="input_enable_global_accelerator"></a> [enable\_global\_accelerator](#input\_enable\_global\_accelerator) | Enable AWS Global Accelerator for reduced latency | `bool` | `false` | no |
| <a name="input_enable_waf"></a> [enable\_waf](#input\_enable\_waf) | Enable AWS WAF for rate limiting and security protection on ALBs | `bool` | `false` | no |
| <a name="input_frontend_domain"></a> [frontend\_domain](#input\_frontend\_domain) | Frontend domain (e.g. kbp.kolya.fun) | `string` | `""` | no |
| <a name="input_ga_api_alb_name"></a> [ga\_api\_alb\_name](#input\_ga\_api\_alb\_name) | Name of the API ALB for Global Accelerator (auto-discovery) | `string` | `"kolya-br-proxy-api-alb"` | no |
| <a name="input_ga_frontend_alb_name"></a> [ga\_frontend\_alb\_name](#input\_ga\_frontend\_alb\_name) | Name of the frontend ALB for Global Accelerator (auto-discovery) | `string` | `"kolya-br-proxy-frontend-alb"` | no |
| <a name="input_project_name"></a> [project\_name](#input\_project\_name) | The name of the project | `string` | `"kolya-br-proxy"` | no |
| <a name="input_project_name_alias"></a> [project\_name\_alias](#input\_project\_name\_alias) | The short name of the project | `string` | `"kbr-proxy"` | no |
| <a name="input_region"></a> [region](#input\_region) | AWS region | `string` | n/a | yes |
| <a name="input_vpc_cidr"></a> [vpc\_cidr](#input\_vpc\_cidr) | CIDR block for VPC | `string` | `"10.1.8.0/22"` | no |
| <a name="input_waf_api_alb_name"></a> [waf\_api\_alb\_name](#input\_waf\_api\_alb\_name) | Name of the API ALB for WAF association (auto-discovery) | `string` | `"kolya-br-proxy-api-alb"` | no |
| <a name="input_waf_frontend_alb_name"></a> [waf\_frontend\_alb\_name](#input\_waf\_frontend\_alb\_name) | Name of the frontend ALB for WAF association (auto-discovery) | `string` | `"kolya-br-proxy-frontend-alb"` | no |
| <a name="input_waf_rate_limit_auth"></a> [waf\_rate\_limit\_auth](#input\_waf\_rate\_limit\_auth) | WAF rate limit per IP for /admin/auth/* (requests per 5 minutes) | `number` | `20` | no |
| <a name="input_waf_rate_limit_chat"></a> [waf\_rate\_limit\_chat](#input\_waf\_rate\_limit\_chat) | WAF rate limit per IP for inference endpoints: /v1/chat/completions, /v1/messages, /v1beta/models/ (requests per 5 minutes) | `number` | `300` | no |
| <a name="input_waf_rate_limit_global"></a> [waf\_rate\_limit\_global](#input\_waf\_rate\_limit\_global) | WAF global rate limit per IP (requests per 5 minutes) | `number` | `2000` | no |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_api_domain"></a> [api\_domain](#output\_api\_domain) | API domain |
| <a name="output_backend_secrets_manager_name"></a> [backend\_secrets\_manager\_name](#output\_backend\_secrets\_manager\_name) | Name of the Secrets Manager secret for backend |
| <a name="output_cluster_arn"></a> [cluster\_arn](#output\_cluster\_arn) | EKS cluster ARN |
| <a name="output_cluster_endpoint"></a> [cluster\_endpoint](#output\_cluster\_endpoint) | Endpoint for EKS control plane |
| <a name="output_cluster_id"></a> [cluster\_id](#output\_cluster\_id) | EKS cluster ID |
| <a name="output_cluster_name"></a> [cluster\_name](#output\_cluster\_name) | EKS cluster name |
| <a name="output_cluster_security_group_id"></a> [cluster\_security\_group\_id](#output\_cluster\_security\_group\_id) | Security group ids attached to the cluster control plane |
| <a name="output_cluster_version"></a> [cluster\_version](#output\_cluster\_version) | The Kubernetes version for the EKS cluster |
| <a name="output_cognito_app_client_id"></a> [cognito\_app\_client\_id](#output\_cognito\_app\_client\_id) | ID of the Cognito App Client |
| <a name="output_cognito_app_client_secret"></a> [cognito\_app\_client\_secret](#output\_cognito\_app\_client\_secret) | Secret of the Cognito App Client (sensitive) |
| <a name="output_cognito_configuration_instructions"></a> [cognito\_configuration\_instructions](#output\_cognito\_configuration\_instructions) | Instructions for configuring Cognito in the backend |
| <a name="output_cognito_domain"></a> [cognito\_domain](#output\_cognito\_domain) | Cognito User Pool domain prefix |
| <a name="output_cognito_enabled"></a> [cognito\_enabled](#output\_cognito\_enabled) | Whether Cognito is enabled |
| <a name="output_cognito_user_pool_domain_url"></a> [cognito\_user\_pool\_domain\_url](#output\_cognito\_user\_pool\_domain\_url) | Full URL of the Cognito User Pool domain |
| <a name="output_cognito_user_pool_id"></a> [cognito\_user\_pool\_id](#output\_cognito\_user\_pool\_id) | ID of the Cognito User Pool |
| <a name="output_eks_nodes_security_group_id"></a> [eks\_nodes\_security\_group\_id](#output\_eks\_nodes\_security\_group\_id) | ID of the EKS nodes security group |
| <a name="output_frontend_domain"></a> [frontend\_domain](#output\_frontend\_domain) | Frontend domain |
| <a name="output_global_accelerator_dns_name"></a> [global\_accelerator\_dns\_name](#output\_global\_accelerator\_dns\_name) | DNS name of the Global Accelerator |
| <a name="output_global_accelerator_enabled"></a> [global\_accelerator\_enabled](#output\_global\_accelerator\_enabled) | Whether Global Accelerator is enabled |
| <a name="output_global_accelerator_static_ips"></a> [global\_accelerator\_static\_ips](#output\_global\_accelerator\_static\_ips) | Static IP addresses of the Global Accelerator |
| <a name="output_global_accelerator_usage_instructions"></a> [global\_accelerator\_usage\_instructions](#output\_global\_accelerator\_usage\_instructions) | Instructions for using Global Accelerator |
| <a name="output_karpenter_node_iam_role_name"></a> [karpenter\_node\_iam\_role\_name](#output\_karpenter\_node\_iam\_role\_name) | Name of the Karpenter node IAM role |
| <a name="output_karpenter_queue_name"></a> [karpenter\_queue\_name](#output\_karpenter\_queue\_name) | Name of the SQS queue used by Karpenter |
| <a name="output_karpenter_service_account"></a> [karpenter\_service\_account](#output\_karpenter\_service\_account) | Name of the Karpenter service account |
| <a name="output_private_subnet_ids"></a> [private\_subnet\_ids](#output\_private\_subnet\_ids) | List of IDs of private subnets |
| <a name="output_public_subnet_ids"></a> [public\_subnet\_ids](#output\_public\_subnet\_ids) | List of IDs of public subnets |
| <a name="output_rds_cluster_database_name"></a> [rds\_cluster\_database\_name](#output\_rds\_cluster\_database\_name) | RDS Aurora cluster database name |
| <a name="output_rds_cluster_endpoint"></a> [rds\_cluster\_endpoint](#output\_rds\_cluster\_endpoint) | RDS Aurora cluster endpoint |
| <a name="output_rds_cluster_port"></a> [rds\_cluster\_port](#output\_rds\_cluster\_port) | RDS Aurora cluster port |
| <a name="output_rds_cluster_reader_endpoint"></a> [rds\_cluster\_reader\_endpoint](#output\_rds\_cluster\_reader\_endpoint) | RDS Aurora cluster reader endpoint |
| <a name="output_rds_secret_name"></a> [rds\_secret\_name](#output\_rds\_secret\_name) | Secrets Manager secret name containing the RDS password (retrieve with: aws secretsmanager get-secret-value --secret-id <name>) |
| <a name="output_rds_security_group_id"></a> [rds\_security\_group\_id](#output\_rds\_security\_group\_id) | ID of the RDS security group |
| <a name="output_region"></a> [region](#output\_region) | AWS region |
| <a name="output_vpc_cidr_block"></a> [vpc\_cidr\_block](#output\_vpc\_cidr\_block) | CIDR block of the VPC |
| <a name="output_vpc_id"></a> [vpc\_id](#output\_vpc\_id) | ID of the VPC |
| <a name="output_waf_enabled"></a> [waf\_enabled](#output\_waf\_enabled) | Whether WAF is enabled |
| <a name="output_waf_web_acl_arn"></a> [waf\_web\_acl\_arn](#output\_waf\_web\_acl\_arn) | ARN of the WAF WebACL |
| <a name="output_waf_web_acl_id"></a> [waf\_web\_acl\_id](#output\_waf\_web\_acl\_id) | ID of the WAF WebACL |
<!-- END_TF_DOCS -->

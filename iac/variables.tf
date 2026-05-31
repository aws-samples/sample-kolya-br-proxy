variable "frontend_domain" {
  description = "Frontend domain (e.g. kbp.kolya.fun)"
  type        = string
  default     = ""
}

variable "api_domain" {
  description = "API domain (e.g. api.kbp.kolya.fun)"
  type        = string
  default     = ""
}

variable "project_name" {
  description = "The name of the project"
  type        = string
  default     = "kolya-br-proxy"
}

variable "project_name_alias" {
  description = "The short name of the project"
  type        = string
  default     = "kbr-proxy"
}



variable "region" {
  description = "AWS region"
  type        = string
  # No default - will be provided via terraform.tfvars, environment variable, or AWS profile
}

variable "account" {
  description = "AWS account"
  type        = string
  # No default - will be provided via terraform.tfvars, environment variable, or detected from AWS profile
}

variable "eks_version" {
  description = "EKS Kubernetes version"
  type        = string
  default     = "1.35"
}

variable "ops_low" {
  description = "Low-ops mode: true = EKS Auto Mode + Aurora Serverless v2; false = EKS Standard + Aurora Provisioned"
  type        = bool
  default     = false
}

# tflint-ignore: terraform_unused_declarations
variable "is_private" {
  description = "Whether ALB is internal-only (consumed by k8s ingress generation, not Terraform)"
  type        = bool
  default     = false
}

variable "enable_global_accelerator" {
  description = "Enable AWS Global Accelerator for reduced latency"
  type        = bool
  default     = false
}

variable "ga_frontend_alb_name" {
  description = "Name of the frontend ALB for Global Accelerator (auto-discovery)"
  type        = string
  default     = "kolya-br-proxy-frontend-alb"
}

variable "ga_api_alb_name" {
  description = "Name of the API ALB for Global Accelerator (auto-discovery)"
  type        = string
  default     = "kolya-br-proxy-api-alb"
}

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.1.8.0/22"
}

variable "egress_mode" {
  description = "Network mode: 'nat_gateway' (create new VPC) or 'byovpc' (use existing VPC)"
  type        = string
  default     = "nat_gateway"
  validation {
    condition     = contains(["nat_gateway", "byovpc"], var.egress_mode)
    error_message = "egress_mode must be 'nat_gateway' or 'byovpc'"
  }
}

variable "vpc_id" {
  description = "Existing VPC ID (required when egress_mode = 'byovpc')"
  type        = string
  default     = ""
}

variable "private_subnet_ids" {
  description = "Existing private subnet IDs (required when egress_mode = 'byovpc', min 2 AZs)"
  type        = list(string)
  default     = []
}

variable "public_subnet_ids" {
  description = "Existing public subnet IDs (required when egress_mode = 'byovpc', min 2 AZs)"
  type        = list(string)
  default     = []
}

# Authentication configuration
variable "enable_cognito" {
  description = "Enable AWS Cognito for user authentication"
  type        = bool
  default     = true
}

# tflint-ignore: terraform_unused_declarations
variable "enable_microsoft" {
  description = "Enable Microsoft Entra ID authentication (consumed by deploy-all.sh, not Terraform)"
  type        = bool
  default     = false
}

variable "cognito_callback_urls" {
  description = "List of allowed callback URLs for Cognito OAuth"
  type        = list(string)
  default     = ["http://localhost:9000/auth/cognito/callback"]
}

variable "cognito_logout_urls" {
  description = "List of allowed logout URLs for Cognito"
  type        = list(string)
  default     = ["http://localhost:9000"]
}

variable "cognito_access_token_validity" {
  description = "Cognito access token validity in minutes"
  type        = number
  default     = 60
}

variable "cognito_id_token_validity" {
  description = "Cognito ID token validity in minutes"
  type        = number
  default     = 60
}

variable "cognito_refresh_token_validity" {
  description = "Cognito refresh token validity in days"
  type        = number
  default     = 30
}

variable "cognito_allowed_email_domains" {
  description = "List of allowed email domains for Cognito user registration (e.g., ['example.com', 'company.com'])"
  type        = list(string)
  default     = ["amazon.com"]
}

# WAF configuration
variable "enable_waf" {
  description = "Enable AWS WAF for rate limiting and security protection on ALBs"
  type        = bool
  default     = false
}

variable "waf_frontend_alb_name" {
  description = "Name of the frontend ALB for WAF association (auto-discovery)"
  type        = string
  default     = "kolya-br-proxy-frontend-alb"
}

variable "waf_api_alb_name" {
  description = "Name of the API ALB for WAF association (auto-discovery)"
  type        = string
  default     = "kolya-br-proxy-api-alb"
}

variable "waf_rate_limit_global" {
  description = "WAF global rate limit per IP (requests per 5 minutes)"
  type        = number
  default     = 2000
}

variable "waf_rate_limit_auth" {
  description = "WAF rate limit per IP for /admin/auth/* (requests per 5 minutes)"
  type        = number
  default     = 20
}

variable "waf_rate_limit_chat" {
  description = "WAF rate limit per IP for inference endpoints: /v1/chat/completions, /v1/messages, /v1beta/models/ (requests per 5 minutes)"
  type        = number
  default     = 300
}

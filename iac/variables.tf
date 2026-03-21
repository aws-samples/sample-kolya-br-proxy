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

# Cognito configuration
variable "enable_cognito" {
  description = "Enable AWS Cognito for user authentication"
  type        = bool
  default     = true
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
  description = "WAF rate limit per IP for /v1/chat/completions (requests per 5 minutes)"
  type        = number
  default     = 300
}

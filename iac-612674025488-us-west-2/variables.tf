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

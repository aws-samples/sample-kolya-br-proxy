variable "project_name_alias" {
  description = "The short name of the project"
  type        = string
}

variable "workspace" {
  description = "The workspace/environment name"
  type        = string
}

# ALB discovery
variable "frontend_alb_arn" {
  description = "ARN of the frontend ALB (leave empty to auto-discover by name)"
  type        = string
  default     = ""
}

variable "api_alb_arn" {
  description = "ARN of the API ALB (leave empty to auto-discover by name)"
  type        = string
  default     = ""
}

variable "frontend_alb_name" {
  description = "Name of the frontend ALB for auto-discovery"
  type        = string
  default     = "kolya-br-proxy-frontend-alb"
}

variable "api_alb_name" {
  description = "Name of the API ALB for auto-discovery"
  type        = string
  default     = "kolya-br-proxy-api-alb"
}

# Rate limit thresholds (requests per 5-minute window)
variable "rate_limit_global" {
  description = "Global rate limit per IP (requests per 5 minutes)"
  type        = number
  default     = 2000
}

variable "rate_limit_auth" {
  description = "Rate limit per IP for /admin/auth/* (requests per 5 minutes)"
  type        = number
  default     = 20
}

variable "rate_limit_chat" {
  description = "Rate limit per IP for /v1/chat/completions (requests per 5 minutes)"
  type        = number
  default     = 300
}

variable "default_tags" {
  description = "Default tags to apply to resources"
  type        = map(string)
  default     = {}
}

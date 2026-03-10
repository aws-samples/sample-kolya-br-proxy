variable "project_name_alias" {
  description = "The short name of the project"
  type        = string
}

variable "workspace" {
  description = "The workspace/environment name"
  type        = string
}

variable "region" {
  description = "AWS region where ALBs are deployed"
  type        = string
}

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

variable "traffic_dial_percentage" {
  description = "Percentage of traffic to dial to the endpoint group (0-100)"
  type        = number
  default     = 100
}

variable "health_check_interval" {
  description = "Health check interval in seconds (10 or 30)"
  type        = number
  default     = 30
  validation {
    condition     = contains([10, 30], var.health_check_interval)
    error_message = "Health check interval must be 10 or 30 seconds"
  }
}

variable "health_check_threshold" {
  description = "Number of consecutive health checks before marking endpoint healthy/unhealthy"
  type        = number
  default     = 3
}

variable "frontend_health_check_path" {
  description = "Health check path for frontend ALB"
  type        = string
  default     = "/"
}

variable "api_health_check_path" {
  description = "Health check path for API ALB"
  type        = string
  default     = "/health/"
}

variable "flow_logs_enabled" {
  description = "Enable flow logs for Global Accelerator"
  type        = bool
  default     = false
}

variable "flow_logs_s3_bucket" {
  description = "S3 bucket for flow logs (required if flow_logs_enabled is true)"
  type        = string
  default     = ""
}

variable "flow_logs_s3_prefix" {
  description = "S3 prefix for flow logs"
  type        = string
  default     = "global-accelerator-logs/"
}

variable "default_tags" {
  description = "Default tags to apply to resources"
  type        = map(string)
  default     = {}
}

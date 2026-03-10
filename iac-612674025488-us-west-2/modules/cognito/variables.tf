variable "project_name_alias" {
  description = "Short name of the project"
  type        = string
}

variable "workspace" {
  description = "Workspace/environment name"
  type        = string
}

variable "account" {
  description = "AWS account ID"
  type        = string
}

variable "region" {
  description = "AWS region"
  type        = string
}

variable "callback_urls" {
  description = "List of allowed callback URLs for OAuth"
  type        = list(string)
  default     = []
}

variable "logout_urls" {
  description = "List of allowed logout URLs"
  type        = list(string)
  default     = []
}

variable "access_token_validity" {
  description = "Access token validity in minutes"
  type        = number
  default     = 60
}

variable "id_token_validity" {
  description = "ID token validity in minutes"
  type        = number
  default     = 60
}

variable "refresh_token_validity" {
  description = "Refresh token validity in days"
  type        = number
  default     = 30
}

variable "advanced_security_mode" {
  description = "Advanced security mode (OFF, AUDIT, ENFORCED)"
  type        = string
  default     = "AUDIT"
}

variable "deletion_protection" {
  description = "Enable deletion protection for user pool"
  type        = bool
  default     = false
}

variable "default_tags" {
  description = "Default tags to apply to all resources"
  type        = map(string)
  default     = {}
}

variable "allowed_email_domains" {
  description = "List of allowed email domains for user registration (e.g., ['example.com', 'company.com'])"
  type        = list(string)
  default     = []
}

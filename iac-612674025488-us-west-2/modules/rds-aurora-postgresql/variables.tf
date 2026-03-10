variable "project_name_alias" {
  description = "The short name of the project"
  type        = string
}

variable "workspace" {
  description = "Terraform workspace"
  type        = string
}

variable "account" {
  description = "AWS account"
  type        = string
}

variable "region" {
  description = "AWS region"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "subnet_ids" {
  description = "List of subnet IDs"
  type        = list(string)
}

variable "instance_count" {
  description = "Number of instances in the cluster"
  type        = number
  default     = 1
}

variable "storage_encrypted" {
  description = "Whether to encrypt the Aurora PostgreSQL cluster storage"
  type        = bool
}

variable "kms_key_id" {
  description = "The ARN for the KMS encryption key for Aurora PostgreSQL cluster storage"
  type        = string
}

variable "iam_database_authentication_enabled" {
  description = "Whether to enable IAM database authentication"
  type        = bool
  default     = false
}

variable "deletion_protection" {
  description = "Whether to enable deletion protection"
  type        = bool
  default     = false
}

variable "backup_retention_period" {
  description = "Backup retention period in days"
  type        = number
  default     = 7
}

variable "preferred_backup_window" {
  description = "Preferred backup window"
  type        = string
  default     = "03:00-04:00"
}

variable "copy_tags_to_snapshot" {
  description = "Whether to copy tags to snapshots"
  type        = bool
  default     = true
}

variable "skip_final_snapshot" {
  description = "Whether to skip final snapshot"
  type        = bool
  default     = false
}

variable "preferred_maintenance_window" {
  description = "Preferred maintenance window"
  type        = string
  default     = "sun:04:00-sun:05:00"
}

variable "apply_immediately" {
  description = "Whether to apply changes immediately"
  type        = bool
  default     = false
}

variable "auto_minor_version_upgrade" {
  description = "Whether to enable auto minor version upgrade"
  type        = bool
  default     = true
}

variable "enabled_cloudwatch_logs_exports" {
  description = "List of log types to export to CloudWatch"
  type        = list(string)
  default     = ["postgresql"]
}

variable "monitoring_interval" {
  description = "Enhanced monitoring interval"
  type        = number
  default     = 0
}

variable "monitoring_role_arn" {
  description = "Enhanced monitoring role ARN"
  type        = string
  default     = ""
}

variable "performance_insights_enabled" {
  description = "Whether to enable Performance Insights"
  type        = bool
  default     = false
}

variable "default_tags" {
  description = "Default tags to apply to resources"
  type        = map(string)
  default     = {}
}

variable "security_group_ids" {
  description = "List of security group IDs to associate with the RDS cluster"
  type        = list(string)
  default     = []
}

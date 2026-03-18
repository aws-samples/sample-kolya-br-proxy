variable "project_name_alias" {
  description = "The short name of the project"
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

variable "workspace" {
  description = "Terraform workspace"
  type        = string
}

variable "partition" {
  description = "AWS partition"
  type        = string
  default     = "aws"
}

variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
}

variable "default_tags" {
  description = "Default tags to apply to resources"
  type        = map(string)
  default     = {}
}

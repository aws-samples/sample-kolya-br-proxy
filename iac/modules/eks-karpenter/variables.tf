# EKS Variables
variable "cluster_name" {
  description = "Name of the EKS cluster"
  type        = string
}

variable "kubernetes_version" {
  description = "Kubernetes version"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID where EKS cluster will be created"
  type        = string
}

variable "subnet_ids" {
  description = "List of subnet IDs for EKS cluster"
  type        = list(string)
}

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



variable "default_tags" {
  description = "Default tags to apply to resources"
  type        = map(string)
  default     = {}
}

variable "additional_security_group_ids" {
  description = "Additional security group IDs to attach to EKS nodes"
  type        = list(string)
  default     = []
}

variable "enable_cloudwatch_observability" {
  description = "Enable CloudWatch Observability addon (FluentBit log collection + Container Insights)"
  type        = bool
  default     = false
}

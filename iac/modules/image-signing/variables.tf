variable "project_name_alias" {
  description = "Project name alias used in resource names"
  type        = string
}

variable "workspace" {
  description = "Terraform workspace"
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

variable "cluster_name" {
  description = "EKS cluster that runs Kyverno"
  type        = string
}

variable "ecr_repository_prefix" {
  description = "ECR repositories whose images are signed and verified"
  type        = string
  default     = "kolya-br-proxy-"
}

variable "default_tags" {
  description = "Tags applied to every resource"
  type        = map(string)
  default     = {}
}

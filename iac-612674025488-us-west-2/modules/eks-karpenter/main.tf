terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

# This file serves as the main entry point for the EKS Karpenter module
# The actual resources are defined in eks.tf and karpenter.tf

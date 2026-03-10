output "cluster_id" {
  description = "EKS cluster ID"
  value       = module.eks.cluster_id
}

output "cluster_arn" {
  description = "EKS cluster ARN"
  value       = module.eks.cluster_arn
}

output "cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "Endpoint for EKS control plane"
  value       = module.eks.cluster_endpoint
}

output "cluster_version" {
  description = "The Kubernetes version for the EKS cluster"
  value       = module.eks.cluster_version
}

output "cluster_security_group_id" {
  description = "Security group ids attached to the cluster control plane"
  value       = module.eks.cluster_security_group_id
}

output "cluster_certificate_authority_data" {
  description = "Base64 encoded certificate data required to communicate with the cluster"
  value       = module.eks.cluster_certificate_authority_data
}

# Note: cluster_token is not available in EKS module v21.0
# Use data.aws_eks_cluster_auth.cluster.token in the root module instead

# Karpenter outputs
output "karpenter_queue_name" {
  description = "Name of the SQS queue used by Karpenter"
  value       = module.karpenter.queue_name
}

output "karpenter_node_iam_role_name" {
  description = "Name of the Karpenter node IAM role"
  value       = module.karpenter.node_iam_role_name
}

output "karpenter_service_account" {
  description = "Name of the Karpenter service account"
  value       = "karpenter"
}

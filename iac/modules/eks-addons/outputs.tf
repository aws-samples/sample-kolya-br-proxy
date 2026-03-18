output "aws_load_balancer_controller_role_arn" {
  description = "ARN of the AWS Load Balancer Controller IAM role"
  value       = aws_iam_role.aws_lbc.arn
}

output "backend_secrets_manager_name" {
  description = "Name of the AWS Secrets Manager secret for backend secrets"
  value       = aws_secretsmanager_secret.backend_secrets.name
}

output "backend_secrets_manager_arn" {
  description = "ARN of the AWS Secrets Manager secret for backend secrets"
  value       = aws_secretsmanager_secret.backend_secrets.arn
}

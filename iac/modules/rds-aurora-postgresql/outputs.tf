output "cluster_endpoint" {
  description = "RDS Aurora cluster endpoint"
  value       = aws_rds_cluster.aurora_cluster.endpoint
}

output "cluster_reader_endpoint" {
  description = "RDS Aurora cluster reader endpoint"
  value       = aws_rds_cluster.aurora_cluster.reader_endpoint
}

output "cluster_database_name" {
  description = "RDS Aurora cluster database name"
  value       = aws_rds_cluster.aurora_cluster.database_name
}

output "cluster_port" {
  description = "RDS Aurora cluster port"
  value       = aws_rds_cluster.aurora_cluster.port
}

output "cluster_master_username" {
  description = "RDS Aurora cluster master username"
  value       = aws_rds_cluster.aurora_cluster.master_username
  sensitive   = true
}

output "cluster_id" {
  description = "RDS Aurora cluster ID"
  value       = aws_rds_cluster.aurora_cluster.id
}

output "cluster_arn" {
  description = "RDS Aurora cluster ARN"
  value       = aws_rds_cluster.aurora_cluster.arn
}

output "secret_arn" {
  description = "ARN of the Secrets Manager secret containing the Aurora PostgreSQL master password"
  value       = aws_secretsmanager_secret.aurora_postgresql_password.arn
}

output "secret_name" {
  description = "Name of the Secrets Manager secret containing the Aurora PostgreSQL master password"
  value       = aws_secretsmanager_secret.aurora_postgresql_password.name
}

output "security_group_id" {
  description = "Security group ID for RDS"
  value       = length(var.security_group_ids) > 0 ? var.security_group_ids[0] : aws_security_group.aurora_security_group[0].id
}

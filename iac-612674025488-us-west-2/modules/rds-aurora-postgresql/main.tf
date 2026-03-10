terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.0"
    }
  }
}

# IAM Role for RDS Enhanced Monitoring (only create if monitoring is enabled)
resource "aws_iam_role" "rds_monitoring_role" {
  count = var.monitoring_interval > 0 ? 1 : 0

  name = "${local.resource_prefix}-rds-monitoring-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "monitoring.rds.amazonaws.com"
        }
      }
    ]
  })

  tags = var.default_tags
}

resource "aws_iam_role_policy_attachment" "rds_monitoring_policy" {
  count = var.monitoring_interval > 0 ? 1 : 0

  role       = aws_iam_role.rds_monitoring_role[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# Generate a random master password for Aurora PostgreSQL
resource "random_password" "master_password" {
  length           = 32
  special          = true
  override_special = "!#$%^&*()-_=+"
}

# Store the password in AWS Secrets Manager
resource "aws_secretsmanager_secret" "aurora_postgresql_password" {
  name                    = "${local.resource_prefix}-aurora-postgres-pwd"
  description             = "Master password for Aurora PostgreSQL cluster ${local.cluster_identifier}"
  recovery_window_in_days = 0
  tags                    = var.default_tags
}

resource "aws_secretsmanager_secret_version" "aurora_postgresql_password" {
  secret_id     = aws_secretsmanager_secret.aurora_postgresql_password.id
  secret_string = jsonencode({ password = random_password.master_password.result })
}

# Data source to get VPC information
data "aws_vpc" "selected" {
  id = var.vpc_id
}

# Local variables for consistent naming (matching lakehouse-core pattern)
locals {
  cluster_identifier = "${var.project_name_alias}-aurora-postgres-${var.workspace}"
  resource_prefix    = "${var.project_name_alias}-${var.account}-${var.region}-${var.workspace}"

  # Default configurations
  default_database_name   = "kolyabrproxy"
  default_master_username = "postgres"
  default_engine          = "aurora-postgresql"
  default_engine_version  = "16.6"
  default_instance_class  = var.workspace == "prod" ? "db.r6g.large" : "db.r6g.large"

  # Use created monitoring role if monitoring is enabled and no role ARN provided
  effective_monitoring_role_arn = var.monitoring_interval > 0 ? (
    var.monitoring_role_arn != "" ? var.monitoring_role_arn : aws_iam_role.rds_monitoring_role[0].arn
  ) : ""
}

# Security Group for Aurora PostgreSQL (only create if none provided)
resource "aws_security_group" "aurora_security_group" {
  count = length(var.security_group_ids) == 0 ? 1 : 0

  name        = "${local.resource_prefix}-aurora-postgres-sg"
  vpc_id      = var.vpc_id
  description = "Security group for Aurora PostgreSQL cluster ${local.cluster_identifier}"

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.selected.cidr_block]
    description = "Aurora PostgreSQL VPC access only"
  }

  tags = merge(var.default_tags, {
    Name = "${local.resource_prefix}-aurora-postgres-sg"
  })
}

# Use provided security groups or fallback to created one
locals {
  rds_security_group_ids = length(var.security_group_ids) > 0 ? var.security_group_ids : [aws_security_group.aurora_security_group[0].id]
}

# Aurora Subnet Group
resource "aws_db_subnet_group" "aurora_subnet_group" {
  name       = "${local.resource_prefix}-aurora-postgres-subnet-group"
  subnet_ids = var.subnet_ids

  lifecycle {
    create_before_destroy = true
  }

  tags = merge(var.default_tags, {
    Name = "${local.resource_prefix}-aurora-postgres-subnet-group"
  })
}

# Aurora Cluster
resource "aws_rds_cluster" "aurora_cluster" {
  cluster_identifier = local.cluster_identifier

  # Engine configuration
  engine         = local.default_engine
  engine_version = local.default_engine_version

  # Database configuration
  database_name   = local.default_database_name
  master_username = local.default_master_username
  master_password = random_password.master_password.result

  # Network configuration
  db_subnet_group_name   = aws_db_subnet_group.aurora_subnet_group.name
  vpc_security_group_ids = local.rds_security_group_ids
  port                   = 5432

  # Security and encryption settings (exposed as variables)
  storage_encrypted                   = var.storage_encrypted
  kms_key_id                          = var.kms_key_id
  iam_database_authentication_enabled = var.iam_database_authentication_enabled

  # Backup settings (exposed as variables)
  backup_retention_period   = var.backup_retention_period
  preferred_backup_window   = var.preferred_backup_window
  copy_tags_to_snapshot     = var.copy_tags_to_snapshot
  skip_final_snapshot       = var.skip_final_snapshot
  final_snapshot_identifier = var.skip_final_snapshot ? null : "${local.cluster_identifier}-final-snapshot-${formatdate("YYYY-MM-DD-hhmm", timestamp())}"

  # Maintenance settings
  preferred_maintenance_window = var.preferred_maintenance_window
  apply_immediately            = var.apply_immediately

  # Logging settings (exposed as variables) - PostgreSQL specific logs
  enabled_cloudwatch_logs_exports = var.enabled_cloudwatch_logs_exports

  # Monitoring settings (exposed as variables)
  monitoring_interval = var.monitoring_interval
  monitoring_role_arn = local.effective_monitoring_role_arn

  # Performance Insights settings (exposed as variables)
  performance_insights_enabled = var.performance_insights_enabled

  # Deletion protection (exposed as variable)
  deletion_protection = var.deletion_protection

  tags = merge(var.default_tags, {
    Name = local.cluster_identifier
  })
}

# Aurora Cluster Instances
resource "aws_rds_cluster_instance" "aurora_cluster_instances" {
  count              = var.instance_count
  identifier         = "${local.cluster_identifier}-${count.index}"
  cluster_identifier = aws_rds_cluster.aurora_cluster.id
  instance_class     = local.default_instance_class
  engine             = aws_rds_cluster.aurora_cluster.engine
  engine_version     = aws_rds_cluster.aurora_cluster.engine_version

  # Network configuration - disable public access
  publicly_accessible = false

  # Monitoring settings (exposed as variables)
  monitoring_interval = var.monitoring_interval
  monitoring_role_arn = local.effective_monitoring_role_arn

  # Auto minor version upgrade (exposed as variable)
  auto_minor_version_upgrade = var.auto_minor_version_upgrade

  tags = merge(var.default_tags, {
    Name = "${local.cluster_identifier}-${count.index}"
  })
}

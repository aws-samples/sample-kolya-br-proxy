locals {
  # Use variables directly - no fallback to data sources to avoid circular dependency
  account = var.account
  region  = var.region

  workspace       = terraform.workspace
  deployment_name = "${var.project_name}-${local.workspace}"
  eks_version     = var.eks_version
  cluster_name    = "${var.project_name_alias}-eks-${local.region}-${local.workspace}"

  default_tags = {
    "DeploymentName" = local.deployment_name
    "Workspace"      = local.workspace
    "ManagedBy"      = "terraform"
    "Project"        = "kolya-br-proxy"
    "Repository"     = "https://github.com/kolya-amazon/kolya-br-proxy"
  }
}



# VPC Module
module "vpc" {
  source = "./modules/vpc"

  name_prefix  = local.deployment_name
  vpc_cidr     = var.vpc_cidr
  tags         = local.default_tags
  cluster_name = local.cluster_name
}

# RDS Aurora PostgreSQL Module
module "rds_aurora_postgresql" {
  source = "./modules/rds-aurora-postgresql"

  # Project configuration
  project_name_alias = var.project_name_alias
  workspace          = local.workspace
  account            = local.account
  region             = local.region

  # Network configuration - using private subnets for security
  vpc_id             = module.vpc.vpc_id
  subnet_ids         = module.vpc.private_subnet_ids
  security_group_ids = [module.vpc.rds_security_group_id]

  # Instance configuration
  instance_count = 1

  # Security settings (configurable for different environments)
  storage_encrypted                   = true
  kms_key_id                          = ""
  iam_database_authentication_enabled = false
  deletion_protection                 = local.workspace == "prod" ? true : false

  # Backup settings (minimum 1 day required by AWS)
  backup_retention_period = local.workspace == "prod" ? 7 : 1
  preferred_backup_window = local.workspace == "prod" ? "03:00-04:00" : null
  copy_tags_to_snapshot   = local.workspace == "prod" ? true : false
  skip_final_snapshot     = local.workspace == "prod" ? false : true

  # Maintenance settings
  preferred_maintenance_window = "sun:04:00-sun:05:00"
  apply_immediately            = local.workspace == "prod" ? false : true
  auto_minor_version_upgrade   = true

  # Logging settings (only for production)
  enabled_cloudwatch_logs_exports = local.workspace == "prod" ? ["postgresql"] : []

  # Monitoring settings (only for production)
  monitoring_interval = local.workspace == "prod" ? 60 : 0

  # Performance Insights settings (only for production)
  performance_insights_enabled = local.workspace == "prod" ? true : false

  # Tags
  default_tags = local.default_tags
}

# EKS and Karpenter Module
module "eks_karpenter" {
  source = "./modules/eks-karpenter"

  # Project configuration
  project_name_alias = var.project_name_alias
  workspace          = local.workspace
  account            = local.account
  region             = local.region

  # EKS configuration
  cluster_name       = local.cluster_name
  kubernetes_version = local.eks_version
  vpc_id             = module.vpc.vpc_id
  subnet_ids         = module.vpc.private_subnet_ids

  # Additional security groups for EKS nodes
  additional_security_group_ids = [module.vpc.eks_nodes_security_group_id]

  # Tags
  default_tags = local.default_tags

}

# EKS Add-ons Module
module "eks_addons" {
  source = "./modules/eks-addons"

  # Project configuration
  project_name_alias = var.project_name_alias
  account            = local.account
  region             = local.region
  workspace          = local.workspace

  # EKS cluster information
  cluster_name = module.eks_karpenter.cluster_name

  # Tags
  default_tags = local.default_tags

  depends_on = [module.eks_karpenter, module.vpc]
}

# NOTE: Previously used data sources for K8s/Helm providers have been removed
# as these providers are no longer used. K8s resources are managed separately.

# Cognito Module (Optional)
module "cognito" {
  count  = var.enable_cognito ? 1 : 0
  source = "./modules/cognito"

  # Project configuration
  project_name_alias = var.project_name_alias
  workspace          = local.workspace
  account            = local.account
  region             = local.region

  # OAuth callback URLs
  callback_urls = var.cognito_callback_urls
  logout_urls   = var.cognito_logout_urls

  # Token validity
  access_token_validity  = var.cognito_access_token_validity
  id_token_validity      = var.cognito_id_token_validity
  refresh_token_validity = var.cognito_refresh_token_validity

  # Security settings
  advanced_security_mode = local.workspace == "prod" ? "ENFORCED" : "AUDIT"
  deletion_protection    = local.workspace == "prod" ? true : false

  # Email domain whitelist for registration
  allowed_email_domains = var.cognito_allowed_email_domains

  # Tags
  default_tags = local.default_tags
}

# Global Accelerator Module (Optional)
# NOTE: This module requires ALBs to be created first by Kubernetes ALB Controller
# Enable this after deploying the Ingress resources
module "global_accelerator" {
  count  = var.enable_global_accelerator ? 1 : 0
  source = "./modules/global-accelerator"

  # Project configuration
  project_name_alias = var.project_name_alias
  workspace          = local.workspace
  region             = local.region

  # ALB auto-discovery (ALBs created by Kubernetes ALB Controller)
  frontend_alb_name = var.ga_frontend_alb_name
  api_alb_name      = var.ga_api_alb_name

  # Health check configuration
  frontend_health_check_path = "/"
  api_health_check_path      = "/health/"
  health_check_interval      = 30
  health_check_threshold     = 3

  # Traffic configuration
  traffic_dial_percentage = 100

  # Flow logs (optional, requires an S3 bucket)
  # To enable: set flow_logs_enabled=true and provide flow_logs_s3_bucket
  flow_logs_enabled = false

  # Tags
  default_tags = local.default_tags
}

# WAF Module (Optional)
# NOTE: This module requires ALBs to be created first by Kubernetes ALB Controller
# Enable this after deploying the Ingress resources
module "waf" {
  count  = var.enable_waf ? 1 : 0
  source = "./modules/waf"

  # Project configuration
  project_name_alias = var.project_name_alias
  workspace          = local.workspace

  # ALB auto-discovery (ALBs created by Kubernetes ALB Controller)
  frontend_alb_name = var.waf_frontend_alb_name
  api_alb_name      = var.waf_api_alb_name

  # Rate limit thresholds (requests per 5-minute window)
  rate_limit_global = var.waf_rate_limit_global
  rate_limit_auth   = var.waf_rate_limit_auth
  rate_limit_chat   = var.waf_rate_limit_chat

  # Tags
  default_tags = local.default_tags
}

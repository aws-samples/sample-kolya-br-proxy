terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

locals {
  resource_prefix = "${var.project_name_alias}-${var.account}-${var.region}-${var.workspace}"
}

# Pod identity for AWS Load Balancer Controller
data "aws_iam_policy_document" "aws_lbc" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }

    actions = [
      "sts:AssumeRole",
      "sts:TagSession"
    ]
  }
}

resource "aws_iam_role" "aws_lbc" {
  name               = "${local.resource_prefix}-albc"
  assume_role_policy = data.aws_iam_policy_document.aws_lbc.json

  tags = var.default_tags
}

resource "aws_iam_policy" "aws_lbc" {
  policy = templatefile("${path.module}/policies/AWSLoadBalancerController.json", {
    partition = var.partition
  })
  name = "${local.resource_prefix}-albc"

  tags = var.default_tags
}

resource "aws_iam_role_policy_attachment" "aws_lbc" {
  policy_arn = aws_iam_policy.aws_lbc.arn
  role       = aws_iam_role.aws_lbc.name
}

resource "aws_eks_pod_identity_association" "aws_lbc" {
  cluster_name    = var.cluster_name
  namespace       = "kube-system"
  service_account = "aws-load-balancer-controller"
  role_arn        = aws_iam_role.aws_lbc.arn
}

# NOTE: Helm installations have been decoupled from Terraform.
# AWS Load Balancer Controller, Karpenter, and Metrics Server should be installed separately.
# See k8s/helm-installations/README.md for installation instructions.

# Pod identity for Backend service (Bedrock access)
data "aws_iam_policy_document" "backend_bedrock" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }

    actions = [
      "sts:AssumeRole",
      "sts:TagSession"
    ]
  }
}

resource "aws_iam_role" "backend_bedrock" {
  name               = "${local.resource_prefix}-backend-bedrock"
  assume_role_policy = data.aws_iam_policy_document.backend_bedrock.json

  tags = var.default_tags
}

resource "aws_iam_policy" "backend_bedrock" {
  name = "${local.resource_prefix}-backend-bedrock"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:*"
        ]
        Resource = "*"
      }
    ]
  })

  tags = var.default_tags
}

resource "aws_iam_role_policy_attachment" "backend_bedrock" {
  policy_arn = aws_iam_policy.backend_bedrock.arn
  role       = aws_iam_role.backend_bedrock.name
}

resource "aws_eks_pod_identity_association" "backend_bedrock" {
  cluster_name    = var.cluster_name
  namespace       = "kbp"
  service_account = "backend"
  role_arn        = aws_iam_role.backend_bedrock.arn
}

# KMS CMK for Secrets Manager encryption
resource "aws_kms_key" "secrets" {
  description             = "CMK for ${local.resource_prefix} Secrets Manager secrets"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = var.default_tags
}

resource "aws_kms_alias" "secrets" {
  name          = "alias/${local.resource_prefix}-secrets"
  target_key_id = aws_kms_key.secrets.key_id
}

# AWS Secrets Manager secret for backend secrets (managed by External Secrets Operator)
resource "aws_secretsmanager_secret" "backend_secrets" {
  name       = "${local.resource_prefix}-backend-secrets"
  kms_key_id = aws_kms_key.secrets.arn

  tags = var.default_tags
}

resource "aws_secretsmanager_secret_version" "backend_secrets" {
  secret_id     = aws_secretsmanager_secret.backend_secrets.id
  secret_string = "{}"
}

# Pod identity for External Secrets Operator
data "aws_iam_policy_document" "eso" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }

    actions = [
      "sts:AssumeRole",
      "sts:TagSession"
    ]
  }
}

resource "aws_iam_role" "eso" {
  name               = "${local.resource_prefix}-eso"
  assume_role_policy = data.aws_iam_policy_document.eso.json

  tags = var.default_tags
}

resource "aws_iam_policy" "eso" {
  name = "${local.resource_prefix}-eso"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = aws_secretsmanager_secret.backend_secrets.arn
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey"
        ]
        Resource = aws_kms_key.secrets.arn
      }
    ]
  })

  tags = var.default_tags
}

resource "aws_iam_role_policy_attachment" "eso" {
  policy_arn = aws_iam_policy.eso.arn
  role       = aws_iam_role.eso.name
}

resource "aws_eks_pod_identity_association" "eso" {
  cluster_name    = var.cluster_name
  namespace       = "external-secrets"
  service_account = "external-secrets"
  role_arn        = aws_iam_role.eso.arn
}

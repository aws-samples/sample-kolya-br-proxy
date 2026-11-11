# Container image signing.
#
# build-and-push.sh signs every pushed image digest with this KMS key
# (cosign, awskms://); Kyverno in the cluster verifies the signature with
# the key's public half before kbp pods may run. The private key never
# leaves KMS. Kyverno gets read-only ECR access to fetch signatures.
#
# Kept out of eks-addons on purpose: that module depends on the whole
# eks_karpenter module, so any targeted change there drags in unrelated
# cluster/node updates.

locals {
  resource_prefix = "${var.project_name_alias}-${var.workspace}"
}

resource "aws_kms_key" "image_signing" {
  description              = "${local.resource_prefix} container image signing (cosign)"
  key_usage                = "SIGN_VERIFY"
  customer_master_key_spec = "ECC_NIST_P256"
  deletion_window_in_days  = 30

  tags = var.default_tags
}

resource "aws_kms_alias" "image_signing" {
  name          = "alias/${local.resource_prefix}-image-signing"
  target_key_id = aws_kms_key.image_signing.key_id
}

data "aws_iam_policy_document" "kyverno_trust" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }

    actions = ["sts:AssumeRole", "sts:TagSession"]
  }
}

resource "aws_iam_role" "kyverno" {
  name               = "${local.resource_prefix}-kyverno"
  assume_role_policy = data.aws_iam_policy_document.kyverno_trust.json

  tags = var.default_tags
}

resource "aws_iam_policy" "kyverno" {
  name        = "${local.resource_prefix}-kyverno-ecr-read"
  description = "Kyverno: read image signatures from the project's ECR repositories"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchCheckLayerAvailability",
          "ecr:DescribeImages",
          "ecr:ListImages"
        ]
        Resource = "arn:aws:ecr:${var.region}:${var.account}:repository/${var.ecr_repository_prefix}*"
      }
    ]
  })

  tags = var.default_tags
}

resource "aws_iam_role_policy_attachment" "kyverno" {
  policy_arn = aws_iam_policy.kyverno.arn
  role       = aws_iam_role.kyverno.name
}

# Both controllers fetch signatures: admission (pod create) and reports
# (background scans).
resource "aws_eks_pod_identity_association" "kyverno" {
  for_each = toset(["kyverno-admission-controller", "kyverno-reports-controller"])

  cluster_name    = var.cluster_name
  namespace       = "kyverno"
  service_account = each.value
  role_arn        = aws_iam_role.kyverno.arn
}

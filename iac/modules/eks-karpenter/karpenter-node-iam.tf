################################################################################
# Karpenter Node IAM Role
# Self-managed to add create_before_destroy lifecycle on policy attachments.
# The upstream karpenter module's aws_iam_role_policy_attachment uses
# destroy-then-create by default, which detaches IAM policies during upgrades
# and causes node failures (vpc-cni crash, nodes NotReady).
################################################################################

data "aws_iam_policy_document" "karpenter_node_assume_role" {
  statement {
    sid     = "EKSNodeAssumeRole"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "karpenter_node" {
  name                  = "${var.project_name_alias}-${var.workspace}-${var.account}-${var.region}-kpnodeiamrole"
  assume_role_policy    = data.aws_iam_policy_document.karpenter_node_assume_role.json
  force_detach_policies = true

  tags = var.default_tags
}

# All policy attachments use create_before_destroy to prevent IAM gaps
# during terraform apply. This ensures the new attachment is created before
# the old one is destroyed, so nodes never lose required permissions.

locals {
  karpenter_node_policies = {
    AmazonEKSWorkerNodePolicy          = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
    AmazonEKS_CNI_Policy               = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
    AmazonEC2ContainerRegistryPullOnly = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPullOnly"
    AmazonEC2ContainerRegistryReadOnly = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
    AmazonEBSCSIDriverPolicy           = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
  }
}

resource "aws_iam_role_policy_attachment" "karpenter_node" {
  for_each = local.karpenter_node_policies

  policy_arn = each.value
  role       = aws_iam_role.karpenter_node.name

  lifecycle {
    create_before_destroy = true
  }
}

################################################################################
# State migration: moved blocks for other environments
# These tell Terraform to move existing module-managed resources to our
# self-managed resources automatically, without manual state mv commands.
# Safe to remove after all environments have been migrated.
################################################################################

moved {
  from = module.karpenter.aws_iam_role.node[0]
  to   = aws_iam_role.karpenter_node
}

moved {
  from = module.karpenter.aws_iam_role_policy_attachment.node["AmazonEKSWorkerNodePolicy"]
  to   = aws_iam_role_policy_attachment.karpenter_node["AmazonEKSWorkerNodePolicy"]
}

moved {
  from = module.karpenter.aws_iam_role_policy_attachment.node["AmazonEKS_CNI_Policy"]
  to   = aws_iam_role_policy_attachment.karpenter_node["AmazonEKS_CNI_Policy"]
}

moved {
  from = module.karpenter.aws_iam_role_policy_attachment.node["AmazonEC2ContainerRegistryPullOnly"]
  to   = aws_iam_role_policy_attachment.karpenter_node["AmazonEC2ContainerRegistryPullOnly"]
}

moved {
  from = module.karpenter.aws_iam_role_policy_attachment.node_additional["AmazonEC2ContainerRegistryReadOnly"]
  to   = aws_iam_role_policy_attachment.karpenter_node["AmazonEC2ContainerRegistryReadOnly"]
}

moved {
  from = module.karpenter.aws_iam_role_policy_attachment.node_additional["AmazonEBSCSIDriverPolicy"]
  to   = aws_iam_role_policy_attachment.karpenter_node["AmazonEBSCSIDriverPolicy"]
}

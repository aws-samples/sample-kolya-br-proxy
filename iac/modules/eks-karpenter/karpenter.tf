module "karpenter" {
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "~> 21.0"

  cluster_name = module.eks.cluster_name

  create_pod_identity_association = true

  # Node IAM role is self-managed in karpenter-node-iam.tf to ensure
  # create_before_destroy lifecycle on policy attachments.
  create_node_iam_role = false
  node_iam_role_arn    = aws_iam_role.karpenter_node.arn

  iam_role_name            = "karpenter-controller-${var.workspace}-${var.account}-${var.region}"
  iam_role_use_name_prefix = false

  queue_name = "${var.project_name_alias}-${var.workspace}-karpenter"

  rule_name_prefix = "karpenter"

  tags = var.default_tags

  depends_on = [module.eks]
}

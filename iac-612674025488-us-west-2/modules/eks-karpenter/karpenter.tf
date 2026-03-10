module "karpenter" {
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "~> 21.0"

  cluster_name = module.eks.cluster_name

  create_pod_identity_association = true

  create_node_iam_role          = true
  node_iam_role_name            = "${var.project_name_alias}-${var.workspace}-${var.account}-${var.region}-kpnodeiamrole"
  node_iam_role_use_name_prefix = false
  node_iam_role_additional_policies = {
    AmazonEC2ContainerRegistryReadOnly = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
    AmazonEBSCSIDriverPolicy           = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
  }

  iam_role_name            = "karpenter-controller-${var.workspace}-${var.account}-${var.region}"
  iam_role_use_name_prefix = false

  queue_name = "${var.project_name_alias}-${var.workspace}-karpenter"

  rule_name_prefix = "karpenter"

  tags = var.default_tags

  depends_on = [module.eks]
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  enable_irsa = false

  create_iam_role          = true
  iam_role_use_name_prefix = false
  name                     = var.cluster_name
  kubernetes_version       = var.kubernetes_version

  vpc_id     = var.vpc_id
  subnet_ids = var.subnet_ids

  addons = merge(
    {
      coredns = {}
      eks-pod-identity-agent = {
        before_compute = true
      }
      kube-proxy = {
        before_compute = true
      }
      vpc-cni = {
        before_compute = true
      }
      aws-ebs-csi-driver = {}
    },
    var.enable_cloudwatch_observability ? {
      amazon-cloudwatch-observability = {
        pod_identity_association = [{
          role_arn        = aws_iam_role.cloudwatch_agent[0].arn
          service_account = "cloudwatch-agent"
        }]
      }
    } : {}
  )

  endpoint_private_access = true
  endpoint_public_access  = true

  # Optional: Adds the current caller identity as an administrator via cluster access entry
  enable_cluster_creator_admin_permissions = true

  # Optional
  encryption_policy_use_name_prefix   = false
  security_group_use_name_prefix      = false
  node_security_group_use_name_prefix = false

  eks_managed_node_groups = {
    core_node_group = {
      use_name_prefix          = false
      iam_role_use_name_prefix = false
      name                     = "${var.project_name_alias}-${var.workspace}-${var.account}-${var.region}"
      ami_type                 = "AL2023_ARM_64_STANDARD"
      instance_types           = var.workspace == "prod" ? ["t4g.medium"] : ["t4g.small"]

      min_size     = 2
      max_size     = 4
      desired_size = 2

      # Custom metadata options with hop limit = 2
      metadata_options = {
        http_endpoint               = "enabled"
        http_tokens                 = "required"
        http_put_response_hop_limit = 2
        instance_metadata_tags      = "enabled"
      }

      capacity_type = "ON_DEMAND"

      ebs_optimized = true
      block_device_mappings = {
        xvda = {
          device_name = "/dev/xvda"
          ebs = {
            volume_size           = var.workspace == "prod" ? 100 : 30
            volume_type           = "gp3"
            encrypted             = true
            delete_on_termination = true
          }
        }
      }

      # Additional security groups
      vpc_security_group_ids = var.additional_security_group_ids

      labels = {
        WorkerType    = "ON_DEMAND"
        NodeGroupType = "core"
      }

      tags = var.default_tags
    }
  }

  node_security_group_tags = {
    "karpenter.sh/discovery" = var.cluster_name
  }

  tags = var.default_tags
}

# Pre-create CloudWatch log groups with short retention to minimize cost.
# The observability addon will reuse these instead of creating groups with no expiry.
resource "aws_cloudwatch_log_group" "container_insights" {
  for_each = var.enable_cloudwatch_observability ? toset([
    "/aws/containerinsights/${var.cluster_name}/application",
    "/aws/containerinsights/${var.cluster_name}/dataplane",
    "/aws/containerinsights/${var.cluster_name}/host",
    "/aws/containerinsights/${var.cluster_name}/performance",
  ]) : toset([])

  name              = each.value
  retention_in_days = var.workspace == "prod" ? 7 : 3
  tags              = var.default_tags
}

################################################################################
# CloudWatch Observability addon IAM
################################################################################

data "aws_iam_policy_document" "cloudwatch_agent_assume_role" {
  count = var.enable_cloudwatch_observability ? 1 : 0

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

resource "aws_iam_role" "cloudwatch_agent" {
  count = var.enable_cloudwatch_observability ? 1 : 0

  name               = "${var.project_name_alias}-${var.workspace}-${var.account}-${var.region}-cw-agent"
  assume_role_policy = data.aws_iam_policy_document.cloudwatch_agent_assume_role[0].json

  tags = var.default_tags
}

resource "aws_iam_role_policy_attachment" "cloudwatch_agent_server" {
  count = var.enable_cloudwatch_observability ? 1 : 0

  role       = aws_iam_role.cloudwatch_agent[0].name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_iam_role_policy_attachment" "cloudwatch_agent_xray" {
  count = var.enable_cloudwatch_observability ? 1 : 0

  role       = aws_iam_role.cloudwatch_agent[0].name
  policy_arn = "arn:aws:iam::aws:policy/AWSXrayWriteOnlyAccess"

  lifecycle {
    create_before_destroy = true
  }
}

# Add EBS CSI permissions to EKS node group role
resource "aws_iam_role_policy_attachment" "node_group_ebs_csi_policy" {
  role       = module.eks.eks_managed_node_groups["core_node_group"].iam_role_name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

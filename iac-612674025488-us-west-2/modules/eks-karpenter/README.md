# eks-karpenter

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
|------|---------|
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | >= 1.0 |
| <a name="requirement_aws"></a> [aws](#requirement\_aws) | >= 5.0 |

## Providers

| Name | Version |
|------|---------|
| <a name="provider_aws"></a> [aws](#provider\_aws) | >= 5.0 |

## Modules

| Name | Source | Version |
|------|--------|---------|
| <a name="module_eks"></a> [eks](#module\_eks) | terraform-aws-modules/eks/aws | ~> 21.0 |
| <a name="module_karpenter"></a> [karpenter](#module\_karpenter) | terraform-aws-modules/eks/aws//modules/karpenter | ~> 21.0 |

## Resources

| Name | Type |
|------|------|
| [aws_iam_role_policy_attachment.node_group_ebs_csi_policy](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_account"></a> [account](#input\_account) | AWS account | `string` | n/a | yes |
| <a name="input_additional_security_group_ids"></a> [additional\_security\_group\_ids](#input\_additional\_security\_group\_ids) | Additional security group IDs to attach to EKS nodes | `list(string)` | `[]` | no |
| <a name="input_cluster_name"></a> [cluster\_name](#input\_cluster\_name) | Name of the EKS cluster | `string` | n/a | yes |
| <a name="input_default_tags"></a> [default\_tags](#input\_default\_tags) | Default tags to apply to resources | `map(string)` | `{}` | no |
| <a name="input_kubernetes_version"></a> [kubernetes\_version](#input\_kubernetes\_version) | Kubernetes version | `string` | n/a | yes |
| <a name="input_project_name_alias"></a> [project\_name\_alias](#input\_project\_name\_alias) | The short name of the project | `string` | n/a | yes |
| <a name="input_region"></a> [region](#input\_region) | AWS region | `string` | n/a | yes |
| <a name="input_subnet_ids"></a> [subnet\_ids](#input\_subnet\_ids) | List of subnet IDs for EKS cluster | `list(string)` | n/a | yes |
| <a name="input_vpc_id"></a> [vpc\_id](#input\_vpc\_id) | VPC ID where EKS cluster will be created | `string` | n/a | yes |
| <a name="input_workspace"></a> [workspace](#input\_workspace) | Terraform workspace | `string` | n/a | yes |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_cluster_arn"></a> [cluster\_arn](#output\_cluster\_arn) | EKS cluster ARN |
| <a name="output_cluster_certificate_authority_data"></a> [cluster\_certificate\_authority\_data](#output\_cluster\_certificate\_authority\_data) | Base64 encoded certificate data required to communicate with the cluster |
| <a name="output_cluster_endpoint"></a> [cluster\_endpoint](#output\_cluster\_endpoint) | Endpoint for EKS control plane |
| <a name="output_cluster_id"></a> [cluster\_id](#output\_cluster\_id) | EKS cluster ID |
| <a name="output_cluster_name"></a> [cluster\_name](#output\_cluster\_name) | EKS cluster name |
| <a name="output_cluster_security_group_id"></a> [cluster\_security\_group\_id](#output\_cluster\_security\_group\_id) | Security group ids attached to the cluster control plane |
| <a name="output_cluster_version"></a> [cluster\_version](#output\_cluster\_version) | The Kubernetes version for the EKS cluster |
| <a name="output_karpenter_node_iam_role_name"></a> [karpenter\_node\_iam\_role\_name](#output\_karpenter\_node\_iam\_role\_name) | Name of the Karpenter node IAM role |
| <a name="output_karpenter_queue_name"></a> [karpenter\_queue\_name](#output\_karpenter\_queue\_name) | Name of the SQS queue used by Karpenter |
| <a name="output_karpenter_service_account"></a> [karpenter\_service\_account](#output\_karpenter\_service\_account) | Name of the Karpenter service account |
<!-- END_TF_DOCS -->

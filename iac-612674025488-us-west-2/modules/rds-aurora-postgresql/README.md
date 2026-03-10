# rds-aurora-postgresql

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
|------|---------|
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | >= 1.0 |
| <a name="requirement_aws"></a> [aws](#requirement\_aws) | >= 5.0 |
| <a name="requirement_random"></a> [random](#requirement\_random) | >= 3.0 |

## Providers

| Name | Version |
|------|---------|
| <a name="provider_aws"></a> [aws](#provider\_aws) | 6.22.1 |
| <a name="provider_random"></a> [random](#provider\_random) | >= 3.0 |

## Modules

No modules.

## Resources

| Name | Type |
|------|------|
| [aws_db_subnet_group.aurora_subnet_group](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/db_subnet_group) | resource |
| [aws_iam_role.rds_monitoring_role](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role_policy_attachment.rds_monitoring_policy](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_rds_cluster.aurora_cluster](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/rds_cluster) | resource |
| [aws_rds_cluster_instance.aurora_cluster_instances](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/rds_cluster_instance) | resource |
| [aws_secretsmanager_secret.aurora_postgresql_password](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/secretsmanager_secret) | resource |
| [aws_secretsmanager_secret_version.aurora_postgresql_password](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/secretsmanager_secret_version) | resource |
| [aws_security_group.aurora_security_group](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group) | resource |
| [random_password.master_password](https://registry.terraform.io/providers/hashicorp/random/latest/docs/resources/password) | resource |
| [aws_vpc.selected](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/vpc) | data source |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_account"></a> [account](#input\_account) | AWS account | `string` | n/a | yes |
| <a name="input_apply_immediately"></a> [apply\_immediately](#input\_apply\_immediately) | Whether to apply changes immediately | `bool` | `false` | no |
| <a name="input_auto_minor_version_upgrade"></a> [auto\_minor\_version\_upgrade](#input\_auto\_minor\_version\_upgrade) | Whether to enable auto minor version upgrade | `bool` | `true` | no |
| <a name="input_backup_retention_period"></a> [backup\_retention\_period](#input\_backup\_retention\_period) | Backup retention period in days | `number` | `7` | no |
| <a name="input_copy_tags_to_snapshot"></a> [copy\_tags\_to\_snapshot](#input\_copy\_tags\_to\_snapshot) | Whether to copy tags to snapshots | `bool` | `true` | no |
| <a name="input_default_tags"></a> [default\_tags](#input\_default\_tags) | Default tags to apply to resources | `map(string)` | `{}` | no |
| <a name="input_deletion_protection"></a> [deletion\_protection](#input\_deletion\_protection) | Whether to enable deletion protection | `bool` | `false` | no |
| <a name="input_enabled_cloudwatch_logs_exports"></a> [enabled\_cloudwatch\_logs\_exports](#input\_enabled\_cloudwatch\_logs\_exports) | List of log types to export to CloudWatch | `list(string)` | <pre>[<br/>  "postgresql"<br/>]</pre> | no |
| <a name="input_iam_database_authentication_enabled"></a> [iam\_database\_authentication\_enabled](#input\_iam\_database\_authentication\_enabled) | Whether to enable IAM database authentication | `bool` | `false` | no |
| <a name="input_instance_count"></a> [instance\_count](#input\_instance\_count) | Number of instances in the cluster | `number` | `1` | no |
| <a name="input_kms_key_id"></a> [kms\_key\_id](#input\_kms\_key\_id) | The ARN for the KMS encryption key for Aurora PostgreSQL cluster storage | `string` | n/a | yes |
| <a name="input_monitoring_interval"></a> [monitoring\_interval](#input\_monitoring\_interval) | Enhanced monitoring interval | `number` | `0` | no |
| <a name="input_monitoring_role_arn"></a> [monitoring\_role\_arn](#input\_monitoring\_role\_arn) | Enhanced monitoring role ARN | `string` | `""` | no |
| <a name="input_performance_insights_enabled"></a> [performance\_insights\_enabled](#input\_performance\_insights\_enabled) | Whether to enable Performance Insights | `bool` | `false` | no |
| <a name="input_preferred_backup_window"></a> [preferred\_backup\_window](#input\_preferred\_backup\_window) | Preferred backup window | `string` | `"03:00-04:00"` | no |
| <a name="input_preferred_maintenance_window"></a> [preferred\_maintenance\_window](#input\_preferred\_maintenance\_window) | Preferred maintenance window | `string` | `"sun:04:00-sun:05:00"` | no |
| <a name="input_project_name_alias"></a> [project\_name\_alias](#input\_project\_name\_alias) | The short name of the project | `string` | n/a | yes |
| <a name="input_region"></a> [region](#input\_region) | AWS region | `string` | n/a | yes |
| <a name="input_security_group_ids"></a> [security\_group\_ids](#input\_security\_group\_ids) | List of security group IDs to associate with the RDS cluster | `list(string)` | `[]` | no |
| <a name="input_skip_final_snapshot"></a> [skip\_final\_snapshot](#input\_skip\_final\_snapshot) | Whether to skip final snapshot | `bool` | `false` | no |
| <a name="input_storage_encrypted"></a> [storage\_encrypted](#input\_storage\_encrypted) | Whether to encrypt the Aurora PostgreSQL cluster storage | `bool` | n/a | yes |
| <a name="input_subnet_ids"></a> [subnet\_ids](#input\_subnet\_ids) | List of subnet IDs | `list(string)` | n/a | yes |
| <a name="input_vpc_id"></a> [vpc\_id](#input\_vpc\_id) | VPC ID | `string` | n/a | yes |
| <a name="input_workspace"></a> [workspace](#input\_workspace) | Terraform workspace | `string` | n/a | yes |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_cluster_arn"></a> [cluster\_arn](#output\_cluster\_arn) | RDS Aurora cluster ARN |
| <a name="output_cluster_database_name"></a> [cluster\_database\_name](#output\_cluster\_database\_name) | RDS Aurora cluster database name |
| <a name="output_cluster_endpoint"></a> [cluster\_endpoint](#output\_cluster\_endpoint) | RDS Aurora cluster endpoint |
| <a name="output_cluster_id"></a> [cluster\_id](#output\_cluster\_id) | RDS Aurora cluster ID |
| <a name="output_cluster_master_username"></a> [cluster\_master\_username](#output\_cluster\_master\_username) | RDS Aurora cluster master username |
| <a name="output_cluster_port"></a> [cluster\_port](#output\_cluster\_port) | RDS Aurora cluster port |
| <a name="output_cluster_reader_endpoint"></a> [cluster\_reader\_endpoint](#output\_cluster\_reader\_endpoint) | RDS Aurora cluster reader endpoint |
| <a name="output_secret_arn"></a> [secret\_arn](#output\_secret\_arn) | ARN of the Secrets Manager secret containing the Aurora PostgreSQL master password |
| <a name="output_secret_name"></a> [secret\_name](#output\_secret\_name) | Name of the Secrets Manager secret containing the Aurora PostgreSQL master password |
| <a name="output_security_group_id"></a> [security\_group\_id](#output\_security\_group\_id) | Security group ID for RDS |
<!-- END_TF_DOCS -->

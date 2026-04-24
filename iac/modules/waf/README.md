# waf

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

No modules.

## Resources

| Name | Type |
|------|------|
| [aws_wafv2_web_acl.main](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/wafv2_web_acl) | resource |
| [aws_wafv2_web_acl_association.api](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/wafv2_web_acl_association) | resource |
| [aws_wafv2_web_acl_association.frontend](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/wafv2_web_acl_association) | resource |
| [aws_lb.api](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/lb) | data source |
| [aws_lb.frontend](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/lb) | data source |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_api_alb_arn"></a> [api\_alb\_arn](#input\_api\_alb\_arn) | ARN of the API ALB (leave empty to auto-discover by name) | `string` | `""` | no |
| <a name="input_api_alb_name"></a> [api\_alb\_name](#input\_api\_alb\_name) | Name of the API ALB for auto-discovery | `string` | `"kolya-br-proxy-api-alb"` | no |
| <a name="input_default_tags"></a> [default\_tags](#input\_default\_tags) | Default tags to apply to resources | `map(string)` | `{}` | no |
| <a name="input_frontend_alb_arn"></a> [frontend\_alb\_arn](#input\_frontend\_alb\_arn) | ARN of the frontend ALB (leave empty to auto-discover by name) | `string` | `""` | no |
| <a name="input_frontend_alb_name"></a> [frontend\_alb\_name](#input\_frontend\_alb\_name) | Name of the frontend ALB for auto-discovery | `string` | `"kolya-br-proxy-frontend-alb"` | no |
| <a name="input_project_name_alias"></a> [project\_name\_alias](#input\_project\_name\_alias) | The short name of the project | `string` | n/a | yes |
| <a name="input_rate_limit_auth"></a> [rate\_limit\_auth](#input\_rate\_limit\_auth) | Rate limit per IP for /admin/auth/* (requests per 5 minutes) | `number` | `20` | no |
| <a name="input_rate_limit_chat"></a> [rate\_limit\_chat](#input\_rate\_limit\_chat) | Rate limit per IP for inference endpoints: /v1/chat/completions, /v1/messages, /v1beta/models/ (requests per 5 minutes) | `number` | `300` | no |
| <a name="input_rate_limit_global"></a> [rate\_limit\_global](#input\_rate\_limit\_global) | Global rate limit per IP (requests per 5 minutes) | `number` | `2000` | no |
| <a name="input_workspace"></a> [workspace](#input\_workspace) | The workspace/environment name | `string` | n/a | yes |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_web_acl_arn"></a> [web\_acl\_arn](#output\_web\_acl\_arn) | ARN of the WAF WebACL |
| <a name="output_web_acl_id"></a> [web\_acl\_id](#output\_web\_acl\_id) | ID of the WAF WebACL |
<!-- END_TF_DOCS -->

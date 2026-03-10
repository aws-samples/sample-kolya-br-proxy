# AWS Cognito User Pool Module

This module creates an AWS Cognito User Pool for user authentication with OAuth 2.0 support.

## Features

- User Pool with email-based authentication
- OAuth 2.0 authorization code flow
- Configurable password policy
- MFA support (optional)
- Advanced security features
- App client with client secret
- Custom domain for hosted UI

## Resources Created

- `aws_cognito_user_pool` - User pool for authentication
- `aws_cognito_user_pool_domain` - Custom domain for hosted UI
- `aws_cognito_user_pool_client` - App client for OAuth

## Usage

```hcl
module "cognito" {
  source = "./modules/cognito"

  project_name_alias = "kbr-proxy"
  workspace          = "dev"
  account            = "123456789012"
  region             = "us-west-2"

  callback_urls = [
    "http://localhost:9000/auth/cognito/callback",
    "https://kbp.kolya.fun/auth/cognito/callback"
  ]

  logout_urls = [
    "http://localhost:9000",
    "https://kbp.kolya.fun"
  ]

  # Token validity
  access_token_validity  = 60    # minutes
  id_token_validity      = 60    # minutes
  refresh_token_validity = 30    # days

  # Security settings
  mfa_configuration      = "OPTIONAL"
  advanced_security_mode = "AUDIT"
  deletion_protection    = false

  default_tags = {
    Environment = "dev"
    ManagedBy   = "terraform"
  }
}
```

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|----------|
| project_name_alias | Short name of the project | string | - | yes |
| workspace | Workspace/environment name | string | - | yes |
| account | AWS account ID | string | - | yes |
| region | AWS region | string | - | yes |
| callback_urls | List of allowed callback URLs | list(string) | [] | no |
| logout_urls | List of allowed logout URLs | list(string) | [] | no |
| access_token_validity | Access token validity in minutes | number | 60 | no |
| id_token_validity | ID token validity in minutes | number | 60 | no |
| refresh_token_validity | Refresh token validity in days | number | 30 | no |
| mfa_configuration | MFA configuration (OFF, ON, OPTIONAL) | string | OPTIONAL | no |
| advanced_security_mode | Advanced security mode (OFF, AUDIT, ENFORCED) | string | AUDIT | no |
| deletion_protection | Enable deletion protection | bool | false | no |
| default_tags | Default tags for all resources | map(string) | {} | no |

## Outputs

| Name | Description |
|------|-------------|
| user_pool_id | ID of the Cognito User Pool |
| user_pool_arn | ARN of the Cognito User Pool |
| user_pool_endpoint | Endpoint of the Cognito User Pool |
| user_pool_domain | Domain of the Cognito User Pool |
| user_pool_domain_url | Full URL of the Cognito User Pool domain |
| app_client_id | ID of the Cognito App Client |
| app_client_secret | Secret of the Cognito App Client (sensitive) |
| oauth_authorize_url | OAuth authorization URL |
| oauth_token_url | OAuth token URL |
| oauth_userinfo_url | OAuth user info URL |

## Environment Variables

After deploying this module, configure your backend with:

```bash
KBR_COGNITO_USER_POOL_ID=<user_pool_id>
KBR_COGNITO_CLIENT_ID=<app_client_id>
KBR_COGNITO_CLIENT_SECRET=<app_client_secret>
KBR_COGNITO_REGION=<region>
```

## OAuth Flow

1. User clicks "Login with Cognito"
2. Frontend redirects to `oauth_authorize_url`
3. User authenticates on Cognito hosted UI
4. Cognito redirects to callback URL with authorization code
5. Backend exchanges code for tokens at `oauth_token_url`
6. Backend retrieves user info from `oauth_userinfo_url`

## Security Considerations

- **Client Secret**: Stored in Terraform state (sensitive). Use remote state with encryption.
- **MFA**: Set to OPTIONAL by default. Consider ON for production.
- **Advanced Security**: Set to AUDIT by default. Consider ENFORCED for production.
- **Deletion Protection**: Disabled by default. Enable for production.

## Notes

- User pool domain must be globally unique across all AWS accounts
- Domain format: `{project_name_alias}-{workspace}-{account}`
- Supports email and username aliases
- Password policy enforces strong passwords
- Tokens are JWT format

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
|------|---------|
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | >= 1.0 |
| <a name="requirement_archive"></a> [archive](#requirement\_archive) | >= 2.0 |
| <a name="requirement_aws"></a> [aws](#requirement\_aws) | >= 5.0 |

## Providers

| Name | Version |
|------|---------|
| <a name="provider_archive"></a> [archive](#provider\_archive) | >= 2.0 |
| <a name="provider_aws"></a> [aws](#provider\_aws) | >= 5.0 |

## Modules

No modules.

## Resources

| Name | Type |
|------|------|
| [aws_cognito_user_pool.main](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cognito_user_pool) | resource |
| [aws_cognito_user_pool_client.main](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cognito_user_pool_client) | resource |
| [aws_cognito_user_pool_domain.main](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cognito_user_pool_domain) | resource |
| [aws_iam_role.lambda_pre_signup](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role_policy.lambda_pre_signup_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_lambda_function.pre_signup](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_function) | resource |
| [aws_lambda_permission.cognito_pre_signup](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_permission) | resource |
| [archive_file.lambda_pre_signup](https://registry.terraform.io/providers/hashicorp/archive/latest/docs/data-sources/file) | data source |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_access_token_validity"></a> [access\_token\_validity](#input\_access\_token\_validity) | Access token validity in minutes | `number` | `60` | no |
| <a name="input_account"></a> [account](#input\_account) | AWS account ID | `string` | n/a | yes |
| <a name="input_advanced_security_mode"></a> [advanced\_security\_mode](#input\_advanced\_security\_mode) | Advanced security mode (OFF, AUDIT, ENFORCED) | `string` | `"AUDIT"` | no |
| <a name="input_allowed_email_domains"></a> [allowed\_email\_domains](#input\_allowed\_email\_domains) | List of allowed email domains for user registration (e.g., ['example.com', 'company.com']) | `list(string)` | `[]` | no |
| <a name="input_callback_urls"></a> [callback\_urls](#input\_callback\_urls) | List of allowed callback URLs for OAuth | `list(string)` | `[]` | no |
| <a name="input_default_tags"></a> [default\_tags](#input\_default\_tags) | Default tags to apply to all resources | `map(string)` | `{}` | no |
| <a name="input_deletion_protection"></a> [deletion\_protection](#input\_deletion\_protection) | Enable deletion protection for user pool | `bool` | `false` | no |
| <a name="input_id_token_validity"></a> [id\_token\_validity](#input\_id\_token\_validity) | ID token validity in minutes | `number` | `60` | no |
| <a name="input_logout_urls"></a> [logout\_urls](#input\_logout\_urls) | List of allowed logout URLs | `list(string)` | `[]` | no |
| <a name="input_project_name_alias"></a> [project\_name\_alias](#input\_project\_name\_alias) | Short name of the project | `string` | n/a | yes |
| <a name="input_refresh_token_validity"></a> [refresh\_token\_validity](#input\_refresh\_token\_validity) | Refresh token validity in days | `number` | `30` | no |
| <a name="input_region"></a> [region](#input\_region) | AWS region | `string` | n/a | yes |
| <a name="input_workspace"></a> [workspace](#input\_workspace) | Workspace/environment name | `string` | n/a | yes |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_app_client_id"></a> [app\_client\_id](#output\_app\_client\_id) | ID of the Cognito App Client |
| <a name="output_app_client_secret"></a> [app\_client\_secret](#output\_app\_client\_secret) | Secret of the Cognito App Client (sensitive) |
| <a name="output_oauth_authorize_url"></a> [oauth\_authorize\_url](#output\_oauth\_authorize\_url) | OAuth authorization URL |
| <a name="output_oauth_token_url"></a> [oauth\_token\_url](#output\_oauth\_token\_url) | OAuth token URL |
| <a name="output_oauth_userinfo_url"></a> [oauth\_userinfo\_url](#output\_oauth\_userinfo\_url) | OAuth user info URL |
| <a name="output_user_pool_arn"></a> [user\_pool\_arn](#output\_user\_pool\_arn) | ARN of the Cognito User Pool |
| <a name="output_user_pool_domain"></a> [user\_pool\_domain](#output\_user\_pool\_domain) | Domain of the Cognito User Pool |
| <a name="output_user_pool_domain_url"></a> [user\_pool\_domain\_url](#output\_user\_pool\_domain\_url) | Full URL of the Cognito User Pool domain |
| <a name="output_user_pool_endpoint"></a> [user\_pool\_endpoint](#output\_user\_pool\_endpoint) | Endpoint of the Cognito User Pool |
| <a name="output_user_pool_id"></a> [user\_pool\_id](#output\_user\_pool\_id) | ID of the Cognito User Pool |
<!-- END_TF_DOCS -->

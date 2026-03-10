terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.0"
    }
  }
}

# AWS Cognito User Pool for authentication

# ============================================================================
# Lambda Function for Pre-Signup Email Domain Validation
# ============================================================================

# Archive Lambda function code
data "archive_file" "lambda_pre_signup" {
  type        = "zip"
  source_file = "${path.module}/lambda_pre_signup.py"
  output_path = "${path.module}/lambda_pre_signup.zip"
}

# IAM role for Lambda execution
resource "aws_iam_role" "lambda_pre_signup" {
  name = "${var.project_name_alias}-cognito-pre-signup-${var.workspace}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(
    var.default_tags,
    {
      Name = "${var.project_name_alias}-cognito-pre-signup-role-${var.workspace}"
    }
  )
}

# IAM policy for CloudWatch Logs
resource "aws_iam_role_policy" "lambda_pre_signup_logs" {
  name = "cloudwatch-logs"
  role = aws_iam_role.lambda_pre_signup.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.region}:${var.account}:log-group:/aws/lambda/${var.project_name_alias}-cognito-pre-signup-${var.workspace}:*"
      }
    ]
  })
}

# Lambda function
resource "aws_lambda_function" "pre_signup" {
  filename         = data.archive_file.lambda_pre_signup.output_path
  function_name    = "${var.project_name_alias}-cognito-pre-signup-${var.workspace}"
  role             = aws_iam_role.lambda_pre_signup.arn
  handler          = "lambda_pre_signup.lambda_handler"
  source_code_hash = data.archive_file.lambda_pre_signup.output_base64sha256
  runtime          = "python3.12"
  timeout          = 10

  environment {
    variables = {
      ALLOWED_EMAIL_DOMAINS = join(",", var.allowed_email_domains)
    }
  }

  tags = merge(
    var.default_tags,
    {
      Name = "${var.project_name_alias}-cognito-pre-signup-${var.workspace}"
    }
  )
}

# Lambda permission for Cognito to invoke
resource "aws_lambda_permission" "cognito_pre_signup" {
  statement_id  = "AllowCognitoInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.pre_signup.function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.main.arn
}

# ============================================================================
# Cognito User Pool
# ============================================================================

resource "aws_cognito_user_pool" "main" {
  name = "${var.project_name_alias}-user-pool-${var.workspace}"

  # User attributes
  alias_attributes         = ["email", "preferred_username"]
  auto_verified_attributes = ["email"]

  # Lambda triggers for email domain validation (only for self-registration)
  lambda_config {
    pre_sign_up = aws_lambda_function.pre_signup.arn
  }

  # Admin user creation configuration
  # Only admins can create users via AWS CLI/Console; self-registration is disabled
  admin_create_user_config {
    allow_admin_create_user_only = true

    invite_message_template {
      email_subject = "Welcome to ${var.project_name_alias} - Your temporary password"
      email_message = "Hello,\n\nYour account has been created. Please use the following credentials to log in:\n\nUsername: {username}\nTemporary Password: {####}\n\nYou will be required to change your password on first login.\n\nBest regards,\n${var.project_name_alias} Team"
      sms_message   = "Your username is {username} and temporary password is {####}"
    }
  }

  # Password policy
  password_policy {
    minimum_length                   = 8
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 7
  }

  # Account recovery
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # Email configuration
  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  # User pool add-ons
  user_pool_add_ons {
    advanced_security_mode = var.advanced_security_mode
  }

  # MFA configuration - set to OFF for simplicity
  # To enable MFA, you need to configure SMS (requires SNS IAM role) or TOTP
  mfa_configuration = "OFF"

  # Schema attributes
  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true

    string_attribute_constraints {
      min_length = 1
      max_length = 256
    }
  }

  # Deletion protection
  deletion_protection = var.deletion_protection ? "ACTIVE" : "INACTIVE"

  tags = merge(
    var.default_tags,
    {
      Name = "${var.project_name_alias}-user-pool-${var.workspace}"
    }
  )
}

# User Pool Domain
resource "aws_cognito_user_pool_domain" "main" {
  domain       = "${var.project_name_alias}-${var.workspace}-${var.account}"
  user_pool_id = aws_cognito_user_pool.main.id
}

# App Client
resource "aws_cognito_user_pool_client" "main" {
  name         = "${var.project_name_alias}-app-client-${var.workspace}"
  user_pool_id = aws_cognito_user_pool.main.id

  # OAuth configuration
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["email", "openid", "profile"]
  callback_urls                        = var.callback_urls
  logout_urls                          = var.logout_urls
  supported_identity_providers         = ["COGNITO"]

  # Token validity
  access_token_validity  = var.access_token_validity
  id_token_validity      = var.id_token_validity
  refresh_token_validity = var.refresh_token_validity

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  # Generate client secret
  generate_secret = true

  # Prevent user existence errors
  prevent_user_existence_errors = "ENABLED"

  # Read and write attributes
  read_attributes  = ["email", "email_verified", "preferred_username"]
  write_attributes = ["email", "preferred_username"]

  # Explicit auth flows
  explicit_auth_flows = [
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_USER_PASSWORD_AUTH"
  ]
}

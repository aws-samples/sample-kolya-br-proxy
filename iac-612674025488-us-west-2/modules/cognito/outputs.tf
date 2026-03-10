output "user_pool_id" {
  description = "ID of the Cognito User Pool"
  value       = aws_cognito_user_pool.main.id
}

output "user_pool_arn" {
  description = "ARN of the Cognito User Pool"
  value       = aws_cognito_user_pool.main.arn
}

output "user_pool_endpoint" {
  description = "Endpoint of the Cognito User Pool"
  value       = aws_cognito_user_pool.main.endpoint
}

output "user_pool_domain" {
  description = "Domain of the Cognito User Pool"
  value       = aws_cognito_user_pool_domain.main.domain
}

output "user_pool_domain_url" {
  description = "Full URL of the Cognito User Pool domain"
  value       = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.region}.amazoncognito.com"
}

output "app_client_id" {
  description = "ID of the Cognito App Client"
  value       = aws_cognito_user_pool_client.main.id
}

output "app_client_secret" {
  description = "Secret of the Cognito App Client (sensitive)"
  value       = aws_cognito_user_pool_client.main.client_secret
  sensitive   = true
}

output "oauth_authorize_url" {
  description = "OAuth authorization URL"
  value       = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.region}.amazoncognito.com/oauth2/authorize"
}

output "oauth_token_url" {
  description = "OAuth token URL"
  value       = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.region}.amazoncognito.com/oauth2/token"
}

output "oauth_userinfo_url" {
  description = "OAuth user info URL"
  value       = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.region}.amazoncognito.com/oauth2/userInfo"
}

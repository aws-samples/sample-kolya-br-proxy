output "key_alias" {
  description = "KMS alias cosign signs with (awskms:///<alias>)"
  value       = aws_kms_alias.image_signing.name
}

output "key_arn" {
  description = "KMS signing key ARN"
  value       = aws_kms_key.image_signing.arn
}

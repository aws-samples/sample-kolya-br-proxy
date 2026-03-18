output "accelerator_id" {
  description = "The ID of the Global Accelerator"
  value       = aws_globalaccelerator_accelerator.main.id
}

output "accelerator_arn" {
  description = "The ARN of the Global Accelerator"
  value       = aws_globalaccelerator_accelerator.main.id
}

output "accelerator_dns_name" {
  description = "The DNS name of the Global Accelerator"
  value       = aws_globalaccelerator_accelerator.main.dns_name
}

output "accelerator_hosted_zone_id" {
  description = "The hosted zone ID of the Global Accelerator"
  value       = aws_globalaccelerator_accelerator.main.hosted_zone_id
}

output "accelerator_static_ips" {
  description = "List of static IP addresses assigned to the Global Accelerator"
  value       = aws_globalaccelerator_accelerator.main.ip_sets[0].ip_addresses
}

output "frontend_https_listener_arn" {
  description = "ARN of the frontend HTTPS listener"
  value       = aws_globalaccelerator_listener.frontend_https.id
}

output "frontend_http_listener_arn" {
  description = "ARN of the frontend HTTP listener"
  value       = aws_globalaccelerator_listener.frontend_http.id
}

output "api_https_listener_arn" {
  description = "ARN of the API HTTPS listener (port 8443)"
  value       = aws_globalaccelerator_listener.api_https.id
}

output "api_http_listener_arn" {
  description = "ARN of the API HTTP listener (port 8080)"
  value       = aws_globalaccelerator_listener.api_http.id
}

output "usage_instructions" {
  description = "Instructions for using Global Accelerator"
  value       = <<-EOT
    Global Accelerator has been deployed with the following configuration:

    Static IPs: ${join(", ", aws_globalaccelerator_accelerator.main.ip_sets[0].ip_addresses)}
    DNS Name: ${aws_globalaccelerator_accelerator.main.dns_name}

    Port Mappings:
    - Frontend HTTPS (443) -> ALB:443
    - Frontend HTTP (80) -> ALB:80
    - API HTTPS (8443) -> ALB:443
    - API HTTP (8080) -> ALB:80

    Next Steps:
    1. Update DNS records to point to Global Accelerator:
       - kbp.kolya.fun -> ${aws_globalaccelerator_accelerator.main.dns_name} (or static IPs)
       - api.kbp.kolya.fun -> Use port 8443 on ${aws_globalaccelerator_accelerator.main.dns_name}

    2. Configure ALB security groups to allow traffic from Global Accelerator IP ranges

    3. Monitor health checks in Global Accelerator console

    4. Consider enabling flow logs for traffic analysis
  EOT
}

terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

# Global Accelerator
resource "aws_globalaccelerator_accelerator" "main" {
  name            = "${var.project_name_alias}-${var.workspace}"
  ip_address_type = "IPV4"
  enabled         = true

  attributes {
    flow_logs_enabled   = var.flow_logs_enabled
    flow_logs_s3_bucket = var.flow_logs_enabled ? var.flow_logs_s3_bucket : null
    flow_logs_s3_prefix = var.flow_logs_enabled ? var.flow_logs_s3_prefix : null
  }

  tags = var.default_tags
}

# Listener for Frontend ALB (Port 443 HTTPS)
resource "aws_globalaccelerator_listener" "frontend_https" {
  accelerator_arn = aws_globalaccelerator_accelerator.main.id
  protocol        = "TCP"

  port_range {
    from_port = 443
    to_port   = 443
  }
}

# Listener for Frontend ALB (Port 80 HTTP - for redirect)
resource "aws_globalaccelerator_listener" "frontend_http" {
  accelerator_arn = aws_globalaccelerator_accelerator.main.id
  protocol        = "TCP"

  port_range {
    from_port = 80
    to_port   = 80
  }
}

# Endpoint Group for Frontend ALB (HTTPS)
resource "aws_globalaccelerator_endpoint_group" "frontend_https" {
  listener_arn = aws_globalaccelerator_listener.frontend_https.id

  endpoint_group_region   = var.region
  traffic_dial_percentage = var.traffic_dial_percentage

  health_check_interval_seconds = var.health_check_interval
  health_check_path             = var.frontend_health_check_path
  health_check_protocol         = "HTTPS"
  health_check_port             = 443
  threshold_count               = var.health_check_threshold

  endpoint_configuration {
    endpoint_id                    = local.frontend_alb_arn
    weight                         = 100
    client_ip_preservation_enabled = true
  }
}

# Endpoint Group for Frontend ALB (HTTP)
resource "aws_globalaccelerator_endpoint_group" "frontend_http" {
  listener_arn = aws_globalaccelerator_listener.frontend_http.id

  endpoint_group_region   = var.region
  traffic_dial_percentage = var.traffic_dial_percentage

  health_check_interval_seconds = var.health_check_interval
  health_check_path             = var.frontend_health_check_path
  health_check_protocol         = "HTTP"
  health_check_port             = 80
  threshold_count               = var.health_check_threshold

  endpoint_configuration {
    endpoint_id                    = local.frontend_alb_arn
    weight                         = 100
    client_ip_preservation_enabled = true
  }
}

# Listener for API ALB (Port 443 HTTPS)
resource "aws_globalaccelerator_listener" "api_https" {
  accelerator_arn = aws_globalaccelerator_accelerator.main.id
  protocol        = "TCP"

  port_range {
    from_port = 8443
    to_port   = 8443
  }
}

# Listener for API ALB (Port 80 HTTP - for redirect)
resource "aws_globalaccelerator_listener" "api_http" {
  accelerator_arn = aws_globalaccelerator_accelerator.main.id
  protocol        = "TCP"

  port_range {
    from_port = 8080
    to_port   = 8080
  }
}

# Endpoint Group for API ALB (HTTPS)
resource "aws_globalaccelerator_endpoint_group" "api_https" {
  listener_arn = aws_globalaccelerator_listener.api_https.id

  endpoint_group_region   = var.region
  traffic_dial_percentage = var.traffic_dial_percentage

  health_check_interval_seconds = var.health_check_interval
  health_check_path             = var.api_health_check_path
  health_check_protocol         = "HTTPS"
  health_check_port             = 443
  threshold_count               = var.health_check_threshold

  endpoint_configuration {
    endpoint_id                    = local.api_alb_arn
    weight                         = 100
    client_ip_preservation_enabled = true
  }
}

# Endpoint Group for API ALB (HTTP)
resource "aws_globalaccelerator_endpoint_group" "api_http" {
  listener_arn = aws_globalaccelerator_listener.api_http.id

  endpoint_group_region   = var.region
  traffic_dial_percentage = var.traffic_dial_percentage

  health_check_interval_seconds = var.health_check_interval
  health_check_path             = var.api_health_check_path
  health_check_protocol         = "HTTP"
  health_check_port             = 80
  threshold_count               = var.health_check_threshold

  endpoint_configuration {
    endpoint_id                    = local.api_alb_arn
    weight                         = 100
    client_ip_preservation_enabled = true
  }
}

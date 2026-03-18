# Data source to discover ALB by name (if not provided via variable)
# This is useful when ALBs are created by Kubernetes ALB Controller

data "aws_lb" "frontend" {
  count = var.frontend_alb_arn == "" && var.frontend_alb_name != "" ? 1 : 0
  name  = var.frontend_alb_name
}

data "aws_lb" "api" {
  count = var.api_alb_arn == "" && var.api_alb_name != "" ? 1 : 0
  name  = var.api_alb_name
}

locals {
  # Use provided ARN or discovered ARN
  frontend_alb_arn = var.frontend_alb_arn != "" ? var.frontend_alb_arn : (
    length(data.aws_lb.frontend) > 0 ? data.aws_lb.frontend[0].arn : ""
  )

  api_alb_arn = var.api_alb_arn != "" ? var.api_alb_arn : (
    length(data.aws_lb.api) > 0 ? data.aws_lb.api[0].arn : ""
  )
}

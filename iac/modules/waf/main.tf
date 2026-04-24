terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

resource "aws_wafv2_web_acl" "main" {
  name        = "${var.project_name_alias}-waf-${var.workspace}"
  description = "WAF WebACL for ${var.project_name_alias} - ${var.workspace}"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  # Rule 1: Rate limit on /admin/auth/* (lowest priority = evaluated first)
  rule {
    name     = "rate-limit-auth"
    priority = 1

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = var.rate_limit_auth
        aggregate_key_type = "IP"

        scope_down_statement {
          byte_match_statement {
            search_string         = "/admin/auth/"
            positional_constraint = "STARTS_WITH"

            field_to_match {
              uri_path {}
            }

            text_transformation {
              priority = 0
              type     = "LOWERCASE"
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project_name_alias}-rate-limit-auth"
      sampled_requests_enabled   = true
    }
  }

  # Rule 2: Rate limit on all inference endpoints
  # /v1/chat/completions (OpenAI), /v1/messages (Anthropic), /v1beta/models/ (Gemini)
  rule {
    name     = "rate-limit-inference"
    priority = 2

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = var.rate_limit_chat
        aggregate_key_type = "IP"

        scope_down_statement {
          or_statement {
            statement {
              byte_match_statement {
                search_string         = "/v1/chat/completions"
                positional_constraint = "STARTS_WITH"

                field_to_match {
                  uri_path {}
                }

                text_transformation {
                  priority = 0
                  type     = "LOWERCASE"
                }
              }
            }

            statement {
              byte_match_statement {
                search_string         = "/v1/messages"
                positional_constraint = "STARTS_WITH"

                field_to_match {
                  uri_path {}
                }

                text_transformation {
                  priority = 0
                  type     = "LOWERCASE"
                }
              }
            }

            statement {
              byte_match_statement {
                search_string         = "/v1beta/models/"
                positional_constraint = "STARTS_WITH"

                field_to_match {
                  uri_path {}
                }

                text_transformation {
                  priority = 0
                  type     = "LOWERCASE"
                }
              }
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project_name_alias}-rate-limit-inference"
      sampled_requests_enabled   = true
    }
  }

  # Rule 3: AWS Managed - Common Rule Set (SQLi, XSS, etc.)
  # Certain rules are excluded for /v1/chat/completions because:
  # - SizeRestrictions_BODY: Agent requests with tools + conversation history exceed 8KB
  # - CrossSiteScripting_BODY: Code snippets in messages trigger XSS false positives
  # - NoUserAgent_HEADER: Some SDK clients don't send User-Agent
  # The API path is already protected by Bearer token auth + per-IP rate limiting.
  rule {
    name     = "aws-managed-common"
    priority = 3

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"

        rule_action_override {
          name = "SizeRestrictions_BODY"
          action_to_use {
            count {}
          }
        }

        rule_action_override {
          name = "CrossSiteScripting_BODY"
          action_to_use {
            count {}
          }
        }

        rule_action_override {
          name = "NoUserAgent_HEADER"
          action_to_use {
            count {}
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project_name_alias}-aws-managed-common"
      sampled_requests_enabled   = true
    }
  }

  # Rule 4: AWS Managed - Known Bad Inputs
  # LLM request bodies contain code snippets and security-related keywords
  # (e.g. "${jndi:", "FORBIDDEN", "BLOCKED") that trigger false positives.
  rule {
    name     = "aws-managed-known-bad-inputs"
    priority = 4

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"

        rule_action_override {
          name = "Log4JRCE_BODY"
          action_to_use {
            count {}
          }
        }

        rule_action_override {
          name = "JavaDeserializationRCE_BODY"
          action_to_use {
            count {}
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project_name_alias}-aws-managed-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  # Rule 5: Global rate limit (highest priority number = evaluated last, catches everything else)
  rule {
    name     = "rate-limit-global"
    priority = 5

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = var.rate_limit_global
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project_name_alias}-rate-limit-global"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.project_name_alias}-waf-${var.workspace}"
    sampled_requests_enabled   = true
  }

  tags = merge(var.default_tags, {
    Name = "${var.project_name_alias}-waf-${var.workspace}"
  })
}

# Associate WebACL with frontend ALB
resource "aws_wafv2_web_acl_association" "frontend" {
  count        = local.frontend_alb_arn != "" ? 1 : 0
  resource_arn = local.frontend_alb_arn
  web_acl_arn  = aws_wafv2_web_acl.main.arn
}

# Associate WebACL with API ALB
resource "aws_wafv2_web_acl_association" "api" {
  count        = local.api_alb_arn != "" ? 1 : 0
  resource_arn = local.api_alb_arn
  web_acl_arn  = aws_wafv2_web_acl.main.arn
}

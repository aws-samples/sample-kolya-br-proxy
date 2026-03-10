"""
Cognito Pre-Signup Lambda Trigger
Validates email domain against whitelist before allowing user registration.
"""

import json
import os


def lambda_handler(event, context):
    """
    Pre-signup Lambda trigger for Cognito User Pool.

    Args:
        event: Cognito trigger event containing user attributes
        context: Lambda context

    Returns:
        Modified event with autoConfirmUser and autoVerifyEmail flags

    Raises:
        Exception: If email domain is not in whitelist
    """
    # Get allowed email domains from environment variable
    allowed_domains_str = os.environ.get('ALLOWED_EMAIL_DOMAINS', '')
    allowed_domains = [d.strip().lower() for d in allowed_domains_str.split(',') if d.strip()]

    # Get user email from event
    user_email = event['request']['userAttributes'].get('email', '').lower()

    print(f"Pre-signup validation for email: {user_email}")
    print(f"Allowed domains: {allowed_domains}")

    # If no domains configured, allow all (fail-open for safety)
    if not allowed_domains:
        print("WARNING: No allowed domains configured, allowing all registrations")
        event['response']['autoConfirmUser'] = False
        event['response']['autoVerifyEmail'] = False
        return event

    # Extract domain from email
    if '@' not in user_email:
        print(f"Invalid email format: {user_email}")
        raise Exception("Invalid email format")

    email_domain = user_email.split('@')[1]

    # Check if domain is in whitelist
    if email_domain not in allowed_domains:
        print(f"Email domain '{email_domain}' not in whitelist: {allowed_domains}")
        raise Exception(
            f"Registration is restricted to specific email domains. "
            f"Your domain '{email_domain}' is not allowed. "
            f"Please contact the administrator."
        )

    print(f"Email domain '{email_domain}' is whitelisted, allowing registration")

    # Auto-confirm and auto-verify email for whitelisted domains
    event['response']['autoConfirmUser'] = True
    event['response']['autoVerifyEmail'] = True

    return event

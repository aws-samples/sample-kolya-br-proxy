"""Notification delivery service for alert channels (SES email)."""

import logging

import boto3
from botocore.exceptions import ClientError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_ses_client = None


def _get_ses_client():
    global _ses_client
    if _ses_client is None:
        settings = get_settings()
        region = settings.ALERT_SES_REGION or settings.AWS_REGION
        _ses_client = boto3.client("ses", region_name=region)
    return _ses_client


def send_email(subject: str, body: str, recipients: list[str]) -> bool:
    """Send a plain-text email to one or more recipients via SES.

    Returns True if the message was handed to SES, False if skipped (sender
    not configured / no recipients) or if SES rejected it. Call via
    asyncio.to_thread to avoid blocking the event loop.
    """
    settings = get_settings()
    sender = settings.ALERT_SES_SENDER_EMAIL
    if not sender:
        logger.warning("SES sender not configured, cannot send email")
        return False

    addresses = [e.strip() for e in recipients if e and e.strip()]
    if not addresses:
        return False

    try:
        _get_ses_client().send_email(
            Source=sender,
            Destination={"ToAddresses": addresses},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
            },
        )
        logger.info("Email '%s' sent to %s", subject, addresses)
        return True
    except ClientError:
        logger.warning("Failed to send email to %s", addresses, exc_info=True)
        return False


def dispatch_alert(message: str, notify_email: str) -> None:
    """Send alert email. Called via asyncio.to_thread to avoid blocking."""
    addresses = [e.strip() for e in notify_email.split(",") if e.strip()]
    send_email("KBP Alert Notification", message, addresses)

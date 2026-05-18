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


def dispatch_alert(message: str, notify_email: str) -> None:
    """Send alert email. Called via asyncio.to_thread to avoid blocking."""
    settings = get_settings()
    sender = settings.ALERT_SES_SENDER_EMAIL
    if not sender:
        logger.debug("SES sender not configured, skipping email")
        return

    addresses = [e.strip() for e in notify_email.split(",") if e.strip()]
    if not addresses:
        return

    try:
        _get_ses_client().send_email(
            Source=sender,
            Destination={"ToAddresses": addresses},
            Message={
                "Subject": {"Data": "KBP Alert Notification", "Charset": "UTF-8"},
                "Body": {"Text": {"Data": message, "Charset": "UTF-8"}},
            },
        )
        logger.info("Alert email sent to %s", addresses)
    except ClientError:
        logger.warning("Failed to send alert email to %s", addresses, exc_info=True)

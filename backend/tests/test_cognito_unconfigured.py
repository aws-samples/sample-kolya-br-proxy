"""Unconfigured Cognito paths fail with 501 instead of a TypeError (500)."""

import pytest
from fastapi import HTTPException

from app.services.cognito_oauth import CognitoOAuthService


def _unconfigured() -> CognitoOAuthService:
    service = CognitoOAuthService()
    service.client_id = None
    service.client_secret = None
    service.token_url = None
    service.user_info_url = None
    return service


def test_secret_hash_without_client_secret_is_501():
    with pytest.raises(HTTPException) as exc_info:
        _unconfigured()._get_secret_hash("user@example.com")
    assert exc_info.value.status_code == 501


@pytest.mark.asyncio
async def test_user_info_without_endpoint_is_501():
    with pytest.raises(HTTPException) as exc_info:
        await _unconfigured().get_user_info("access-token")
    assert exc_info.value.status_code == 501


def test_secret_hash_is_unchanged_when_configured():
    import base64
    import hashlib
    import hmac
    import secrets

    client_secret = secrets.token_hex(16)
    service = _unconfigured()
    service.client_id = "client"
    service.client_secret = client_secret
    expected = base64.b64encode(
        hmac.new(
            client_secret.encode(), b"user@example.comclient", hashlib.sha256
        ).digest()
    ).decode()
    assert service._get_secret_hash("user@example.com") == expected

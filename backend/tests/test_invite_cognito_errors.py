# pyright: reportArgumentType=false
"""Cognito rejections of caller input surface as 400 with Cognito's reason."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException

from app.api.admin.endpoints import users


def _client_error(code: str, message: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, "AdminCreateUser")


@pytest.fixture
def invite(monkeypatch):
    def _run(cognito_error: ClientError):
        cognito = MagicMock()
        cognito.admin_create_user.side_effect = cognito_error
        monkeypatch.setattr(users, "_get_cognito_client", lambda: cognito)
        monkeypatch.setattr(
            users, "get_settings", lambda: SimpleNamespace(COGNITO_USER_POOL_ID="pool")
        )
        db = MagicMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        db.commit = AsyncMock()
        request = users.InviteAdminRequest(
            email="new@example.com",
            username="new",
            temp_password="weakpass",  # pragma: allowlist secret
            role="viewer",
        )
        return users.invite_admin(
            request=request,
            current_user=SimpleNamespace(id="me"),
            audit_service=MagicMock(),
            db=db,
        ), db

    return _run


@pytest.mark.parametrize(
    "code", ["InvalidPasswordException", "InvalidParameterException"]
)
@pytest.mark.asyncio
async def test_input_errors_are_400_with_reason(invite, code):
    reason = "Password must have uppercase characters"
    coro, db = invite(_client_error(code, reason))
    with pytest.raises(HTTPException) as exc_info:
        await coro
    assert exc_info.value.status_code == 400
    assert reason in exc_info.value.detail
    db.commit.assert_not_awaited()  # no half-created local user


@pytest.mark.asyncio
async def test_other_cognito_errors_stay_500(invite):
    coro, _ = invite(_client_error("InternalErrorException", "boom"))
    with pytest.raises(HTTPException) as exc_info:
        await coro
    assert exc_info.value.status_code == 500

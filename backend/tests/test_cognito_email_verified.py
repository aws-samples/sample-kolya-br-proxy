# pyright: reportArgumentType=false
"""Cognito login must not trust an unverified email claim.

Local users are matched by email. Any invited Cognito user can rewrite
their own email attribute, which Cognito then marks unverified; trusting
it would log them in as whoever owns that address (e.g. super_admin).
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.admin.endpoints import auth
from app.services import oauth


class _FakeCognito:
    def __init__(self, user_info):
        self._user_info = user_info

    async def exchange_code_for_token(self, *_a, **_k):
        return {"access_token": "at"}

    async def get_user_info(self, _access_token):
        return self._user_info


class _ExplodingDB:
    """The check must reject before any user lookup."""

    async def execute(self, *_a, **_k):
        raise AssertionError("user lookup ran for an unverified email")


@pytest.fixture
def patch_oauth(monkeypatch):
    async def _valid_state(self, state, provider):
        return True, "verifier"

    monkeypatch.setattr(oauth.OAuthService, "validate_state", _valid_state)

    def _set(user_info):
        monkeypatch.setattr(
            auth, "get_cognito_oauth_service", lambda: _FakeCognito(user_info)
        )

    return _set


async def _call():
    return await auth.cognito_callback(
        code="c",
        redirect_uri="https://example/cb",
        state="s",
        http_request=SimpleNamespace(client=None, headers={}),
        response=SimpleNamespace(),
        auth_service=None,
        refresh_token_service=None,
        db=_ExplodingDB(),
    )


@pytest.mark.parametrize("verified", [None, False, "false", "False", ""])
@pytest.mark.asyncio
async def test_unverified_email_rejected(patch_oauth, verified):
    info = {"sub": "attacker-sub", "email": "kolya@amazon.com"}
    if verified is not None:
        info["email_verified"] = verified
    patch_oauth(info)
    with pytest.raises(HTTPException) as exc_info:
        await _call()
    assert exc_info.value.status_code == 403


@pytest.mark.parametrize("verified", [True, "true", "True"])
def test_claim_is_true_accepts_verified(verified):
    assert auth._claim_is_true(verified)

# pyright: reportArgumentType=false, reportAttributeAccessIssue=false
"""OAuth callbacks only accept a state issued to the same browser.

The state row proves the state was issued; the kbr_oauth_state cookie proves
it was issued to this browser, so a page on another site cannot complete a
login with a state and code minted elsewhere (login CSRF, pentest 2026-11-10).
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.responses import Response

from app.api.admin.endpoints import auth
from app.core.cookies import OAUTH_STATE_COOKIE


class _NoDB:
    def __getattr__(self, _name):
        raise AssertionError("state must be rejected before any DB access")


def _request(cookies):
    return SimpleNamespace(client=None, headers={}, cookies=cookies)


@pytest.mark.parametrize("callback", ["cognito_callback", "microsoft_callback"])
@pytest.mark.parametrize(
    "cookies", [{}, {OAUTH_STATE_COOKIE: "other-state"}, {OAUTH_STATE_COOKIE: ""}]
)
@pytest.mark.asyncio
async def test_callback_rejects_state_not_bound_to_browser(callback, cookies):
    with pytest.raises(HTTPException) as exc:
        await getattr(auth, callback)(
            code="c",
            redirect_uri="https://example/cb",
            state="the-state",
            http_request=_request(cookies),
            response=Response(),
            auth_service=None,
            refresh_token_service=None,
            db=_NoDB(),
        )
    assert exc.value.status_code == 403


@pytest.mark.parametrize("provider", ["cognito", "microsoft"])
@pytest.mark.asyncio
async def test_login_sets_state_cookie(monkeypatch, provider):
    class _StateService:
        def __init__(self, _db):
            pass

        async def generate_state(self, _provider):
            return "issued-state", "challenge"

    class _OAuth:
        def is_configured(self):
            return True

        def get_authorization_url(self, *_a, **_k):
            return "https://idp/authorize"

    import app.services.oauth as oauth_mod

    monkeypatch.setattr(oauth_mod, "OAuthService", _StateService)
    monkeypatch.setattr(auth, f"get_{provider}_oauth_service", lambda: _OAuth())

    response = Response()
    result = await getattr(auth, f"{provider}_login")(
        redirect_uri="https://example/cb", response=response, db=None
    )
    assert result["state"] == "issued-state"
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{OAUTH_STATE_COOKIE}=issued-state")
    assert "HttpOnly" in cookie and "Path=/admin/auth" in cookie

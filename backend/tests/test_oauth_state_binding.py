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


# --- callback parameters travel in the body --------------------------------


@pytest.mark.parametrize("provider", ["cognito", "microsoft"])
def test_callback_reads_json_body(provider):
    from fastapi.testclient import TestClient

    from app.api.deps import get_auth_service, get_refresh_token_service
    from app.core.database import get_db
    from main import app

    async def _no_db():
        yield _NoDB()

    app.dependency_overrides[get_db] = _no_db
    app.dependency_overrides[get_auth_service] = lambda: None
    app.dependency_overrides[get_refresh_token_service] = lambda: None
    client = TestClient(app, raise_server_exceptions=False)
    url = f"/admin/auth/{provider}/callback"
    headers = {"X-Requested-With": "XMLHttpRequest"}
    # Body parsed: the state is checked (and rejected: no cookie) before DB use.
    r = client.post(
        url,
        json={"code": "c", "state": "s", "redirect_uri": "https://example/cb"},
        headers=headers,
    )
    assert r.status_code == 403
    # Nothing supplied at all is a 400, not a 422 or 500.
    try:
        assert client.post(url, headers=headers).status_code == 400
    finally:
        app.dependency_overrides.clear()

# pyright: reportArgumentType=false, reportAttributeAccessIssue=false
"""Admin endpoints that touch a token must check the caller may manage it.

Covers the code-review findings: team add-member and model-entitlement
endpoints accepted any token_id, alert rules could watch any token, the
plaintext key export had its own JWT parsing (URL token, no active check),
and the Cognito callback logged deactivated users back in.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import deps
from app.api.admin.endpoints import alerts, auth, models, teams, tokens
from app.models.user import UserRole
from app.services import oauth

ME = uuid.uuid4()
OTHER_USER = uuid.uuid4()
MY_TOKEN = uuid.uuid4()
SCOPED_TOKEN = uuid.uuid4()
FOREIGN_TOKEN = uuid.uuid4()


def _admin(scope):
    return SimpleNamespace(
        id=ME,
        role=UserRole.ADMIN,
        is_admin=True,
        permissions={"manage_api_keys": scope, "manage_teams": "all"},
    )


def _token(token_id, owner):
    return SimpleNamespace(id=token_id, user_id=owner, token_hash="h", name="n")


TOKENS = {
    MY_TOKEN: _token(MY_TOKEN, ME),
    SCOPED_TOKEN: _token(SCOPED_TOKEN, OTHER_USER),
    FOREIGN_TOKEN: _token(FOREIGN_TOKEN, OTHER_USER),
}


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _TokenDB:
    """Answers the token lookup in require_token_access; nothing else."""

    async def execute(self, stmt):
        params = stmt.compile().params
        token_id = next(iter(params.values()))
        return _Result(TOKENS.get(token_id))


# --- helper -----------------------------------------------------------------


@pytest.mark.parametrize(
    "token_id,allowed",
    [(MY_TOKEN, True), (SCOPED_TOKEN, True), (FOREIGN_TOKEN, False)],
)
def test_can_access_token_owner_or_scope(token_id, allowed):
    user = _admin([str(SCOPED_TOKEN)])
    assert deps.can_access_token(user, TOKENS[token_id]) is allowed


def test_full_access_admin_reaches_any_token():
    assert deps.can_access_token(_admin("all"), TOKENS[FOREIGN_TOKEN])


@pytest.mark.asyncio
async def test_require_token_access_hides_foreign_and_missing_tokens():
    user = _admin([str(SCOPED_TOKEN)])
    for token_id in (FOREIGN_TOKEN, uuid.uuid4()):
        with pytest.raises(HTTPException) as exc_info:
            await deps.require_token_access(_TokenDB(), user, token_id)
        assert exc_info.value.status_code == 404
    token = await deps.require_token_access(_TokenDB(), user, SCOPED_TOKEN)
    assert token.id == SCOPED_TOKEN


# --- endpoints --------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_member_rejects_token_outside_scope(monkeypatch):
    async def _boom(*_a, **_k):
        raise AssertionError("team service ran for a foreign token")

    monkeypatch.setattr(teams.TeamService, "add_member", _boom)
    with pytest.raises(HTTPException) as exc_info:
        await teams.add_member(
            team_id=str(uuid.uuid4()),
            request=teams.AddMemberRequest(
                token_id=str(FOREIGN_TOKEN), allocated_usd=1
            ),
            current_user=_admin([str(SCOPED_TOKEN)]),
            db=_TokenDB(),
            audit_service=None,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_add_model_rejects_token_outside_scope():
    with pytest.raises(HTTPException) as exc_info:
        await models.add_model(
            request=models.AddModelRequest(token_id=str(FOREIGN_TOKEN), model_name="m"),
            db=_TokenDB(),
            _current_user=_admin([str(SCOPED_TOKEN)]),
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_models_for_foreign_token_rejected():
    with pytest.raises(HTTPException) as exc_info:
        await models.list_enabled_models(
            token_id=str(FOREIGN_TOKEN),
            db=_TokenDB(),
            _current_user=_admin([str(SCOPED_TOKEN)]),
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_alert_rule_on_foreign_token_rejected(monkeypatch):
    async def _boom(**_k):
        raise AssertionError("rule created for a foreign token")

    monkeypatch.setattr(alerts.alert_service, "create_rule", _boom)
    request = alerts.CreateAlertRuleRequest.model_construct(
        token_id=str(FOREIGN_TOKEN), team_id=None
    )
    with pytest.raises(HTTPException) as exc_info:
        await alerts.create_alert_rule(
            request=request,
            current_user=_admin([str(SCOPED_TOKEN)]),
            db=_TokenDB(),
            audit_service=None,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_alert_rule_on_foreign_team_rejected():
    user = _admin("all")
    user.permissions["manage_teams"] = [str(uuid.uuid4())]
    request = alerts.CreateAlertRuleRequest.model_construct(
        token_id=None, team_id=str(uuid.uuid4())
    )
    with pytest.raises(HTTPException) as exc_info:
        await alerts.create_alert_rule(
            request=request, current_user=user, db=_TokenDB(), audit_service=None
        )
    assert exc_info.value.status_code == 403


# --- plaintext key export ---------------------------------------------------


def test_export_uses_standard_superadmin_dependency():
    dep = tokens.export_keys_csv.__defaults__[0].dependency
    assert dep is deps.get_current_superadmin


# --- key notify recipients --------------------------------------------------


def test_notify_recipient_regex():
    assert tokens._EMAIL_RE.fullmatch("a@example.com")
    for bad in ("a", "a@b", "a b@example.com", "a@@example.com"):
        assert not tokens._EMAIL_RE.fullmatch(bad)


# --- Cognito callback -------------------------------------------------------


class _FakeCognito:
    async def exchange_code_for_token(self, *_a, **_k):
        return {"access_token": "at"}

    async def get_user_info(self, _access_token):
        return {"sub": "s", "email": "gone@example.com", "email_verified": "true"}


class _DeactivatedUserDB:
    async def execute(self, *_a, **_k):
        return _Result(SimpleNamespace(is_active=False))


@pytest.mark.asyncio
async def test_cognito_login_rejects_deactivated_user(monkeypatch):
    async def _valid_state(self, state, provider):
        return True, "verifier"

    monkeypatch.setattr(oauth.OAuthService, "validate_state", _valid_state)
    monkeypatch.setattr(auth, "get_cognito_oauth_service", lambda: _FakeCognito())
    with pytest.raises(HTTPException) as exc_info:
        await auth.cognito_callback(
            code="c",
            redirect_uri="https://example/cb",
            state="s",
            http_request=SimpleNamespace(
                client=None, headers={}, cookies={"kbr_oauth_state": "s"}
            ),
            response=SimpleNamespace(delete_cookie=lambda **_k: None),
            auth_service=None,
            refresh_token_service=None,
            db=_DeactivatedUserDB(),
        )
    assert exc_info.value.status_code == 403

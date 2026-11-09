# pyright: reportArgumentType=false, reportAttributeAccessIssue=false
"""Smaller code-review fixes (low-confidence batch B).

- CSV export neutralises spreadsheet formulas in token names
- admin invite only resets an existing Cognito user whose email matches
- Gemini tier-1 scraped prices go through the same sanity bounds as tier 2
"""

import uuid
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException

from app.api.admin.endpoints import tokens, users

# --- CSV formulas ----------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ('=HYPERLINK("x")', '\'=HYPERLINK("x")'),
        ("+1", "'+1"),
        ("-cmd", "'-cmd"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tx", "'\tx"),
        ("normal key", "normal key"),
        (None, ""),
    ],
)
def test_csv_safe(name, expected):
    assert tokens._csv_safe(name) == expected


# --- invite and existing Cognito usernames ---------------------------------


class _Cognito:
    def __init__(self, existing_email):
        self.existing_email = existing_email
        self.reset_calls = []

    def admin_create_user(self, **_k):
        raise ClientError(
            {"Error": {"Code": "UsernameExistsException", "Message": "exists"}},
            "AdminCreateUser",
        )

    def admin_get_user(self, **_k):
        return {"UserAttributes": [{"Name": "email", "Value": self.existing_email}]}

    def admin_set_user_password(self, **kw):
        self.reset_calls.append(kw)


class _DB:
    def __init__(self):
        self.added = None

    async def execute(self, _stmt):
        return SimpleNamespace(scalar_one_or_none=lambda: None)

    def add(self, obj):
        self.added = obj

    async def commit(self):
        pass

    async def refresh(self, obj):
        obj.id = uuid.uuid4()


class _Audit:
    def __init__(self):
        self.details = None

    async def log(self, **kw):
        self.details = kw["details"]


def _invite_request(email, username):
    return SimpleNamespace(
        email=email,
        username=username,
        role="admin",
        permissions={"manage_api_keys": "all"},  # pragma: allowlist secret
        temp_password="Temp-Passw0rd!",  # pragma: allowlist secret
    )


@pytest.fixture
def cognito(monkeypatch):
    monkeypatch.setattr(
        users, "get_settings", lambda: SimpleNamespace(COGNITO_USER_POOL_ID="pool")
    )

    def _set(existing_email):
        client = _Cognito(existing_email)
        monkeypatch.setattr(users, "_get_cognito_client", lambda: client)
        monkeypatch.setattr(
            users.AdminUserResponse, "from_user", staticmethod(lambda u: u)
        )
        return client

    return _set


@pytest.mark.asyncio
async def test_invite_refuses_to_reset_someone_elses_username(cognito):
    client = cognito("boss@example.com")
    with pytest.raises(HTTPException) as exc_info:
        await users.invite_admin(
            request=_invite_request("new@example.com", "boss"),
            current_user=SimpleNamespace(id=uuid.uuid4()),
            db=_DB(),
            audit_service=_Audit(),
        )
    assert exc_info.value.status_code == 409
    assert client.reset_calls == []


@pytest.mark.asyncio
async def test_invite_resets_matching_user_and_audits_it(cognito):
    client = cognito("Back@Example.com")
    audit = _Audit()
    await users.invite_admin(
        request=_invite_request("back@example.com", "back"),
        current_user=SimpleNamespace(id=uuid.uuid4()),
        db=_DB(),
        audit_service=audit,
    )
    assert len(client.reset_calls) == 1
    assert audit.details["cognito_username"] == "back"
    assert audit.details["password_reset"] is True


# --- Gemini tier-1 sanity ----------------------------------------------------


def test_tier1_page_with_zero_price_is_dropped():
    from unittest.mock import MagicMock

    from app.services.gemini_pricing_updater import GeminiPricingUpdater

    def section(heading, inp, out):
        return (
            f"<h2>{heading}</h2><h3>Standard</h3><table><tbody>"
            f"<tr><td>Input price</td><td>Free of charge</td><td>{inp}</td></tr>"
            f"<tr><td>Output price (including thinking tokens)</td>"
            f"<td>Free of charge</td><td>{out}</td></tr>"
            "</tbody></table>"
        )

    page = section("Gemini 2.5 Pro", "$0.00", "$10.00") + section(
        "Gemini 2.5 Flash", "$0.30", "$2.50"
    )
    entries = GeminiPricingUpdater(MagicMock())._parse_google_html(page)
    assert [e["model_id"] for e in entries] == ["gemini-2.5-flash"]

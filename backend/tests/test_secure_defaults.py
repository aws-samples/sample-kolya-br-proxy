# pyright: reportArgumentType=false, reportAttributeAccessIssue=false
"""Secure defaults from the code review.

- empty KBR_ALLOWED_ORIGINS means no cross-origin access, not "*"
- Microsoft: bootstrap super_admin only when none exists at all; new users
  without group sync start with no rights; no email linking for
  multi-tenant apps
- migrate.py keeps the advisory lock until alembic finishes
"""

import asyncio
import importlib.util
import pathlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.admin.endpoints import auth
from app.core.config import Settings
from app.models.user import UserRole
from app.services import oauth

# --- CORS ---------------------------------------------------------------


def test_empty_origins_is_not_wildcard():
    s = Settings.model_construct(ALLOWED_ORIGINS="")
    assert s.get_allowed_origins() == []


@pytest.mark.parametrize("value", ["*", "https://a.example,*", " * "])
def test_wildcard_rejected_outside_local(monkeypatch, value):
    monkeypatch.setenv("KBR_ENV", "prod")
    with pytest.raises(ValueError):
        Settings.validate_allowed_origins(value, {})


def test_explicit_origins_kept():
    s = Settings.model_construct(ALLOWED_ORIGINS="https://a.example, https://b.example")
    assert s.get_allowed_origins() == ["https://a.example", "https://b.example"]


# --- Microsoft login ----------------------------------------------------


@pytest.mark.parametrize(
    "tenant,single",
    [
        (None, False),
        ("", False),
        ("common", False),
        ("Organizations", False),
        ("consumers", False),
        ("6f0c1d2e-0000-4000-8000-000000000000", True),
    ],
)
def test_single_tenant_detection(tenant, single):
    assert (
        auth._microsoft_single_tenant(SimpleNamespace(MICROSOFT_TENANT_ID=tenant))
        is single
    )


class _Created(Exception):
    def __init__(self, user):
        self.user = user


class _FakeMicrosoft:
    async def exchange_code_for_token(self, *_a, **_k):
        return {"access_token": "at"}

    async def get_user_info(self, _at):
        return {"id": "ms-1", "mail": "boss@example.com"}


class _DB:
    """Answers the callback's lookups by inspecting the query text."""

    def __init__(self, by_email=None, super_admin_exists=False):
        self.by_email = by_email
        self.super_admin_exists = super_admin_exists

    async def execute(self, stmt):
        sql = str(stmt)
        if "microsoft_id" in sql and "WHERE users.microsoft_id" in sql:
            value = None
        elif "WHERE users.email" in sql:
            value = self.by_email
        elif "WHERE users.role" in sql:
            value = "id" if self.super_admin_exists else None
        else:
            raise AssertionError(f"unexpected query: {sql}")
        return SimpleNamespace(scalar_one_or_none=lambda: value)

    def add(self, user):
        raise _Created(user)


def _settings(**over):
    base = dict(
        MICROSOFT_ENABLE_GROUP_SYNC=False,
        MICROSOFT_TENANT_ID="common",
        INITIAL_USER_BALANCE_USD=0,
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture
def ms(monkeypatch):
    async def _valid_state(self, state, provider):
        return True, "verifier"

    monkeypatch.setattr(oauth.OAuthService, "validate_state", _valid_state)
    monkeypatch.setattr(auth, "get_microsoft_oauth_service", lambda: _FakeMicrosoft())

    def _run(db, **settings_over):
        monkeypatch.setattr(
            "app.core.config.get_settings", lambda: _settings(**settings_over)
        )
        return auth.microsoft_callback(
            code="c",
            redirect_uri="https://example/cb",
            state="s",
            http_request=SimpleNamespace(
                client=None, headers={}, cookies={"kbr_oauth_state": "s"}
            ),
            response=SimpleNamespace(delete_cookie=lambda **_k: None),
            auth_service=None,
            refresh_token_service=None,
            db=db,
        )

    return _run


@pytest.mark.asyncio
async def test_new_user_without_group_sync_gets_no_rights(ms):
    with pytest.raises(_Created) as created:
        await ms(_DB())
    user = created.value.user
    assert user.role == UserRole.ADMIN
    assert user.permissions == {"pending_approval": True}


@pytest.mark.asyncio
async def test_multi_tenant_app_does_not_link_by_email(ms):
    existing = SimpleNamespace(is_active=True, auth_method=None)
    with pytest.raises(HTTPException) as exc_info:
        await ms(_DB(by_email=existing), MICROSOFT_TENANT_ID="common")
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_bootstrap_skipped_when_a_super_admin_exists(ms, monkeypatch):
    from app.services import entra_group_sync

    async def _no_mappings(self):
        return False

    monkeypatch.setattr(
        entra_group_sync.EntraGroupSyncService, "has_any_mappings", _no_mappings
    )
    with pytest.raises(HTTPException) as exc_info:
        await ms(_DB(super_admin_exists=True), MICROSOFT_ENABLE_GROUP_SYNC=True)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_bootstrap_grants_super_admin_on_empty_deployment(ms, monkeypatch):
    from app.services import entra_group_sync

    async def _no_mappings(self):
        return False

    monkeypatch.setattr(
        entra_group_sync.EntraGroupSyncService, "has_any_mappings", _no_mappings
    )
    with pytest.raises(_Created) as created:
        await ms(_DB(super_admin_exists=False), MICROSOFT_ENABLE_GROUP_SYNC=True)
    assert created.value.user.role == UserRole.SUPER_ADMIN


# --- migration lock -----------------------------------------------------


def _load_migrate():
    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "migrate.py"
    spec = importlib.util.spec_from_file_location("migrate_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_lock_held_until_upgrade_finishes(monkeypatch):
    migrate = _load_migrate()
    events = []

    class _Conn:
        async def execute(self, stmt, params=None):
            sql = str(stmt)
            if "pg_advisory_lock" in sql:
                events.append("lock")
            elif "pg_advisory_unlock" in sql:
                events.append("unlock")
            elif "alembic_version LIMIT" in sql:
                return SimpleNamespace(first=lambda: ("head-rev",))
            return SimpleNamespace(scalar=lambda: True, first=lambda: None)

        async def commit(self):
            pass

    class _Engine:
        def connect(self):
            conn = _Conn()

            class _Ctx:
                async def __aenter__(self_inner):
                    return conn

                async def __aexit__(self_inner, *a):
                    return False

            return _Ctx()

        async def dispose(self):
            pass

    monkeypatch.setattr(migrate, "create_async_engine", lambda _url: _Engine())

    def _upgrade(stamp_rev):
        events.append("upgrade")

    await migrate.check_and_stamp(upgrade=_upgrade)
    assert events == ["lock", "upgrade", "unlock"]
    await asyncio.sleep(0)

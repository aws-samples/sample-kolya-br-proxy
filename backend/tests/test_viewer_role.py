# pyright: reportArgumentType=false
"""Viewer role: reads every admin page, never writes, never sees plaintext keys."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from app.api.deps import (
    enforce_viewer_read_only,
    get_allowed_resource_ids,
    get_current_superadmin,
    get_current_user_from_jwt,
    require_permission,
)
from app.models.user import UserRole

# Admin routes that are intentionally reachable without a JWT (login flow).
_PUBLIC_ADMIN_ROUTES = {
    "/admin/auth/refresh",
    "/admin/auth/revoke",
    "/admin/auth/microsoft/login",
    "/admin/auth/microsoft/callback",
    "/admin/auth/cognito/login",
    "/admin/auth/cognito/callback",
}


def _user(role: UserRole, permissions=None):
    return SimpleNamespace(
        role=role, is_admin=role != UserRole.VIEWER, permissions=permissions
    )


def _admin_routes():
    from main import app

    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith("/admin/"):
            yield route


def _depends_on(dependant, target) -> bool:
    return any(
        d.call is target or _depends_on(d, target) for d in dependant.dependencies
    )


# --- the gate -------------------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_viewer_cannot_write(method):
    with pytest.raises(HTTPException) as exc_info:
        enforce_viewer_read_only(
            _user(UserRole.VIEWER), method, "/admin/tokens/{token_id}"
        )
    assert exc_info.value.status_code == 403


@pytest.mark.parametrize(
    "route", ["/admin/tokens/{token_id}/plain", "/admin/tokens/export/keys"]
)
def test_viewer_cannot_read_plaintext_keys(route):
    with pytest.raises(HTTPException) as exc_info:
        enforce_viewer_read_only(_user(UserRole.VIEWER), "GET", route)
    assert exc_info.value.status_code == 403


@pytest.mark.parametrize(
    "route", ["/admin/tokens", "/admin/tokens/{token_id}", "/admin/users"]
)
def test_viewer_can_read(route):
    enforce_viewer_read_only(_user(UserRole.VIEWER), "GET", route)


def test_viewer_can_log_out_everywhere():
    enforce_viewer_read_only(_user(UserRole.VIEWER), "POST", "/admin/auth/revoke-all")


@pytest.mark.parametrize("role", [UserRole.SUPER_ADMIN, UserRole.ADMIN])
def test_gate_ignores_other_roles(role):
    enforce_viewer_read_only(_user(role), "DELETE", "/admin/tokens/{token_id}")
    enforce_viewer_read_only(_user(role), "GET", "/admin/tokens/{token_id}/plain")


# --- read access ----------------------------------------------------------


@pytest.mark.asyncio
async def test_viewer_passes_superadmin_and_permission_checks():
    viewer = _user(UserRole.VIEWER)
    assert await get_current_superadmin(current_user=viewer) is viewer
    for perm in ("manage_api_keys", "manage_teams", "view_usage", "view_monitor"):
        assert await require_permission(perm)(current_user=viewer) is viewer
        assert get_allowed_resource_ids(viewer, perm) is None


@pytest.mark.asyncio
async def test_admin_still_needs_superadmin():
    with pytest.raises(HTTPException):
        await get_current_superadmin(current_user=_user(UserRole.ADMIN, {"x": True}))


# --- coverage: every admin write goes through the gate --------------------


def test_every_admin_write_route_is_gated():
    """A new write endpoint that skips get_current_user_from_jwt would let
    viewers write. Fail loudly instead."""
    ungated = [
        f"{sorted(r.methods)} {r.path}"
        for r in _admin_routes()
        if r.methods - {"GET", "HEAD", "OPTIONS"}
        and r.path not in _PUBLIC_ADMIN_ROUTES
        and not _depends_on(r.dependant, get_current_user_from_jwt)
    ]
    assert not ungated, f"admin write routes bypass the viewer gate: {ungated}"


def test_denied_read_routes_exist():
    """Guard against a route rename silently re-exposing plaintext keys."""
    paths = {r.path for r in _admin_routes()}
    assert "/admin/tokens/{token_id}/plain" in paths
    assert "/admin/tokens/export/keys" in paths


# --- end to end through the real app --------------------------------------


@pytest.fixture
def viewer_client():
    from uuid import uuid4

    from fastapi.testclient import TestClient

    from app.api.deps import get_auth_service
    from app.core.database import get_db
    from app.core.security import create_access_token
    from main import app

    viewer = SimpleNamespace(
        id=uuid4(),
        role=UserRole.VIEWER,
        is_admin=False,
        is_active=True,
        permissions=None,
    )

    class _AuthService:
        async def get_user_by_id(self, _user_id):
            return viewer

    async def _no_db():
        # Endpoints must never run: the gate rejects during dependency
        # resolution. A None session makes any leak fail loudly.
        yield None

    app.dependency_overrides[get_auth_service] = lambda: _AuthService()
    app.dependency_overrides[get_db] = _no_db
    token = create_access_token({"sub": str(viewer.id)})
    client = TestClient(app, raise_server_exceptions=False)
    client.headers["Authorization"] = f"Bearer {token}"
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_auth_service, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/admin/tokens"),
        ("DELETE", "/admin/tokens/00000000-0000-0000-0000-000000000000"),
        ("PUT", "/admin/users/00000000-0000-0000-0000-000000000000"),
        ("POST", "/admin/users"),
        ("GET", "/admin/tokens/00000000-0000-0000-0000-000000000000/plain"),
    ],
)
def test_viewer_blocked_end_to_end(viewer_client, method, path):
    response = viewer_client.request(method, path, json={})
    assert response.status_code == 403, response.text
    assert "Read-only access" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_export_keys_rejects_viewer(monkeypatch):
    """/tokens/export/keys authenticates itself (it accepts ?token= for
    browser downloads) instead of using get_current_user_from_jwt, so the
    central gate doesn't run there. Its own super_admin check must hold."""
    from uuid import uuid4

    from app.api.admin.endpoints import tokens
    from app.core.security import create_access_token

    viewer = SimpleNamespace(id=uuid4(), role=UserRole.VIEWER, is_active=True)

    class _AuthService:
        def __init__(self, _db):
            pass

        async def get_user_by_id(self, _user_id):
            return viewer

    monkeypatch.setattr(tokens, "AuthService", _AuthService)
    request = SimpleNamespace(
        headers={
            "authorization": f"Bearer {create_access_token({'sub': str(viewer.id)})}"
        },
        query_params={},
    )
    with pytest.raises(HTTPException) as exc_info:
        await tokens.export_keys_csv(request_obj=request, db=None)
    assert exc_info.value.status_code == 403

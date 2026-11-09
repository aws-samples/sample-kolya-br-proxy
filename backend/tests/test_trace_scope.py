# pyright: reportArgumentType=false
"""Traces carry full prompts: scoped admins only see their own tokens'."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.admin.endpoints import traces
from app.api.deps import get_current_superadmin
from app.models.user import UserRole
from app.services.trace_store import TraceRecord, TraceStore

MINE, OTHER = (
    "11111111-1111-1111-1111-111111111111",
    "22222222-2222-2222-2222-222222222222",
)


def _user(role, permissions=None):
    return SimpleNamespace(role=role, permissions=permissions)


@pytest.fixture(autouse=True)
def store():
    s = TraceStore.get_instance()
    s.clear()
    s.add(TraceRecord(request_id="r-mine", timestamp=1, model="m", token_id=MINE))
    s.add(TraceRecord(request_id="r-other", timestamp=2, model="m", token_id=OTHER))
    yield s
    s.clear()


@pytest.mark.asyncio
async def test_scoped_admin_lists_only_own_tokens():
    admin = _user(UserRole.ADMIN, {"view_usage": True, "manage_api_keys": [MINE]})
    result = await traces.list_traces(current_user=admin)
    assert [t["request_id"] for t in result["traces"]] == ["r-mine"]
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_scoped_admin_cannot_read_other_trace():
    admin = _user(UserRole.ADMIN, {"view_usage": True, "manage_api_keys": [MINE]})
    with pytest.raises(HTTPException) as exc_info:
        await traces.get_trace("r-other", current_user=admin)
    assert exc_info.value.status_code == 404
    assert (await traces.get_trace("r-mine", current_user=admin))["token_id"] == MINE


@pytest.mark.asyncio
async def test_admin_without_key_scope_sees_nothing():
    admin = _user(UserRole.ADMIN, {"view_usage": True})
    assert (await traces.list_traces(current_user=admin))["traces"] == []


@pytest.mark.asyncio
async def test_super_admin_sees_all():
    result = await traces.list_traces(current_user=_user(UserRole.SUPER_ADMIN))
    assert {t["request_id"] for t in result["traces"]} == {"r-mine", "r-other"}


@pytest.mark.asyncio
async def test_viewer_sees_no_prompt_bodies():
    viewer = _user(UserRole.VIEWER)
    assert (await traces.list_traces(current_user=viewer))["traces"] == []
    with pytest.raises(HTTPException) as exc_info:
        await traces.get_trace("r-mine", current_user=viewer)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_full_access_admin_sees_all():
    admin = _user(UserRole.ADMIN, {"view_usage": True, "manage_api_keys": "all"})
    assert (await traces.list_traces(current_user=admin))["count"] == 2


def test_clear_requires_superadmin():
    dep = traces.clear_traces.__defaults__[0].dependency
    assert dep is get_current_superadmin


@pytest.mark.asyncio
async def test_admin_rejected_by_clear_dependency():
    with pytest.raises(HTTPException):
        await get_current_superadmin(
            current_user=_user(UserRole.ADMIN, {"view_usage": True})
        )

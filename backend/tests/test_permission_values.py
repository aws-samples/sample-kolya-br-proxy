# pyright: reportArgumentType=false
"""Pin admin permission-value semantics.

Booleans are matched by identity, not equality: ``0`` and ``1`` are not
``False``/``True`` here, so a lint-driven rewrite to ``in (None, False)``
would silently change who gets access.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.deps import get_allowed_resource_ids, require_permission
from app.models.user import UserRole


def _admin(permissions):
    return SimpleNamespace(
        role=UserRole.ADMIN, is_admin=True, permissions={"other": True, **permissions}
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, None),
        ("all", None),
        (["a", "b"], ["a", "b"]),
        (False, []),
        (None, []),
        (1, []),
        (0, []),
    ],
)
def test_allowed_resource_ids_treats_only_real_true_as_full_access(value, expected):
    user = _admin({} if value is None else {"tokens": value})
    assert get_allowed_resource_ids(user, "tokens") == expected


@pytest.mark.parametrize("value", [True, "all", ["a"], 1, 0, "x"])
@pytest.mark.asyncio
async def test_require_permission_grants_everything_except_none_and_false(value):
    check = require_permission("tokens")
    user = _admin({"tokens": value})
    assert await check(current_user=user) is user


@pytest.mark.parametrize("value", [False, None])
@pytest.mark.asyncio
async def test_require_permission_denies_missing_or_false(value):
    check = require_permission("tokens")
    user = _admin({} if value is None else {"tokens": value})
    with pytest.raises(HTTPException) as exc_info:
        await check(current_user=user)
    assert exc_info.value.status_code == 403

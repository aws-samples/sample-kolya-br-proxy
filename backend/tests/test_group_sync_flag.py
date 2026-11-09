"""group_sync_enabled is only reported when Microsoft OAuth is configured.

Group sync applies to Microsoft logins only; on a Cognito-only deployment the
flag must not leak to the frontend, where it would hide the invite flow.
"""

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.admin.endpoints import auth as auth_endpoints
from app.models.user import User, UserRole


def _user() -> User:
    return User(
        id=uuid4(),
        email="user@example.com",
        is_active=True,
        is_admin=True,
        role=UserRole.ADMIN,
        email_verified=True,
        current_balance=Decimal("0.00"),
    )


@pytest.mark.parametrize(
    ("group_sync", "client_id", "expected"),
    [
        (True, None, False),
        (True, "", False),
        (False, "ms-client", False),
        (True, "ms-client", True),
    ],
)
def test_group_sync_enabled_requires_microsoft_config(
    monkeypatch, group_sync, client_id, expected
):
    settings = SimpleNamespace(
        MICROSOFT_ENABLE_GROUP_SYNC=group_sync, MICROSOFT_CLIENT_ID=client_id
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)

    response = auth_endpoints.UserResponse.from_user(_user())

    assert response.group_sync_enabled is expected

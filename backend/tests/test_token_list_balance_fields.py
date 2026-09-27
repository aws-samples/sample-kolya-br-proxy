"""Response-contract tests for balance fields returned by /admin/tokens."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.api.admin.endpoints import tokens as tokens_module
from app.models.token import APIToken
from app.models.user import User


def _zero_quota_token() -> APIToken:
    return APIToken(
        id=uuid4(),
        user_id=uuid4(),
        name="zero-budget",
        description=None,
        token_hash="hash",
        encrypted_token=None,
        expires_at=None,
        quota_usd=Decimal("0.00"),
        monthly_quota_usd=None,
        monthly_reset_policy=None,
        monthly_quota_start=None,
        allowed_ips=None,
        notify_emails=None,
        is_active=True,
        is_deleted=False,
        created_at=datetime.utcnow(),
        last_used_at=None,
        token_metadata=None,
    )


def _query_result(*, scalars=None, rows=None):
    result = MagicMock()
    if scalars is not None:
        result.scalars.return_value.all.return_value = scalars
    if rows is not None:
        result.__iter__.return_value = iter(rows)
    return result


@pytest.mark.asyncio
async def test_list_tokens_preserves_zero_lifetime_quota_and_remaining():
    """A zero budget is blocked, so the API must not serialize it as unlimited."""
    token = _zero_quota_token()
    db = AsyncMock()
    db.execute.side_effect = [
        _query_result(scalars=[token]),
        _query_result(rows=[]),  # usage totals
        _query_result(rows=[]),  # team membership
        _query_result(rows=[]),  # team-window usage
        _query_result(rows=[]),  # allowed models
    ]

    with patch.object(tokens_module, "get_allowed_resource_ids", return_value=None):
        response = await tokens_module.list_tokens(
            include_inactive=False,
            current_user=cast(User, SimpleNamespace()),
            db=db,
        )

    assert response[0].is_quota_exceeded is True
    assert response[0].quota_usd == "0.00"
    assert response[0].remaining_quota == "0.00"

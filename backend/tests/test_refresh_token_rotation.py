"""Refresh-token rotation concurrency regressions."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.services.refresh_token import RefreshTokenService


@pytest.mark.asyncio
async def test_rotation_locks_presented_token_before_child_check():
    db = MagicMock()
    db.execute = AsyncMock()
    missing = MagicMock()
    missing.scalar_one_or_none.return_value = None
    db.execute.return_value = missing

    service = RefreshTokenService(db)
    with patch("app.services.refresh_token.hash_refresh_token", return_value="hash"):
        result = await service.validate_and_rotate_token("refresh-token")

    statement = db.execute.await_args_list[0].args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql
    assert result == (None, None, "Invalid refresh token")

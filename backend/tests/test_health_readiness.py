"""/health/ready must report a reachable database as healthy.

Regression: the check awaited ``Result.fetchone()``, which is synchronous in
SQLAlchemy 2.0 (``await AsyncSession.execute()`` returns a buffered
``Result``). Awaiting the returned ``Row`` raised ``TypeError``, so the
endpoint answered 503 even when the database was fine.
"""

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.health import readiness_check


def _session(execute):
    session = MagicMock()
    session.execute = execute
    return session


@pytest.mark.asyncio
async def test_reachable_database_is_ready():
    result = MagicMock()
    result.fetchone.return_value = (1,)  # synchronous, like sqlalchemy.Result

    response = await readiness_check(db=_session(AsyncMock(return_value=result)))

    assert response["status"] == "ready"
    assert response["components"]["database"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_unreachable_database_is_not_ready():
    with pytest.raises(HTTPException) as exc_info:
        await readiness_check(db=_session(AsyncMock(side_effect=OSError("down"))))

    assert exc_info.value.status_code == 503
    # The endpoint puts its full report (a dict) in HTTPException.detail.
    detail = cast(dict[str, Any], exc_info.value.detail)
    assert detail["components"]["database"]["status"] == "unhealthy"

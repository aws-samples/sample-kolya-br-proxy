"""Bind stored upstream Responses to the API key that created them.

See ``app.models.stored_response``. A ``previous_response_id`` the caller
does not own is answered exactly like an unknown one, so IDs can't be probed.
"""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.core.database import session_scope
from app.models.stored_response import StoredResponse

# OpenAI keeps stored responses for 30 days; keep ownership a little longer.
RETENTION = timedelta(days=31)


def is_stored(body: dict, response: dict | None = None) -> bool:
    """Whether upstream keeps this response (``store`` defaults to true)."""
    if response is not None and "store" in response:
        return response.get("store") is not False
    return body.get("store") is not False


async def record_owner(response_id: str, token_id: UUID) -> None:
    async with session_scope() as db:
        await db.execute(
            insert(StoredResponse)
            .values(response_id=response_id, token_id=token_id)
            .on_conflict_do_nothing(index_elements=["response_id"])
        )
        await db.commit()


async def is_owner(response_id: str, token_id: UUID) -> bool:
    async with session_scope() as db:
        owner = (
            await db.execute(
                select(StoredResponse.token_id).where(
                    StoredResponse.response_id == response_id
                )
            )
        ).scalar_one_or_none()
    return owner == token_id


async def cleanup_expired(db) -> int:
    result = await db.execute(
        delete(StoredResponse).where(
            StoredResponse.created_at < datetime.utcnow() - RETENTION
        )
    )
    await db.commit()
    return result.rowcount or 0

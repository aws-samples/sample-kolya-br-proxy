"""Entra ID group-to-permission sync service."""

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entra_group_mapping import EntraGroupMapping
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)


class EntraGroupSyncService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def resolve_permissions(
        self, group_ids: list[str]
    ) -> Optional[tuple[UserRole, dict | None]]:
        if not group_ids:
            return None

        result = await self.db.execute(
            select(EntraGroupMapping)
            .where(EntraGroupMapping.entra_group_id.in_(group_ids))
            .order_by(EntraGroupMapping.priority.desc())
            .limit(1)
        )
        mapping = result.scalar_one_or_none()

        if not mapping:
            return None

        logger.info(
            f"Entra group resolved: group={mapping.group_name}, "
            f"role={mapping.role.value}, priority={mapping.priority}"
        )
        return (mapping.role, mapping.permissions)

    async def sync_user_permissions(
        self, user: User, group_ids: list[str]
    ) -> bool:
        resolved = await self.resolve_permissions(group_ids)
        if resolved is None:
            return False

        role, permissions = resolved
        user.role = role
        user.permissions = permissions
        return True

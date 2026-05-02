"""Team management service with budget invariant enforcement."""

import logging
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.team import Team, TeamMember
from app.models.token import APIToken

logger = logging.getLogger(__name__)


class TeamService:
    """Service for team CRUD and budget allocation with invariant enforcement."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Locking helper
    # ------------------------------------------------------------------

    async def _lock_team_and_members(
        self, team_id: UUID
    ) -> tuple[Team, list[TeamMember], Decimal]:
        """Lock team + all members FOR UPDATE. Returns (team, members, total_allocated)."""
        result = await self.db.execute(
            select(Team).where(Team.id == team_id).with_for_update()
        )
        team = result.scalar_one_or_none()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")

        members_result = await self.db.execute(
            select(TeamMember).where(TeamMember.team_id == team_id).with_for_update()
        )
        members = list(members_result.scalars().all())
        total_allocated = sum((m.allocated_usd for m in members), Decimal("0.00"))

        return team, members, total_allocated

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_team(
        self,
        user_id: UUID,
        name: str,
        monthly_budget_usd: Decimal,
        monthly_reset_policy: str = "reset",
        daily_limit_enabled: bool = True,
    ) -> Team:
        team = Team(
            user_id=user_id,
            name=name,
            monthly_budget_usd=monthly_budget_usd,
            monthly_reset_policy=monthly_reset_policy,
            daily_limit_enabled=daily_limit_enabled,
            monthly_budget_start=datetime.utcnow(),
        )
        self.db.add(team)
        await self.db.commit()
        await self.db.refresh(team)
        return team

    async def get_team(self, team_id: UUID, user_id: UUID) -> Team:
        result = await self.db.execute(
            select(Team).where(Team.id == team_id, Team.user_id == user_id)
        )
        team = result.scalar_one_or_none()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        return team

    async def list_teams(self, user_id: UUID) -> list[Team]:
        result = await self.db.execute(
            select(Team)
            .where(Team.user_id == user_id, Team.is_active)
            .order_by(Team.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_team(
        self,
        team_id: UUID,
        user_id: UUID,
        name: Optional[str] = None,
        monthly_budget_usd: Optional[Decimal] = None,
        monthly_reset_policy: Optional[str] = None,
        daily_limit_enabled: Optional[bool] = None,
    ) -> Team:
        team, members, total_allocated = await self._lock_team_and_members(team_id)

        if team.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        if monthly_budget_usd is not None:
            if monthly_budget_usd < total_allocated:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Cannot reduce budget below total allocated "
                        f"(${total_allocated:.2f}). Free up allocations first."
                    ),
                )
            team.monthly_budget_usd = monthly_budget_usd

        if name is not None:
            team.name = name
        if monthly_reset_policy is not None:
            team.monthly_reset_policy = monthly_reset_policy
        if daily_limit_enabled is not None:
            team.daily_limit_enabled = daily_limit_enabled

        await self.db.commit()
        await self.db.refresh(team)
        return team

    async def delete_team(self, team_id: UUID, user_id: UUID) -> None:
        team = await self.get_team(team_id, user_id)

        # Clear monthly quota from member tokens (they become standalone)
        members_result = await self.db.execute(
            select(TeamMember)
            .where(TeamMember.team_id == team.id)
            .options(joinedload(TeamMember.token))
        )
        for member in members_result.scalars().all():
            if member.token:
                member.token.monthly_quota_usd = None
                member.token.monthly_reset_policy = None
                member.token.monthly_quota_start = None

        await self.db.delete(team)
        await self.db.commit()

    # ------------------------------------------------------------------
    # Member management
    # ------------------------------------------------------------------

    async def add_member(
        self,
        team_id: UUID,
        token_id: UUID,
        allocated_usd: Decimal,
        user_id: UUID,
    ) -> TeamMember:
        team, members, total_allocated = await self._lock_team_and_members(team_id)

        if team.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        if allocated_usd < 0:
            raise HTTPException(status_code=400, detail="Allocation must be >= 0")

        if total_allocated + allocated_usd > team.monthly_budget_usd:
            pool = team.monthly_budget_usd - total_allocated
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Insufficient unallocated pool. "
                    f"Available: ${pool:.2f}, requested: ${allocated_usd:.2f}"
                ),
            )

        # Verify token exists, belongs to same user, not already in a team
        token_result = await self.db.execute(
            select(APIToken).where(APIToken.id == token_id)
        )
        token = token_result.scalar_one_or_none()
        if not token:
            raise HTTPException(status_code=404, detail="Token not found")
        if token.user_id != user_id:
            raise HTTPException(status_code=403, detail="Token does not belong to you")

        existing = await self.db.execute(
            select(TeamMember).where(TeamMember.token_id == token_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=400, detail="Token is already a member of a team"
            )

        # Clear token standalone monthly quota (team takes over)
        token.monthly_quota_usd = None
        token.monthly_reset_policy = None
        token.monthly_quota_start = None

        member = TeamMember(
            team_id=team_id,
            token_id=token_id,
            allocated_usd=allocated_usd,
        )
        self.db.add(member)
        await self.db.commit()
        await self.db.refresh(member)
        return member

    async def remove_member(self, team_id: UUID, token_id: UUID, user_id: UUID) -> None:
        team = await self.get_team(team_id, user_id)

        result = await self.db.execute(
            select(TeamMember).where(
                TeamMember.team_id == team.id, TeamMember.token_id == token_id
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            raise HTTPException(status_code=404, detail="Member not found in this team")

        # Soft-delete the associated token
        token_result = await self.db.execute(
            select(APIToken).where(APIToken.id == token_id)
        )
        token = token_result.scalar_one_or_none()
        if token:
            token.is_active = False
            token.is_deleted = True
            token.deleted_at = datetime.utcnow()

        await self.db.delete(member)
        await self.db.commit()

    async def adjust_member_allocation(
        self,
        team_id: UUID,
        token_id: UUID,
        new_allocated_usd: Decimal,
        user_id: UUID,
    ) -> TeamMember:
        team, members, total_allocated = await self._lock_team_and_members(team_id)

        if team.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        if new_allocated_usd < 0:
            raise HTTPException(status_code=400, detail="Allocation must be >= 0")

        target = None
        for m in members:
            if m.token_id == token_id:
                target = m
                break

        if not target:
            raise HTTPException(status_code=404, detail="Member not found in this team")

        total_others = total_allocated - target.allocated_usd
        if total_others + new_allocated_usd > team.monthly_budget_usd:
            pool = team.monthly_budget_usd - total_others
            raise HTTPException(
                status_code=400,
                detail=(f"Exceeds budget. Max allocation for this member: ${pool:.2f}"),
            )

        target.allocated_usd = new_allocated_usd
        await self.db.commit()
        await self.db.refresh(target)
        return target

    async def transfer_allocation(
        self,
        team_id: UUID,
        from_token_id: UUID,
        to_token_id: UUID,
        amount: Decimal,
        user_id: UUID,
    ) -> None:
        team, members, _ = await self._lock_team_and_members(team_id)

        if team.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        if amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")

        from_member = None
        to_member = None
        for m in members:
            if m.token_id == from_token_id:
                from_member = m
            if m.token_id == to_token_id:
                to_member = m

        if not from_member or not to_member:
            raise HTTPException(
                status_code=404, detail="One or both members not found in this team"
            )

        if from_member.allocated_usd < amount:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Insufficient allocation. "
                    f"Source has: ${from_member.allocated_usd:.2f}, "
                    f"requested: ${amount:.2f}"
                ),
            )

        from_member.allocated_usd -= amount
        to_member.allocated_usd += amount
        await self.db.commit()

    # ------------------------------------------------------------------
    # Batch create members
    # ------------------------------------------------------------------

    async def batch_create_members(
        self,
        team_id: UUID,
        user_id: UUID,
        names: List[str],
        per_member_allocation: Decimal,
        expires_at=None,
        quota_usd=None,
        allowed_ips=None,
        token_metadata=None,
        model_names=None,
    ) -> list[tuple[APIToken, str]]:
        """Create new tokens and add them as team members atomically."""
        from app.services.token import TokenService

        team, members, total_allocated = await self._lock_team_and_members(team_id)

        if team.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        if per_member_allocation < 0:
            raise HTTPException(status_code=400, detail="Allocation must be >= 0")

        needed = per_member_allocation * len(names)
        if total_allocated + needed > team.monthly_budget_usd:
            pool = team.monthly_budget_usd - total_allocated
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Insufficient budget. "
                    f"Available: ${pool:.2f}, needed: ${needed:.2f} "
                    f"({len(names)} × ${per_member_allocation:.2f})"
                ),
            )

        token_service = TokenService(self.db)
        results = await token_service.create_tokens_batch(
            user_id=user_id,
            names=names,
            expires_at=expires_at,
            quota_usd=quota_usd,
            allowed_ips=allowed_ips,
            token_metadata=token_metadata,
            model_names=model_names,
            auto_commit=False,
        )

        for token, _ in results:
            member = TeamMember(
                team_id=team_id,
                token_id=token.id,
                allocated_usd=per_member_allocation,
            )
            self.db.add(member)

        await self.db.commit()

        # Refresh tokens
        token_ids = [t.id for t, _ in results]
        refresh_result = await self.db.execute(
            select(APIToken).where(APIToken.id.in_(token_ids))
        )
        refreshed = {t.id: t for t in refresh_result.scalars().all()}
        return [(refreshed[t.id], pk) for t, pk in results]


async def get_team_membership(token_id: UUID, db: AsyncSession) -> Optional[TeamMember]:
    """Get team membership with team data for a token. Returns None if not in a team."""
    result = await db.execute(
        select(TeamMember)
        .options(joinedload(TeamMember.team))
        .where(TeamMember.token_id == token_id)
    )
    return result.scalar_one_or_none()

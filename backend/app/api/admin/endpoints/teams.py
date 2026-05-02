"""Team management endpoints."""

import calendar
import re
from datetime import datetime
from decimal import Decimal
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_from_jwt
from app.core.database import get_db
from app.models.team import Team, TeamMember
from app.models.token import APIToken
from app.models.usage import UsageRecord
from app.models.user import User
from app.services.team import TeamService

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CreateTeamRequest(BaseModel):
    name: str
    monthly_budget_usd: Decimal
    monthly_reset_policy: str = "reset"
    daily_limit_enabled: bool = True


class UpdateTeamRequest(BaseModel):
    name: str | None = None
    monthly_budget_usd: Decimal | None = None
    monthly_reset_policy: str | None = None
    daily_limit_enabled: bool | None = None


class AddMemberRequest(BaseModel):
    token_id: str
    allocated_usd: Decimal


class AdjustMemberRequest(BaseModel):
    allocated_usd: Decimal


class TransferAllocationRequest(BaseModel):
    from_token_id: str
    to_token_id: str
    amount: Decimal


class BatchCreateMembersRequest(BaseModel):
    names: str
    per_member_allocation: Decimal
    expires_at: datetime | None = None
    quota_usd: Decimal | None = None
    allowed_ips: List[str] | None = None
    token_metadata: dict | None = None
    model_names: List[str] | None = None

    def parsed_names(self) -> List[str]:
        return [
            n for n in (s.strip() for s in re.split(r"[,，;；\n]+", self.names)) if n
        ]


class TeamMemberResponse(BaseModel):
    token_id: str
    token_name: str
    allocated_usd: str
    used_usd: str
    remaining_usd: str
    daily_limit_usd: str
    daily_used_usd: str
    is_active: bool
    last_used_at: datetime | None


class TeamDashboardResponse(BaseModel):
    id: str
    name: str
    monthly_budget_usd: str
    monthly_reset_policy: str
    daily_limit_enabled: bool
    total_allocated_usd: str
    total_used_usd: str
    unallocated_pool_usd: str
    members: List[TeamMemberResponse]


class TeamListItem(BaseModel):
    id: str
    name: str
    monthly_budget_usd: str
    monthly_reset_policy: str
    daily_limit_enabled: bool
    member_count: int
    total_used_usd: str
    unallocated_pool_usd: str
    created_at: datetime


class TeamMemberSimpleResponse(BaseModel):
    token_id: str
    token_name: str
    allocated_usd: str


class BatchCreateMembersResponse(BaseModel):
    created: List[dict]
    total: int


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _invalidate_token_cache(token_hash: str) -> None:
    from app.api.admin.endpoints.tokens import (
        _invalidate_token_cache as _do_invalidate,
    )

    await _do_invalidate(token_hash)


# ---------------------------------------------------------------------------
# Team CRUD
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_team(
    request: CreateTeamRequest,
    current_user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    if request.monthly_reset_policy not in ("reset", "rollover"):
        raise HTTPException(
            status_code=400, detail="monthly_reset_policy must be 'reset' or 'rollover'"
        )
    if request.monthly_budget_usd <= 0:
        raise HTTPException(status_code=400, detail="Budget must be positive")

    service = TeamService(db)
    team = await service.create_team(
        user_id=current_user.id,
        name=request.name,
        monthly_budget_usd=request.monthly_budget_usd,
        monthly_reset_policy=request.monthly_reset_policy,
        daily_limit_enabled=request.daily_limit_enabled,
    )
    return {
        "id": str(team.id),
        "name": team.name,
        "monthly_budget_usd": str(team.monthly_budget_usd),
        "monthly_reset_policy": team.monthly_reset_policy,
        "daily_limit_enabled": team.daily_limit_enabled,
        "unallocated_pool_usd": str(team.monthly_budget_usd),
    }


@router.get("", response_model=List[TeamListItem])
async def list_teams(
    current_user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.utcnow()
    month_start = datetime(now.year, now.month, 1)

    result = await db.execute(
        select(
            Team.id,
            Team.name,
            Team.monthly_budget_usd,
            Team.monthly_reset_policy,
            Team.daily_limit_enabled,
            Team.monthly_budget_start,
            Team.created_at,
            func.count(TeamMember.id).label("member_count"),
            func.coalesce(func.sum(TeamMember.allocated_usd), Decimal("0.00")).label(
                "total_allocated"
            ),
        )
        .outerjoin(TeamMember, TeamMember.team_id == Team.id)
        .where(Team.user_id == current_user.id, Team.is_active)
        .group_by(Team.id)
        .order_by(Team.created_at.desc())
    )
    rows = result.all()

    # Get total monthly usage per team
    team_ids = [row.id for row in rows]
    usage_result = await db.execute(
        select(
            TeamMember.team_id,
            func.coalesce(func.sum(UsageRecord.cost_usd), Decimal("0.00")).label(
                "total_used"
            ),
        )
        .join(UsageRecord, UsageRecord.token_id == TeamMember.token_id)
        .where(
            TeamMember.team_id.in_(team_ids),
            UsageRecord.created_at >= month_start,
        )
        .group_by(TeamMember.team_id)
    )
    usage_map = {row.team_id: row.total_used for row in usage_result.all()}

    return [
        TeamListItem(
            id=str(row.id),
            name=row.name,
            monthly_budget_usd=str(row.monthly_budget_usd),
            monthly_reset_policy=row.monthly_reset_policy,
            daily_limit_enabled=row.daily_limit_enabled,
            member_count=row.member_count,
            total_used_usd=str(usage_map.get(row.id, Decimal("0.00"))),
            unallocated_pool_usd=str(row.monthly_budget_usd - row.total_allocated),
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/{team_id}", response_model=TeamDashboardResponse)
async def get_team_dashboard(
    team_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    try:
        team_uuid = UUID(team_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid team ID")

    team_result = await db.execute(
        select(Team).where(Team.id == team_uuid, Team.user_id == current_user.id)
    )
    team = team_result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    now = datetime.utcnow()
    today = now.date()
    month_start = datetime(today.year, today.month, 1)
    day_start = datetime(today.year, today.month, today.day)

    is_rollover = (team.monthly_reset_policy or "reset") == "rollover"
    monthly_boundary = team.monthly_budget_start if is_rollover else month_start

    result = await db.execute(
        select(
            TeamMember.token_id,
            TeamMember.allocated_usd,
            APIToken.name.label("token_name"),
            APIToken.is_active,
            APIToken.last_used_at,
            func.coalesce(
                func.sum(
                    case(
                        (
                            UsageRecord.created_at >= monthly_boundary,
                            UsageRecord.cost_usd,
                        ),
                        else_=Decimal("0.00"),
                    )
                ),
                Decimal("0.00"),
            ).label("monthly_used"),
            func.coalesce(
                func.sum(
                    case(
                        (UsageRecord.created_at >= day_start, UsageRecord.cost_usd),
                        else_=Decimal("0.00"),
                    )
                ),
                Decimal("0.00"),
            ).label("daily_used"),
        )
        .join(APIToken, TeamMember.token_id == APIToken.id)
        .outerjoin(
            UsageRecord,
            (UsageRecord.token_id == TeamMember.token_id)
            & (UsageRecord.created_at >= monthly_boundary),
        )
        .where(TeamMember.team_id == team_uuid)
        .group_by(
            TeamMember.token_id,
            TeamMember.allocated_usd,
            APIToken.name,
            APIToken.is_active,
            APIToken.last_used_at,
        )
    )
    rows = result.all()

    days_in_month = calendar.monthrange(today.year, today.month)[1]

    members = []
    total_allocated = Decimal("0.00")
    total_used = Decimal("0.00")
    for row in rows:
        daily_limit = row.allocated_usd / Decimal(str(days_in_month))
        remaining = max(Decimal("0.00"), row.allocated_usd - row.monthly_used)
        members.append(
            TeamMemberResponse(
                token_id=str(row.token_id),
                token_name=row.token_name,
                allocated_usd=str(row.allocated_usd),
                used_usd=str(row.monthly_used),
                remaining_usd=str(remaining),
                daily_limit_usd=str(daily_limit),
                daily_used_usd=str(row.daily_used),
                is_active=row.is_active,
                last_used_at=row.last_used_at,
            )
        )
        total_allocated += row.allocated_usd
        total_used += row.monthly_used

    unallocated = team.monthly_budget_usd - total_allocated

    return TeamDashboardResponse(
        id=str(team.id),
        name=team.name,
        monthly_budget_usd=str(team.monthly_budget_usd),
        monthly_reset_policy=team.monthly_reset_policy,
        daily_limit_enabled=team.daily_limit_enabled,
        total_allocated_usd=str(total_allocated),
        total_used_usd=str(total_used),
        unallocated_pool_usd=str(unallocated),
        members=members,
    )


@router.put("/{team_id}")
async def update_team(
    team_id: str,
    request: UpdateTeamRequest,
    current_user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    try:
        team_uuid = UUID(team_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid team ID")

    if request.monthly_reset_policy and request.monthly_reset_policy not in (
        "reset",
        "rollover",
    ):
        raise HTTPException(
            status_code=400, detail="monthly_reset_policy must be 'reset' or 'rollover'"
        )

    service = TeamService(db)
    team = await service.update_team(
        team_id=team_uuid,
        user_id=current_user.id,
        name=request.name,
        monthly_budget_usd=request.monthly_budget_usd,
        monthly_reset_policy=request.monthly_reset_policy,
        daily_limit_enabled=request.daily_limit_enabled,
    )
    return {
        "id": str(team.id),
        "name": team.name,
        "monthly_budget_usd": str(team.monthly_budget_usd),
    }


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    try:
        team_uuid = UUID(team_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid team ID")

    service = TeamService(db)
    await service.delete_team(team_uuid, current_user.id)
    return None


# ---------------------------------------------------------------------------
# Member management
# ---------------------------------------------------------------------------


@router.post("/{team_id}/members", response_model=TeamMemberSimpleResponse)
async def add_member(
    team_id: str,
    request: AddMemberRequest,
    current_user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    try:
        team_uuid = UUID(team_id)
        token_uuid = UUID(request.token_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")

    service = TeamService(db)
    member = await service.add_member(
        team_id=team_uuid,
        token_id=token_uuid,
        allocated_usd=request.allocated_usd,
        user_id=current_user.id,
    )

    # Invalidate token cache
    token_result = await db.execute(
        select(APIToken.token_hash).where(APIToken.id == token_uuid)
    )
    token_hash = token_result.scalar_one_or_none()
    if token_hash:
        await _invalidate_token_cache(token_hash)

    # Get token name
    token_result = await db.execute(
        select(APIToken.name).where(APIToken.id == token_uuid)
    )
    token_name = token_result.scalar_one_or_none() or ""

    return TeamMemberSimpleResponse(
        token_id=str(member.token_id),
        token_name=token_name,
        allocated_usd=str(member.allocated_usd),
    )


@router.delete("/{team_id}/members/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    team_id: str,
    token_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    try:
        team_uuid = UUID(team_id)
        token_uuid = UUID(token_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")

    # Get token hash before removal for cache invalidation
    token_result = await db.execute(
        select(APIToken.token_hash).where(APIToken.id == token_uuid)
    )
    token_hash = token_result.scalar_one_or_none()

    service = TeamService(db)
    await service.remove_member(team_uuid, token_uuid, current_user.id)

    if token_hash:
        await _invalidate_token_cache(token_hash)

    return None


@router.put("/{team_id}/members/{token_id}", response_model=TeamMemberSimpleResponse)
async def adjust_member(
    team_id: str,
    token_id: str,
    request: AdjustMemberRequest,
    current_user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    try:
        team_uuid = UUID(team_id)
        token_uuid = UUID(token_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")

    service = TeamService(db)
    member = await service.adjust_member_allocation(
        team_id=team_uuid,
        token_id=token_uuid,
        new_allocated_usd=request.allocated_usd,
        user_id=current_user.id,
    )

    # Invalidate cache
    token_result = await db.execute(
        select(APIToken.token_hash).where(APIToken.id == token_uuid)
    )
    token_hash = token_result.scalar_one_or_none()
    if token_hash:
        await _invalidate_token_cache(token_hash)

    token_result = await db.execute(
        select(APIToken.name).where(APIToken.id == token_uuid)
    )
    token_name = token_result.scalar_one_or_none() or ""

    return TeamMemberSimpleResponse(
        token_id=str(member.token_id),
        token_name=token_name,
        allocated_usd=str(member.allocated_usd),
    )


@router.post("/{team_id}/transfer", status_code=status.HTTP_200_OK)
async def transfer_allocation(
    team_id: str,
    request: TransferAllocationRequest,
    current_user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    try:
        team_uuid = UUID(team_id)
        from_uuid = UUID(request.from_token_id)
        to_uuid = UUID(request.to_token_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")

    service = TeamService(db)
    await service.transfer_allocation(
        team_id=team_uuid,
        from_token_id=from_uuid,
        to_token_id=to_uuid,
        amount=request.amount,
        user_id=current_user.id,
    )

    # Invalidate caches for both tokens
    for tid in (from_uuid, to_uuid):
        result = await db.execute(select(APIToken.token_hash).where(APIToken.id == tid))
        token_hash = result.scalar_one_or_none()
        if token_hash:
            await _invalidate_token_cache(token_hash)

    return {
        "from_token_id": request.from_token_id,
        "to_token_id": request.to_token_id,
        "amount": str(request.amount),
    }


# ---------------------------------------------------------------------------
# Batch create members
# ---------------------------------------------------------------------------


@router.post(
    "/{team_id}/members/batch",
    response_model=BatchCreateMembersResponse,
    status_code=status.HTTP_201_CREATED,
)
async def batch_create_members(
    team_id: str,
    request: BatchCreateMembersRequest,
    current_user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    try:
        team_uuid = UUID(team_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid team ID")

    names = request.parsed_names()
    if not names:
        raise HTTPException(status_code=400, detail="No valid names provided")
    if len(names) > 100:
        raise HTTPException(
            status_code=400, detail=f"Too many names ({len(names)}), maximum is 100"
        )

    service = TeamService(db)
    results = await service.batch_create_members(
        team_id=team_uuid,
        user_id=current_user.id,
        names=names,
        per_member_allocation=request.per_member_allocation,
        expires_at=request.expires_at,
        quota_usd=request.quota_usd,
        allowed_ips=request.allowed_ips,
        token_metadata=request.token_metadata,
        model_names=request.model_names,
    )

    created = []
    for token, plain_token in results:
        created.append(
            {
                "token_id": str(token.id),
                "token_name": token.name,
                "token": plain_token,
                "allocated_usd": str(request.per_member_allocation),
            }
        )

    return BatchCreateMembersResponse(created=created, total=len(created))

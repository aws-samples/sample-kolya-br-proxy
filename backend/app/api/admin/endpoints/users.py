"""Admin user management endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_audit_log_service, get_current_superadmin
from app.core.database import get_db
from app.models.audit_log import AuditAction
from app.models.model import Model
from app.models.team import Team
from app.models.token import APIToken
from app.models.user import User, UserRole
from app.services.audit_log import AuditLogService

router = APIRouter()

VALID_ROLES = {r.value for r in UserRole}


class AdminUserResponse(BaseModel):
    id: str
    email: str
    first_name: str | None
    last_name: str | None
    role: str
    permissions: dict | None
    is_active: bool
    created_at: str
    last_login_at: str | None

    @classmethod
    def from_user(cls, u: User) -> "AdminUserResponse":
        return cls(
            id=str(u.id),
            email=u.email,
            first_name=u.first_name,
            last_name=u.last_name,
            role=u.role.value,
            permissions=u.permissions,
            is_active=u.is_active,
            created_at=u.created_at.isoformat(),
            last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
        )


class InviteAdminRequest(BaseModel):
    email: EmailStr
    role: str = "admin"
    permissions: dict | None = None


class UpdateAdminRequest(BaseModel):
    role: str | None = None
    permissions: dict | None = None
    is_active: bool | None = None


@router.get("/resources")
async def list_assignable_resources(
    current_user: User = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """List all resources (tokens, teams, models) for permission assignment."""
    tokens_result = await db.execute(
        select(APIToken.id, APIToken.name)
        .where(APIToken.is_active.is_(True), APIToken.is_deleted.is_(False))
        .order_by(APIToken.name)
    )
    teams_result = await db.execute(select(Team.id, Team.name).order_by(Team.name))
    models_result = await db.execute(
        select(Model.id, Model.model_name)
        .where(Model.is_active.is_(True), Model.is_deleted.is_(False))
        .order_by(Model.model_name)
    )
    return {
        "api_keys": [{"id": str(r.id), "name": r.name} for r in tokens_result.all()],
        "teams": [{"id": str(r.id), "name": r.name} for r in teams_result.all()],
        "models": [
            {"id": str(r.id), "name": r.model_name} for r in models_result.all()
        ],
    }


@router.get("", response_model=List[AdminUserResponse])
async def list_admin_users(
    current_user: User = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """List all admin users (super_admin and admin roles)."""
    result = await db.execute(
        select(User)
        .where(User.role.in_([UserRole.SUPER_ADMIN, UserRole.ADMIN]))
        .where(User.is_active.is_(True))
        .order_by(User.created_at.desc())
    )
    users = result.scalars().all()

    return [AdminUserResponse.from_user(u) for u in users]


@router.post("", response_model=AdminUserResponse, status_code=status.HTTP_201_CREATED)
async def invite_admin(
    request: InviteAdminRequest,
    current_user: User = Depends(get_current_superadmin),
    audit_service: AuditLogService = Depends(get_audit_log_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Invite a new admin by email (pre-registration).
    The invited user will be activated when they first login via OAuth.
    """
    if request.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role must be one of: {', '.join(VALID_ROLES)}",
        )

    existing = await db.execute(select(User).where(User.email == request.email))
    user = existing.scalar_one_or_none()

    role = UserRole(request.role)

    if user:
        if user.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User with this email already exists",
            )
        # Reactivate previously deactivated user
        user.is_active = True
        user.role = role
        user.permissions = request.permissions
        user.is_admin = True
    else:
        user = User(
            email=request.email,
            role=role,
            permissions=request.permissions,
            is_active=True,
            is_admin=True,
            email_verified=False,
        )
        db.add(user)

    await db.commit()
    await db.refresh(user)

    await audit_service.log(
        action=AuditAction.ADMIN_CREATED,
        user=current_user,
        resource_type="user",
        resource_id=str(user.id),
        details={"email": user.email, "role": request.role},
    )

    return AdminUserResponse.from_user(user)


@router.put("/{user_id}", response_model=AdminUserResponse)
async def update_admin(
    user_id: UUID,
    request: UpdateAdminRequest,
    current_user: User = Depends(get_current_superadmin),
    audit_service: AuditLogService = Depends(get_audit_log_service),
    db: AsyncSession = Depends(get_db),
):
    """Update admin user role or permissions."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if request.role is not None:
        if request.role not in VALID_ROLES:
            raise HTTPException(status_code=400, detail="Invalid role")
        user.role = UserRole(request.role)

    if request.permissions is not None:
        user.permissions = request.permissions

    if request.is_active is not None:
        user.is_active = request.is_active

    await db.commit()
    await db.refresh(user)

    await audit_service.log(
        action=AuditAction.ADMIN_UPDATED,
        user=current_user,
        resource_type="user",
        resource_id=str(user.id),
        details={"email": user.email, "changes": request.model_dump(exclude_none=True)},
    )

    return AdminUserResponse.from_user(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_admin(
    user_id: UUID,
    current_user: User = Depends(get_current_superadmin),
    audit_service: AuditLogService = Depends(get_audit_log_service),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate an admin user."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    await db.commit()

    await audit_service.log(
        action=AuditAction.ADMIN_DELETED,
        user=current_user,
        resource_type="user",
        resource_id=str(user.id),
        details={"email": user.email},
    )

    return None

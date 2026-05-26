"""Admin user management endpoints."""

import asyncio
import logging
from functools import lru_cache
from typing import List
from uuid import UUID

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_audit_log_service, get_current_superadmin
from app.core.config import get_settings
from app.core.database import get_db
from app.models.audit_log import AuditAction
from app.models.team import Team
from app.models.token import APIToken
from app.models.user import User, UserRole
from app.services.audit_log import AuditLogService

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_ROLES = {r.value for r in UserRole}


@lru_cache()
def _get_cognito_client():
    settings = get_settings()
    return boto3.client(
        "cognito-idp",
        region_name=settings.COGNITO_REGION or settings.AWS_REGION,
    )


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
    username: str
    temp_password: str
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
        .where(APIToken.is_deleted.is_(False))
        .order_by(APIToken.name)
    )
    teams_result = await db.execute(select(Team.id, Team.name).order_by(Team.name))
    # Reuse the aws-available endpoint (includes Bedrock + Gemini, cached 12h)
    from app.api.admin.endpoints.models import list_aws_available_models

    aws_result = await list_aws_available_models(current_user)
    all_models = aws_result.get("models", [])
    models = [{"id": m["model_id"], "name": m["model_id"]} for m in all_models]
    return {
        "api_keys": [{"id": str(r.id), "name": r.name} for r in tokens_result.all()],
        "teams": [{"id": str(r.id), "name": r.name} for r in teams_result.all()],
        "models": models,
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
    Invite a new admin by email.
    Creates a Cognito user with temporary password and a local user record.
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

    # Create Cognito user with temporary password
    settings = get_settings()
    if settings.COGNITO_USER_POOL_ID:
        cognito_username = request.username
        if "@" in cognito_username:
            cognito_username = cognito_username.split("@")[0]

        cognito_client = _get_cognito_client()
        try:
            await asyncio.to_thread(
                cognito_client.admin_create_user,
                UserPoolId=settings.COGNITO_USER_POOL_ID,
                Username=cognito_username,
                TemporaryPassword=request.temp_password,
                UserAttributes=[
                    {"Name": "email", "Value": request.email},
                    {"Name": "email_verified", "Value": "true"},
                ],
                MessageAction="SUPPRESS",
            )
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "UsernameExistsException":
                try:
                    await asyncio.to_thread(
                        cognito_client.admin_set_user_password,
                        UserPoolId=settings.COGNITO_USER_POOL_ID,
                        Username=cognito_username,
                        Password=request.temp_password,
                        Permanent=False,
                    )
                except ClientError as reset_err:
                    logger.error(f"Failed to reset Cognito password: {reset_err}")
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to reset Cognito password: {reset_err.response['Error']['Message']}",
                    )
            else:
                logger.error(f"Failed to create Cognito user: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to create Cognito user: {e.response['Error']['Message']}",
                )

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
    """Deactivate an admin user and remove from Cognito."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    settings = get_settings()
    if settings.COGNITO_USER_POOL_ID:
        cognito_client = _get_cognito_client()
        # Look up actual Cognito username by email (may differ from email prefix)
        cognito_username = None
        try:
            list_resp = await asyncio.to_thread(
                cognito_client.list_users,
                UserPoolId=settings.COGNITO_USER_POOL_ID,
                Filter=f'email = "{user.email}"',
                Limit=1,
            )
            if list_resp.get("Users"):
                cognito_username = list_resp["Users"][0]["Username"]
        except ClientError as e:
            logger.error(f"Failed to look up Cognito user by email {user.email}: {e}")

        if cognito_username:
            try:
                await asyncio.to_thread(
                    cognito_client.admin_delete_user,
                    UserPoolId=settings.COGNITO_USER_POOL_ID,
                    Username=cognito_username,
                )
            except ClientError as e:
                if e.response["Error"]["Code"] != "UserNotFoundException":
                    logger.error(
                        f"Failed to delete Cognito user {cognito_username}: {e}"
                    )

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

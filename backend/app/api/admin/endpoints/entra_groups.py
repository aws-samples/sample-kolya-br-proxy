"""Entra ID group mapping management endpoints."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_audit_log_service, get_current_superadmin
from app.core.database import get_db
from app.models.audit_log import AuditAction
from app.models.entra_group_mapping import EntraGroupMapping
from app.models.user import User, UserRole
from app.services.audit_log import AuditLogService

router = APIRouter()

VALID_ROLES = {r.value for r in UserRole}


class EntraGroupMappingResponse(BaseModel):
    id: str
    entra_group_id: str
    group_name: str
    role: str
    permissions: dict | None
    priority: int
    created_at: str
    updated_at: str

    @classmethod
    def from_model(cls, m: EntraGroupMapping) -> "EntraGroupMappingResponse":
        return cls(
            id=str(m.id),
            entra_group_id=m.entra_group_id,
            group_name=m.group_name,
            role=m.role.value,
            permissions=m.permissions,
            priority=m.priority,
            created_at=m.created_at.isoformat(),
            updated_at=m.updated_at.isoformat(),
        )


class CreateEntraGroupMappingRequest(BaseModel):
    entra_group_id: str
    group_name: str
    role: str = "admin"
    permissions: dict | None = None
    priority: int = 0


class UpdateEntraGroupMappingRequest(BaseModel):
    group_name: str | None = None
    role: str | None = None
    permissions: dict | None = None
    priority: int | None = None


@router.get("", response_model=List[EntraGroupMappingResponse])
async def list_entra_group_mappings(
    current_user: User = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(EntraGroupMapping).order_by(EntraGroupMapping.priority.desc())
    )
    mappings = result.scalars().all()
    return [EntraGroupMappingResponse.from_model(m) for m in mappings]


@router.post(
    "", response_model=EntraGroupMappingResponse, status_code=status.HTTP_201_CREATED
)
async def create_entra_group_mapping(
    request: CreateEntraGroupMappingRequest,
    current_user: User = Depends(get_current_superadmin),
    audit_service: AuditLogService = Depends(get_audit_log_service),
    db: AsyncSession = Depends(get_db),
):
    if request.role not in VALID_ROLES:
        raise HTTPException(
            status_code=400, detail=f"Role must be one of: {', '.join(VALID_ROLES)}"
        )

    existing = await db.execute(
        select(EntraGroupMapping).where(
            EntraGroupMapping.entra_group_id == request.entra_group_id
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Group mapping already exists")

    mapping = EntraGroupMapping(
        entra_group_id=request.entra_group_id,
        group_name=request.group_name,
        role=UserRole(request.role),
        permissions=request.permissions,
        priority=request.priority,
    )
    db.add(mapping)
    await db.commit()
    await db.refresh(mapping)

    await audit_service.log(
        action=AuditAction.ADMIN_CREATED,
        user=current_user,
        resource_type="entra_group_mapping",
        resource_id=str(mapping.id),
        details={
            "group_name": mapping.group_name,
            "entra_group_id": mapping.entra_group_id,
        },
    )

    return EntraGroupMappingResponse.from_model(mapping)


@router.put("/{mapping_id}", response_model=EntraGroupMappingResponse)
async def update_entra_group_mapping(
    mapping_id: UUID,
    request: UpdateEntraGroupMappingRequest,
    current_user: User = Depends(get_current_superadmin),
    audit_service: AuditLogService = Depends(get_audit_log_service),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(EntraGroupMapping).where(EntraGroupMapping.id == mapping_id)
    )
    mapping = result.scalar_one_or_none()
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    if request.group_name is not None:
        mapping.group_name = request.group_name
    if request.role is not None:
        if request.role not in VALID_ROLES:
            raise HTTPException(status_code=400, detail="Invalid role")
        mapping.role = UserRole(request.role)
    if request.permissions is not None:
        mapping.permissions = request.permissions
    if request.priority is not None:
        mapping.priority = request.priority

    await db.commit()
    await db.refresh(mapping)

    await audit_service.log(
        action=AuditAction.ADMIN_UPDATED,
        user=current_user,
        resource_type="entra_group_mapping",
        resource_id=str(mapping.id),
        details={"changes": request.model_dump(exclude_none=True)},
    )

    return EntraGroupMappingResponse.from_model(mapping)


@router.delete("/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entra_group_mapping(
    mapping_id: UUID,
    current_user: User = Depends(get_current_superadmin),
    audit_service: AuditLogService = Depends(get_audit_log_service),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(EntraGroupMapping).where(EntraGroupMapping.id == mapping_id)
    )
    mapping = result.scalar_one_or_none()
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    group_name = mapping.group_name
    await db.delete(mapping)
    await db.commit()

    await audit_service.log(
        action=AuditAction.ADMIN_DELETED,
        user=current_user,
        resource_type="entra_group_mapping",
        resource_id=str(mapping_id),
        details={"group_name": group_name},
    )

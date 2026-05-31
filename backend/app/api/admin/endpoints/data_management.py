"""
Data management endpoints for exporting and importing application configuration.
Super-admin only.
"""

import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_audit_log_service, get_current_superadmin
from app.core.database import get_db
from app.models.audit_log import AuditAction
from app.models.user import User
from app.services.audit_log import AuditLogService
from app.services.data_management import DataManagementService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/export")
async def export_config(
    current_user: User = Depends(get_current_superadmin),
    audit_service: AuditLogService = Depends(get_audit_log_service),
    db: AsyncSession = Depends(get_db),
):
    """Export all application configuration as a downloadable JSON file."""
    service = DataManagementService(db)
    data = await service.export_config(exported_by=current_user.email)

    await audit_service.log(
        action=AuditAction.DATA_EXPORTED,
        user=current_user,
        resource_type="config",
        details={
            "sections": list(data["sections"].keys()),
            "counts": {k: len(v) for k, v in data["sections"].items()},
        },
    )

    content = json.dumps(data, indent=2, ensure_ascii=False)
    filename = f"config_export_{data['exported_at'][:10].replace('-', '')}.json"

    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/import")
async def import_config(
    file: UploadFile = File(...),
    conflict_strategy: str = Form("skip"),
    current_user: User = Depends(get_current_superadmin),
    audit_service: AuditLogService = Depends(get_audit_log_service),
    db: AsyncSession = Depends(get_db),
):
    """Import application configuration from a JSON file."""
    if conflict_strategy not in ("skip", "overwrite"):
        raise HTTPException(
            status_code=400, detail="conflict_strategy must be 'skip' or 'overwrite'"
        )

    # Read and parse file
    try:
        content = await file.read()
        data = json.loads(content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON file: {e}")

    # Validate structure
    if "version" not in data or "sections" not in data:
        raise HTTPException(
            status_code=400,
            detail="Invalid file format: missing 'version' or 'sections'",
        )

    service = DataManagementService(db)
    try:
        results = await service.import_config(data, conflict_strategy)
    except Exception as e:
        logger.exception("Import failed")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Import failed: {e}")

    await audit_service.log(
        action=AuditAction.DATA_IMPORTED,
        user=current_user,
        resource_type="config",
        details={
            "conflict_strategy": conflict_strategy,
            "results": {
                k: {kk: vv for kk, vv in v.items() if kk != "generated_keys"}
                for k, v in results.items()
            },
        },
    )

    return results

"""Trace inspection endpoints.

Traces hold full prompt and response bodies, so reads are scoped to the
tokens the caller may manage (same scope as usage stats) and clearing the
shared buffer is reserved for super_admin.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import (
    get_allowed_resource_ids,
    get_audit_log_service,
    get_current_superadmin,
    require_permission,
)
from app.models.audit_log import AuditAction
from app.models.user import User, UserRole
from app.services.audit_log import AuditLogService
from app.services.trace_store import TraceStore

router = APIRouter()


def _visible_token_ids(user: User) -> Optional[set[str]]:
    """Token IDs whose traces the user may read; None means all."""
    # Viewers read every dashboard page, but traces carry raw prompt and
    # response bodies, which a read-only role should not see.
    if user.role == UserRole.VIEWER:
        return set()
    allowed = get_allowed_resource_ids(user, "manage_api_keys")
    return None if allowed is None else set(allowed)


def _is_visible(trace: dict, visible: Optional[set[str]]) -> bool:
    return visible is None or trace.get("token_id") in visible


@router.get("/")
async def list_traces(
    current_user: User = Depends(require_permission("view_usage")),
):
    """List recent traces (newest first) for tokens the caller can access."""
    visible = _visible_token_ids(current_user)
    traces = [
        t for t in TraceStore.get_instance().list_all() if _is_visible(t, visible)
    ]
    return {
        "enabled": TraceStore.is_enabled(),
        "count": len(traces),
        "traces": traces,
    }


@router.get("/{request_id}")
async def get_trace(
    request_id: str,
    current_user: User = Depends(require_permission("view_usage")),
):
    """Get a single trace by request_id."""
    trace = TraceStore.get_instance().get(request_id)
    # Out-of-scope traces return 404, not 403, so their IDs can't be probed.
    if not trace or not _is_visible(trace, _visible_token_ids(current_user)):
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


@router.delete("/")
async def clear_traces(
    current_user: User = Depends(get_current_superadmin),
    audit_service: AuditLogService = Depends(get_audit_log_service),
):
    """Clear all stored traces. The buffer is shared, so super_admin only."""
    TraceStore.get_instance().clear()
    await audit_service.log(
        action=AuditAction.OBSERVABILITY_UPDATED,
        user=current_user,
        resource_type="trace_buffer",
        details={"op": "traces_cleared"},
    )
    return {"message": "Traces cleared"}

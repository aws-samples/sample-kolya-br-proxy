"""Trace inspection endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_permission
from app.models.user import User
from app.services.trace_store import TraceStore

router = APIRouter()


@router.get("/")
async def list_traces(
    current_user: User = Depends(require_permission("view_usage")),
):
    """List recent traces (newest first)."""
    store = TraceStore.get_instance()
    return {
        "enabled": TraceStore.is_enabled(),
        "count": store.size,
        "traces": store.list_all(),
    }


@router.get("/{request_id}")
async def get_trace(
    request_id: str,
    current_user: User = Depends(require_permission("view_usage")),
):
    """Get a single trace by request_id."""
    store = TraceStore.get_instance()
    trace = store.get(request_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


@router.delete("/")
async def clear_traces(
    current_user: User = Depends(require_permission("view_usage")),
):
    """Clear all stored traces."""
    store = TraceStore.get_instance()
    store.clear()
    return {"message": "Traces cleared"}

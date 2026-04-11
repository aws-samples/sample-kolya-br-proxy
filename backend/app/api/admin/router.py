"""
Admin API router for management dashboard.
All endpoints require JWT authentication.
"""

from fastapi import APIRouter

from app.api.admin.endpoints import (
    audit,
    auth,
    models,
    tokens,
    usage,
    pricing,
    monitor,
    observability,
)

admin_router = APIRouter()

# Authentication endpoints (no auth required for login/register)
admin_router.include_router(auth.router, prefix="/auth", tags=["admin-auth"])

# Token management endpoints (JWT auth required)
admin_router.include_router(tokens.router, prefix="/tokens", tags=["admin-tokens"])

# Models management endpoints (JWT auth required)
admin_router.include_router(models.router, prefix="/models", tags=["admin-models"])

# Usage statistics endpoints (JWT auth required)
admin_router.include_router(usage.router, prefix="/usage", tags=["admin-usage"])

# Audit log endpoints (JWT auth required)
admin_router.include_router(audit.router, prefix="/audit-logs", tags=["admin-audit"])

# Pricing management endpoints (JWT auth required)
admin_router.include_router(pricing.router, prefix="/pricing", tags=["admin-pricing"])

# Monitor endpoints (JWT auth required)
admin_router.include_router(monitor.router, prefix="/monitor", tags=["admin-monitor"])

# Observability runtime config (JWT auth required)
admin_router.include_router(
    observability.router, prefix="/observability", tags=["admin-observability"]
)

# TODO: Add more admin endpoints
# admin_router.include_router(users.router, prefix="/users", tags=["admin-users"])


@admin_router.get("/")
async def admin_root():
    """Admin API root endpoint."""
    return {
        "message": "Kolya BR Proxy - Admin API",
        "version": "1.0.0",
        "endpoints": {
            "auth": "/admin/auth",
            "tokens": "/admin/tokens",
            "usage": "/admin/usage",
            "audit_logs": "/admin/audit-logs",
            "pricing": "/admin/pricing",
            "docs": "/docs",
        },
    }

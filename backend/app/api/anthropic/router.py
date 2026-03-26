"""
Anthropic Messages API compatible router.
All endpoints require API key authentication via x-api-key header.
"""

from fastapi import APIRouter

from app.api.anthropic.endpoints import messages

anthropic_router = APIRouter()

# Include Anthropic Messages endpoint
anthropic_router.include_router(messages.router, tags=["anthropic-messages"])


@anthropic_router.get("/")
async def anthropic_root():
    """Anthropic API root endpoint."""
    return {
        "message": "Kolya BR Proxy - Anthropic Messages API",
        "version": "1.0.0",
        "compatible_with": "Anthropic Messages API",
        "endpoints": {
            "messages": "/v1/messages",
        },
    }

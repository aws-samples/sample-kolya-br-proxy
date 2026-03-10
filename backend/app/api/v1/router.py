"""
AI Gateway API v1 router (OpenAI compatible).
All endpoints require API Token authentication.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import chat, models

gateway_router = APIRouter()

# Include AI Gateway endpoint routers
gateway_router.include_router(chat.router, tags=["chat"])
gateway_router.include_router(models.router, tags=["models"])


@gateway_router.get("/")
async def gateway_root():
    """AI Gateway API v1 root endpoint."""
    return {
        "message": "Kolya BR Proxy - AI Gateway API",
        "version": "1.0.0",
        "compatible_with": "OpenAI API v1",
        "endpoints": {
            "chat_completions": "/v1/chat/completions",
            "models": "/v1/models",
        },
    }

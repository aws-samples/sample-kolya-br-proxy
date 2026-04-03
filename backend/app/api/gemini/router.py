"""
Gemini native API compatible router.

Supports authentication via query parameter ``key`` or header
``x-goog-api-key``, matching the Google Gemini SDK conventions.
"""

from fastapi import APIRouter

from app.api.gemini.endpoints import generate

gemini_router = APIRouter()

# Include Gemini generateContent / streamGenerateContent endpoints
gemini_router.include_router(generate.router, tags=["gemini-generate"])

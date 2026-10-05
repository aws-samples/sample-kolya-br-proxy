# pyright: reportMissingImports=false
"""Shared model authorization for embedding protocol adapters."""

from typing import cast

from fastapi import HTTPException
from sqlalchemy import select

from app.core.database import session_scope
from app.models.model import Model
from app.models.token import APIToken
from app.services.bedrock import match_allowed_model
from app.services.embedding_models import SUPPORTED_EMBEDDING_MODELS
from app.services.quota import enforce_quota


async def authorize_embedding_model(token: APIToken, requested_model: str) -> str:
    """Enforce quota and the token's active model allowlist."""
    if requested_model not in SUPPORTED_EMBEDDING_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{requested_model}' is not supported by the embeddings API",
        )

    async with session_scope() as db:
        await enforce_quota(token, db)
        result = await db.execute(
            select(Model).where(
                Model.token_id == token.id,
                Model.is_active,
                ~Model.is_deleted,
            )
        )
        allowed: list[str] = [
            cast(str, model.model_name) for model in result.scalars().all()
        ]

    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="Token does not have access to any models",
        )
    matched = match_allowed_model(requested_model, allowed)
    if matched is None:
        raise HTTPException(
            status_code=403,
            detail=f"Token does not have access to model: {requested_model}",
        )
    return requested_model

"""
Admin models management endpoints.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_from_jwt
from app.core.config import get_settings
from app.core.database import get_db
from app.models.model import Model
from app.services.bedrock import BedrockClient
from app.services.gemini_client import GeminiClient

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()

# Cache for AWS Bedrock models list (12 hours)
_aws_models_cache: Optional[List[Dict]] = None
_cache_timestamp: Optional[datetime] = None
CACHE_DURATION_HOURS = 12


class BedrockModelInfo(BaseModel):
    """Bedrock model information from AWS."""

    model_id: str
    model_name: str
    friendly_name: str
    provider: str
    streaming_supported: bool


class EnabledModelResponse(BaseModel):
    """Enabled model with AWS info."""

    id: str
    model_name: str
    model_id: str
    friendly_name: str
    provider: str
    streaming_supported: bool
    is_active: bool


class AddModelRequest(BaseModel):
    """Request to add a model."""

    token_id: str
    model_name: str


def _get_aws_models_cache() -> Optional[List[Dict]]:
    """Get AWS models from cache if still valid."""
    global _aws_models_cache, _cache_timestamp

    if _aws_models_cache is None or _cache_timestamp is None:
        return None

    # Check if cache is still valid (12 hours)
    if datetime.utcnow() - _cache_timestamp > timedelta(hours=CACHE_DURATION_HOURS):
        logger.info("AWS models cache expired, will refresh")
        return None

    logger.info("Returning AWS models from cache")
    return _aws_models_cache


def _set_aws_models_cache(models: List[Dict]):
    """Set AWS models cache."""
    global _aws_models_cache, _cache_timestamp
    _aws_models_cache = models
    _cache_timestamp = datetime.utcnow()
    logger.info(f"AWS models cache updated with {len(models)} models")


def _get_model_id_from_cache(model_name: str) -> Optional[str]:
    """Get model_id from cache by model_name (full model_id match)."""
    if _aws_models_cache is None:
        return None

    for model in _aws_models_cache:
        if model.get("model_id") == model_name:
            return model.get("model_id")

    return None


@router.get("/aws-available")
async def list_aws_available_models(
    _current_user=Depends(get_current_user_from_jwt),
):
    """
    Get list of available Bedrock models from AWS (for selection).

    Returns models that the proxy can actually invoke:
    * Inference profiles available in the deployment region
    * Foundation models available in the deployment region
    * Foundation models available in the fallback region (routed automatically)

    Results are cached for 12 hours in memory. The underlying profile cache
    is refreshed at startup and daily at 03:00 UTC.
    """
    # Check in-memory cache first
    cached_models = _get_aws_models_cache()
    if cached_models is not None:
        return {"models": cached_models}

    try:
        bc = BedrockClient.get_instance()

        # Refresh profile cache if stale or empty
        if bc._profile_cache.is_stale or bc._profile_cache.is_empty:
            await bc.refresh_profile_cache()

        # Build model list from the profile cache
        raw_models = bc._profile_cache.get_all_available_models()

        models = []
        for m in raw_models:
            model_id = m["model_id"]
            base_id = m["base_model_id"]

            # Derive friendly name from base model ID
            # e.g. "anthropic.claude-sonnet-4-6" → "Claude Sonnet 4.6"
            friendly_name = base_id
            if m["cross_region_type"]:
                # For profiles, use prefix + base for display
                friendly_name = base_id

            models.append(
                {
                    "model_id": model_id,
                    "model_name": friendly_name,
                    "friendly_name": friendly_name,
                    "provider": "bedrock-converse",
                    "is_cross_region": m["is_cross_region"],
                    "cross_region_type": m["cross_region_type"],
                    "streaming_supported": True,
                    "is_fallback": m.get("is_fallback", False),
                }
            )

        # Sort: cross-region first, then by model_id
        models.sort(key=lambda m: (not m["is_cross_region"], m["model_id"]))

        logger.info(f"Built model list from profile cache: {len(models)} models")

        # Append Gemini models dynamically (only if API key is configured)
        if settings.GEMINI_API_KEY:
            try:
                gemini_models = await GeminiClient.list_models(settings.GEMINI_API_KEY)
                models.extend(gemini_models)
                logger.info(
                    f"Added {len(gemini_models)} Gemini models to available list"
                )
            except Exception as e:
                logger.warning(f"Failed to fetch Gemini models (non-fatal): {e}")

        # Cache the results
        _set_aws_models_cache(models)

        return {"models": models}

    except Exception as e:
        logger.error(f"Failed to list Bedrock models: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve models from AWS Bedrock: {str(e)}",
        )


@router.get("")
async def list_enabled_models(
    token_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user_from_jwt),
):
    """
    Get list of enabled models from PostgreSQL.

    Returns models that user has added, with model_id fetched from AWS cache.
    If token_id is provided, only returns models for that token.
    """
    try:
        # Get enabled models from database (exclude deleted)
        query = select(Model).where(Model.is_active, Model.is_deleted.is_(False))

        # Filter by token_id if provided
        if token_id:
            try:
                token_uuid = UUID(token_id)
                query = query.where(Model.token_id == token_uuid)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid token_id format",
                )

        result = await db.execute(query)
        db_models = result.scalars().all()

        # Ensure AWS cache is populated
        if _aws_models_cache is None:
            # Trigger cache refresh
            await list_aws_available_models(_current_user)

        # Build response: model_name in DB is the full model_id
        # (e.g., "global.amazon.nova-pro-v1:0" or "meta.llama3-3-70b-instruct-v1:0")
        enabled_models = []
        for db_model in db_models:
            # The model_name stored in DB IS the model_id used in requests
            model_id = db_model.model_name

            # Try to find additional info from AWS cache
            model_info = None
            if _aws_models_cache:
                for cached_model in _aws_models_cache:
                    if cached_model.get("model_id") == model_id:
                        model_info = cached_model
                        break

            if model_info:
                enabled_models.append(
                    {
                        "id": str(db_model.id),
                        "model_name": db_model.model_name,
                        "model_id": model_id,
                        "friendly_name": model_info.get("friendly_name", model_id),
                        "provider": model_info.get("provider", "bedrock-converse"),
                        "streaming_supported": model_info.get(
                            "streaming_supported", False
                        ),
                        "is_active": db_model.is_active,
                    }
                )
            else:
                # Model not found in AWS cache (maybe deprecated)
                enabled_models.append(
                    {
                        "id": str(db_model.id),
                        "model_name": db_model.model_name,
                        "model_id": model_id,
                        "friendly_name": model_id,
                        "provider": "bedrock-converse",
                        "streaming_supported": False,
                        "is_active": db_model.is_active,
                    }
                )

        return {"models": enabled_models}

    except Exception as e:
        logger.error(f"Failed to list enabled models: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve enabled models: {str(e)}",
        )


@router.post("")
async def add_model(
    request: AddModelRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user_from_jwt),
):
    """
    Add a model to enabled list for a specific token.

    User selects a model from AWS available models and adds it to PostgreSQL
    with association to a specific API token.
    """
    try:
        # Validate token_id
        token_uuid = UUID(request.token_id)

        # Check if model already exists for this token
        result = await db.execute(
            select(Model).where(
                Model.token_id == token_uuid, Model.model_name == request.model_name
            )
        )
        existing_model = result.scalar_one_or_none()

        if existing_model:
            if existing_model.is_active:
                raise HTTPException(
                    status_code=400,
                    detail=f"Model {request.model_name} is already enabled for this token",
                )
            else:
                # Reactivate
                existing_model.is_active = True
                existing_model.is_deleted = False
                existing_model.deleted_at = None
                await db.commit()
                return {"message": f"Model {request.model_name} reactivated"}

        # Create new model
        new_model = Model(
            token_id=token_uuid, model_name=request.model_name, is_active=True
        )
        db.add(new_model)
        await db.commit()

        logger.info(
            f"Model {request.model_name} added to token {token_uuid} by user {_current_user.id}"
        )

        return {
            "message": f"Model {request.model_name} added successfully",
            "id": str(new_model.id),
        }

    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid token_id format",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add model: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to add model: {str(e)}",
        )


@router.delete("/{model_id}")
async def delete_model(
    model_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user_from_jwt),
):
    """
    Delete (deactivate) a model from enabled list.
    """
    try:
        result = await db.execute(select(Model).where(Model.id == model_id))
        model = result.scalar_one_or_none()

        if not model:
            raise HTTPException(status_code=404, detail="Model not found")

        # Soft delete - mark as deleted and inactive
        model.is_deleted = True
        model.is_active = False
        model.deleted_at = datetime.utcnow()
        await db.commit()

        logger.info(f"Model {model.model_name} deleted by user {_current_user.id}")

        return {"message": f"Model {model.model_name} deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete model: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete model: {str(e)}",
        )

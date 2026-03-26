"""
Models management endpoints (OpenAI compatible).
"""

import logging
import time
from typing import List

import aioboto3
from botocore.config import Config
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_token_flexible, get_current_user_from_jwt
from app.core.config import get_settings
from app.core.database import get_db
from app.models.model import Model
from app.models.token import APIToken
from app.schemas.openai import ModelInfo, ModelListResponse

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()


async def _fetch_bedrock_models():
    """
    Helper function to fetch foundation models from AWS Bedrock.

    Returns:
        List of model summaries from Bedrock API
    """
    import os

    session_kwargs = {}
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        session_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
        session_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY

    if settings.AWS_PROFILE:
        os.environ["AWS_PROFILE"] = settings.AWS_PROFILE

    config = Config(
        region_name=settings.AWS_REGION,
        retries={"max_attempts": 3, "mode": "adaptive"},
    )

    session = aioboto3.Session(**session_kwargs)

    async with session.client(
        service_name="bedrock", region_name=settings.AWS_REGION, config=config
    ) as bedrock_client:
        response = await bedrock_client.list_foundation_models()
        return response.get("modelSummaries", [])


class BedrockModel(BaseModel):
    """Bedrock model information."""

    model_id: str
    model_name: str
    provider_name: str
    input_modalities: List[str]
    output_modalities: List[str]
    response_streaming_supported: bool
    customizations_supported: List[str]
    inference_types_supported: List[str]


class BedrockModelListResponse(BaseModel):
    """Response for Bedrock model list."""

    models: List[BedrockModel]


@router.get("/models")
async def list_models(
    token: APIToken = Depends(get_current_token_flexible),
    db: AsyncSession = Depends(get_db),
):
    """
    List models available to the current API token.

    Supports both OpenAI-style (Authorization: Bearer) and Anthropic-style
    (x-api-key) authentication. Returns models in OpenAI format.
    """
    try:
        # Query models associated with this token
        result = await db.execute(
            select(Model).where(
                Model.token_id == token.id,
                Model.is_active,
                ~Model.is_deleted,
            )
        )
        token_models = result.scalars().all()

        created = int(time.time())
        data = [
            ModelInfo(
                id=m.model_name,
                created=created,
                owned_by="bedrock",
            )
            for m in token_models
        ]

        return ModelListResponse(data=data)

    except Exception as e:
        logger.error(f"Failed to list models: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve models: {str(e)}",
        )


@router.get("/models/bedrock", response_model=BedrockModelListResponse)
async def list_bedrock_models(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_from_jwt),
):
    """
    Get list of available Bedrock models (requires JWT auth).

    This endpoint queries AWS Bedrock to get all foundation models
    available for the current AWS account/region.
    """
    try:
        model_summaries = await _fetch_bedrock_models()

        models = []
        for model_summary in model_summaries:
            if model_summary.get("providerName") == "Anthropic":
                models.append(
                    BedrockModel(
                        model_id=model_summary.get("modelId", ""),
                        model_name=model_summary.get("modelName", ""),
                        provider_name=model_summary.get("providerName", ""),
                        input_modalities=model_summary.get("inputModalities", []),
                        output_modalities=model_summary.get("outputModalities", []),
                        response_streaming_supported=model_summary.get(
                            "responseStreamingSupported", False
                        ),
                        customizations_supported=model_summary.get(
                            "customizationsSupported", []
                        ),
                        inference_types_supported=model_summary.get(
                            "inferenceTypesSupported", []
                        ),
                    )
                )

        logger.info(f"Retrieved {len(models)} Bedrock models")

        return BedrockModelListResponse(models=models)

    except Exception as e:
        logger.error(f"Failed to list Bedrock models: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve models from AWS Bedrock: {str(e)}",
        )


@router.get("/models/simple")
async def list_simple_models(
    current_user=Depends(get_current_user_from_jwt),
):
    """
    Get simplified list of Claude models for UI display (async with aioboto3).

    Returns a simplified list with friendly names and model IDs.
    """
    try:
        model_summaries = await _fetch_bedrock_models()

        models = []
        for model_summary in model_summaries:
            if model_summary.get("providerName") == "Anthropic":
                model_id = model_summary.get("modelId", "")
                model_name = model_summary.get("modelName", "")

                friendly_name = model_id.split(".")[-1].split("-2024")[0]

                models.append(
                    {
                        "id": model_id,
                        "name": friendly_name,
                        "full_name": model_name,
                        "provider": "bedrock-converse",
                        "streaming_supported": model_summary.get(
                            "responseStreamingSupported", False
                        ),
                    }
                )

        return {"models": models}

    except Exception as e:
        logger.error(f"Failed to list simple models: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve models: {str(e)}",
        )

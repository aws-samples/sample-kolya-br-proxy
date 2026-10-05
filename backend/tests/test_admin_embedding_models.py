# pyright: reportAttributeAccessIssue=false
"""Admins must be able to select the embedding models for API keys."""

from app.api.admin.endpoints.models import embedding_model_options
from app.services.embedding_models import SUPPORTED_EMBEDDING_MODELS


def test_both_embedding_models_are_selectable():
    options = embedding_model_options()

    assert {o["model_id"] for o in options} == SUPPORTED_EMBEDDING_MODELS
    # model_name is what gets stored in the key's allowlist; it must be the
    # exact model ID that /v1/embeddings authorizes against.
    assert all(o["model_name"] == o["model_id"] for o in options)
    assert all(o["provider"] == "bedrock-embedding" for o in options)

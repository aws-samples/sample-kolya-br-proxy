"""
AWS Bedrock API schemas for Claude models.
"""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class BedrockContentPart(BaseModel):
    """Content part in Bedrock format (text, image, tool_use, or tool_result)."""

    type: str  # "text", "image", "tool_use", "tool_result"
    text: Optional[str] = None
    source: Optional[Dict[str, Any]] = (
        None  # For images: {"type": "base64", "media_type": "...", "data": "..."}
    )
    # For tool_use type
    id: Optional[str] = None
    name: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    # For tool_result type
    tool_use_id: Optional[str] = None
    content: Optional[str] = None  # Tool result content as string


class BedrockMessage(BaseModel):
    """Message in Bedrock format."""

    role: str
    content: Union[
        str, List[BedrockContentPart]
    ]  # Support both string and array format


class BedrockTool(BaseModel):
    """Tool definition in Bedrock format."""

    name: str
    description: str
    input_schema: Dict[str, Any]


class BedrockRequest(BaseModel):
    """Bedrock API request for Claude models."""

    anthropic_version: str = "bedrock-2023-05-31"
    max_tokens: int = Field(default=4096, ge=1)
    messages: List[BedrockMessage]
    temperature: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    stop_sequences: Optional[List[str]] = None
    system: Optional[str] = None
    tools: Optional[List[BedrockTool]] = None
    tool_choice: Optional[Dict[str, Any]] = None
    # Advanced Bedrock parameters
    guardrail_config: Optional[Dict[str, Any]] = None
    additional_model_request_fields: Optional[Dict[str, Any]] = None
    trace: Optional[str] = None  # "ENABLED" or "DISABLED"
    performance_config: Optional[Dict[str, Any]] = None
    prompt_caching: Optional[Dict[str, Any]] = None
    prompt_variables: Optional[Dict[str, Any]] = None
    additional_model_response_field_paths: Optional[List[str]] = None
    request_metadata: Optional[Dict[str, str]] = None
    auto_cache: Optional[bool] = None
    cache_ttl: Optional[str] = None  # Per-request TTL override ("5m" or "1h")


class BedrockContentBlock(BaseModel):
    """Content block in Bedrock response."""

    type: str  # "text", "tool_use", "image"
    text: Optional[str] = None
    # For tool_use type
    id: Optional[str] = None
    name: Optional[str] = None
    input: Optional[Dict[str, Any]] = None


class BedrockUsage(BaseModel):
    """Usage information from Bedrock."""

    input_tokens: Optional[int] = 0
    output_tokens: Optional[int] = 0
    cache_creation_input_tokens: Optional[int] = 0
    cache_read_input_tokens: Optional[int] = 0


class BedrockResponse(BaseModel):
    """Bedrock API response."""

    id: str
    type: str
    role: str
    content: List[BedrockContentBlock]
    model: str
    stop_reason: Optional[str] = None
    stop_sequence: Optional[str] = None
    usage: BedrockUsage


class BedrockStreamEvent(BaseModel):
    """Bedrock streaming event."""

    type: str
    index: Optional[int] = None
    delta: Optional[Dict[str, Any]] = None
    content_block: Optional[BedrockContentBlock] = None
    message: Optional[Dict[str, Any]] = None
    usage: Optional[BedrockUsage] = None

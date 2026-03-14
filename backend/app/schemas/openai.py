"""
OpenAI API compatible request/response schemas.
"""

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class ContentPart(BaseModel):
    """Content part for multimodal messages."""

    type: Literal["text", "image_url"]
    text: Optional[str] = None
    image_url: Optional[Dict[str, str]] = None


class ToolCall(BaseModel):
    """Tool call in OpenAI format."""

    id: str
    type: Literal["function"] = "function"
    function: Dict[str, Any]  # {"name": "...", "arguments": "..."}


class ChatMessage(BaseModel):
    """Chat message in OpenAI format."""

    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[Union[str, List[ContentPart]]] = (
        None  # Support both string and array format
    )
    name: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None  # For tool role messages


class ChatCompletionRequest(BaseModel):
    """OpenAI chat completion request with Bedrock extension support."""

    model: str
    messages: List[ChatMessage]
    temperature: Optional[float] = Field(default=1.0, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=1.0, ge=0.0, le=1.0)
    n: Optional[int] = Field(default=1, ge=1)
    stream: Optional[bool] = False
    stop: Optional[Union[str, List[str]]] = None
    max_tokens: Optional[int] = Field(default=None, ge=1)
    presence_penalty: Optional[float] = Field(default=0.0, ge=-2.0, le=2.0)
    frequency_penalty: Optional[float] = Field(default=0.0, ge=-2.0, le=2.0)
    user: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    # Bedrock-specific extensions (bedrock_* prefix)
    bedrock_guardrail_config: Optional[Dict[str, Any]] = None
    bedrock_additional_model_request_fields: Optional[Dict[str, Any]] = None
    bedrock_trace: Optional[str] = None
    bedrock_performance_config: Optional[Dict[str, Any]] = None
    bedrock_prompt_caching: Optional[Dict[str, Any]] = None
    bedrock_prompt_variables: Optional[Dict[str, Any]] = None
    bedrock_additional_model_response_field_paths: Optional[List[str]] = None
    bedrock_request_metadata: Optional[Dict[str, str]] = None
    bedrock_auto_cache: Optional[bool] = None  # None = use server default


class ChatCompletionChoice(BaseModel):
    """Single completion choice."""

    index: int
    message: ChatMessage
    finish_reason: Optional[str] = None


class PromptTokensDetails(BaseModel):
    """Breakdown of prompt token usage (OpenAI compatible)."""

    cached_tokens: int = 0
    cache_creation_tokens: int = 0


class UsageInfo(BaseModel):
    """Token usage information."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_tokens_details: Optional[PromptTokensDetails] = None


class ChatCompletionResponse(BaseModel):
    """OpenAI chat completion response."""

    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    usage: UsageInfo


class ChatCompletionStreamChoice(BaseModel):
    """Streaming completion choice delta."""

    index: int
    delta: Dict[str, Any]
    finish_reason: Optional[str] = None


class ChatCompletionStreamResponse(BaseModel):
    """OpenAI streaming response chunk."""

    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: List[ChatCompletionStreamChoice]
    usage: Optional[UsageInfo] = None


class ModelInfo(BaseModel):
    """Model information."""

    id: str
    object: Literal["model"] = "model"
    created: int
    owned_by: str


class ModelListResponse(BaseModel):
    """List of available models."""

    object: Literal["list"] = "list"
    data: List[ModelInfo]


class ErrorDetail(BaseModel):
    """Error detail in OpenAI format."""

    message: str
    type: str
    param: Optional[str] = None
    code: Optional[str] = None


class ErrorResponse(BaseModel):
    """OpenAI error response."""

    error: ErrorDetail

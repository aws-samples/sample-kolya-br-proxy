"""
Anthropic Messages API compatible request/response schemas.
"""

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator


# --- Request schemas ---


def _extract_text(content: Any) -> str:
    """Flatten Anthropic content (str or list of text blocks) into plain text.

    Used to hoist ``system`` messages — which may carry either a bare string or
    a list of ``{"type": "text", "text": ...}`` blocks — into the top-level
    ``system`` field. Non-text blocks are ignored.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: List[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type", "text") == "text" and block.get("text"):
                    texts.append(block["text"])
            elif isinstance(block, str):
                texts.append(block)
            else:
                text = getattr(block, "text", None)
                if text:
                    texts.append(text)
        return "\n".join(texts)
    return str(content)


class AnthropicTextContent(BaseModel):
    """Text content block."""

    type: Literal["text"] = "text"
    text: str
    cache_control: Optional[Dict[str, str]] = None


class AnthropicImageSource(BaseModel):
    """Image source for Anthropic format."""

    type: Literal["base64", "url"] = "base64"
    media_type: Optional[str] = None
    data: Optional[str] = None
    url: Optional[str] = None


class AnthropicImageContent(BaseModel):
    """Image content block."""

    type: Literal["image"] = "image"
    source: AnthropicImageSource
    cache_control: Optional[Dict[str, str]] = None


class AnthropicToolUseContent(BaseModel):
    """Tool use content block (in assistant messages)."""

    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: Dict[str, Any]


class AnthropicToolResultContent(BaseModel):
    """Tool result content block (in user messages)."""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: Optional[Union[str, List[Dict[str, Any]]]] = None
    is_error: Optional[bool] = None
    cache_control: Optional[Dict[str, str]] = None


class AnthropicThinkingContent(BaseModel):
    """Thinking content block."""

    type: Literal["thinking"] = "thinking"
    thinking: str = ""
    signature: Optional[str] = None


class AnthropicRedactedThinkingContent(BaseModel):
    """Redacted thinking content block."""

    type: Literal["redacted_thinking"] = "redacted_thinking"
    data: str


# Union of all content block types
AnthropicContentBlock = Union[
    AnthropicTextContent,
    AnthropicImageContent,
    AnthropicToolUseContent,
    AnthropicToolResultContent,
    AnthropicThinkingContent,
    AnthropicRedactedThinkingContent,
    Dict[str, Any],  # Fallback for unknown types
]


class AnthropicMessage(BaseModel):
    """Message in Anthropic format.

    The Anthropic spec only allows ``user``/``assistant`` here, but some clients
    (notably Claude Code) inject a ``system`` message into the ``messages`` array
    instead of the top-level ``system`` field. ``role`` accepts ``system`` so
    those requests parse; ``AnthropicMessagesRequest`` then hoists any such
    messages into the top-level ``system`` field before validation completes, so
    downstream code never sees a ``system`` role in ``messages``.
    """

    role: Literal["user", "assistant", "system"]
    content: Union[str, List[AnthropicContentBlock]]


class AnthropicToolDefinition(BaseModel):
    """Tool definition in Anthropic format."""

    name: str
    description: Optional[str] = None
    input_schema: Dict[str, Any]
    cache_control: Optional[Dict[str, str]] = None
    strict: Optional[bool] = None


class AnthropicSystemBlock(BaseModel):
    """System content block."""

    type: Literal["text"] = "text"
    text: str
    cache_control: Optional[Dict[str, str]] = None


class AnthropicThinkingConfig(BaseModel):
    """Thinking configuration."""

    type: Literal["enabled", "disabled", "adaptive"] = "enabled"
    budget_tokens: Optional[int] = None


class AnthropicMessagesRequest(BaseModel):
    """Anthropic Messages API request."""

    model: str
    messages: List[AnthropicMessage]
    max_tokens: int = Field(ge=1)
    system: Optional[Union[str, List[AnthropicSystemBlock]]] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    top_k: Optional[int] = Field(default=None, ge=0)
    stop_sequences: Optional[List[str]] = None
    stream: Optional[bool] = False
    tools: Optional[List[AnthropicToolDefinition]] = None
    tool_choice: Optional[Dict[str, Any]] = None
    disable_parallel_tool_use: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None
    thinking: Optional[AnthropicThinkingConfig] = None

    @model_validator(mode="before")
    @classmethod
    def _hoist_system_messages(cls, data: Any) -> Any:
        """Move any ``system`` role messages into the top-level ``system`` field.

        Some clients (e.g. Claude Code) put a ``system`` message inside the
        ``messages`` array rather than the top-level ``system`` field, which the
        Anthropic spec disallows. To stay compatible, pull those out, prepend
        their text to ``system``, and leave ``messages`` with only
        ``user``/``assistant`` entries — transparent to all downstream logic.
        """
        if not isinstance(data, dict):
            return data
        messages = data.get("messages")
        if not isinstance(messages, list):
            return data

        system_texts: List[str] = []
        kept: List[Any] = []
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "system":
                system_texts.append(_extract_text(msg.get("content")))
            else:
                kept.append(msg)
        if not system_texts:
            return data

        # Prepend hoisted system text to any existing top-level system content.
        existing = data.get("system")
        parts = [t for t in system_texts if t]
        if existing:
            parts.append(_extract_text(existing))
        data["system"] = "\n\n".join(p for p in parts if p)
        data["messages"] = kept
        return data


# --- Response schemas ---


class AnthropicUsage(BaseModel):
    """Usage information in Anthropic format."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: Optional[int] = None
    cache_read_input_tokens: Optional[int] = None


class AnthropicResponseTextContent(BaseModel):
    """Text content block in response."""

    type: Literal["text"] = "text"
    text: str


class AnthropicResponseToolUseContent(BaseModel):
    """Tool use content block in response."""

    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: Dict[str, Any]


class AnthropicResponseThinkingContent(BaseModel):
    """Thinking content block in response."""

    type: Literal["thinking"] = "thinking"
    thinking: str
    signature: Optional[str] = None


class AnthropicResponseRedactedThinkingContent(BaseModel):
    """Redacted thinking content block in response."""

    type: Literal["redacted_thinking"] = "redacted_thinking"
    data: str


AnthropicResponseContentBlock = Union[
    AnthropicResponseTextContent,
    AnthropicResponseToolUseContent,
    AnthropicResponseThinkingContent,
    AnthropicResponseRedactedThinkingContent,
]


class AnthropicMessagesResponse(BaseModel):
    """Anthropic Messages API response."""

    id: str
    type: Literal["message"] = "message"
    role: Literal["assistant"] = "assistant"
    content: List[AnthropicResponseContentBlock]
    model: str
    stop_reason: Optional[str] = None
    stop_sequence: Optional[str] = None
    usage: AnthropicUsage


# --- Streaming event schemas ---


class AnthropicStreamMessageStart(BaseModel):
    """message_start streaming event."""

    type: Literal["message_start"] = "message_start"
    message: AnthropicMessagesResponse


class AnthropicStreamContentBlockStart(BaseModel):
    """content_block_start streaming event."""

    type: Literal["content_block_start"] = "content_block_start"
    index: int
    content_block: Dict[str, Any]


class AnthropicStreamContentBlockDelta(BaseModel):
    """content_block_delta streaming event."""

    type: Literal["content_block_delta"] = "content_block_delta"
    index: int
    delta: Dict[str, Any]


class AnthropicStreamContentBlockStop(BaseModel):
    """content_block_stop streaming event."""

    type: Literal["content_block_stop"] = "content_block_stop"
    index: int


class AnthropicStreamMessageDelta(BaseModel):
    """message_delta streaming event."""

    type: Literal["message_delta"] = "message_delta"
    delta: Dict[str, Any]
    usage: Optional[AnthropicUsage] = None


class AnthropicStreamMessageStop(BaseModel):
    """message_stop streaming event."""

    type: Literal["message_stop"] = "message_stop"


class AnthropicStreamPing(BaseModel):
    """ping streaming event."""

    type: Literal["ping"] = "ping"


# --- Error schemas ---


class AnthropicErrorDetail(BaseModel):
    """Anthropic error detail."""

    type: str
    message: str


class AnthropicErrorResponse(BaseModel):
    """Anthropic error response."""

    type: Literal["error"] = "error"
    error: AnthropicErrorDetail

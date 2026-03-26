# Request Translation Pipeline

How Kolya BR Proxy translates requests into AWS Bedrock API calls, and converts responses back. The proxy supports two client-facing API formats:

- **OpenAI-compatible** (`POST /v1/chat/completions`) -- requires format translation
- **Anthropic Messages API** (`POST /v1/messages`) -- near-passthrough to Bedrock InvokeModel

Anthropic models use the InvokeModel API (native Messages API format), while non-Anthropic models (Nova, DeepSeek, Mistral, Llama, etc.) use the Converse API.

---

## Table of Contents

1. [Full Data Flow](#1-full-data-flow)
2. [Phase 1: OpenAI → BedrockRequest](#2-phase-1-openai--bedrockrequest)
3. [Phase 2: BedrockRequest → Anthropic Messages API Body](#3-phase-2-bedrockrequest--anthropic-messages-api-body)
4. [Phase 2b: BedrockRequest → Converse API (Non-Anthropic Models)](#4-phase-2b-bedrockrequest--converse-api-non-anthropic-models)
5. [Phase 3: Response → BedrockResponse → OpenAI](#5-phase-3-response--bedrockresponse--openai)
6. [Streaming Event Translation](#6-streaming-event-translation)
7. [Anthropic Messages API Path (Near-Passthrough)](#7-anthropic-messages-api-path-near-passthrough)
8. [Bedrock Extension Pass-through](#8-bedrock-extension-pass-through)
9. [Effort Parameter Auto-transform](#9-effort-parameter-auto-transform)
10. [Automatic Fixes](#10-automatic-fixes)
11. [Unsupported Parameters](#11-unsupported-parameters)

---

## 1. Full Data Flow

```mermaid
sequenceDiagram
    participant Client as OpenAI Client
    participant Chat as chat.py
    participant RT as RequestTranslator
    participant BC as BedrockClient
    participant AWS as AWS Bedrock
    participant ResT as ResponseTranslator

    Client->>Chat: POST /v1/chat/completions<br/>(OpenAI format)
    Chat->>Chat: Extract X-Bedrock-* headers
    Chat->>RT: openai_to_bedrock(request)
    RT-->>Chat: BedrockRequest

    Chat->>BC: invoke(model, bedrock_request)
    alt Anthropic model
        BC->>BC: _build_anthropic_body(request)
        BC->>AWS: invoke_model(body=JSON, modelId=...)
        AWS-->>BC: Anthropic Messages API JSON
    else Non-Anthropic model
        BC->>BC: _build_converse_params(request)
        BC->>AWS: converse(params)
        AWS-->>BC: Converse API JSON
    end
    BC->>BC: Parse → BedrockResponse
    BC-->>Chat: BedrockResponse

    Chat->>ResT: bedrock_to_openai(response)
    ResT-->>Chat: ChatCompletionResponse
    Chat-->>Client: OpenAI JSON response
```

---

## 2. Phase 1: OpenAI → BedrockRequest

**File**: `backend/app/services/translator.py` — `RequestTranslator.openai_to_bedrock()`

### 2.1 Message Conversion

| OpenAI Message | BedrockMessage | Notes |
|---|---|---|
| `role: "system"` | Extracted to `BedrockRequest.system` (top-level string) | Only the last system message is used |
| `role: "user"` (string content) | `role: "user", content: "..."` | Direct pass-through |
| `role: "user"` (array content) | `role: "user", content: [BedrockContentPart...]` | Multimodal: text + images |
| `role: "assistant"` (plain text) | `role: "assistant", content: "..."` | Direct pass-through |
| `role: "assistant"` (with `tool_calls`) | `role: "assistant", content: [tool_use blocks]` | Converted to `BedrockContentPart(type="tool_use")` |
| `role: "tool"` | `role: "user", content: [tool_result blocks]` | Multiple consecutive tool messages merged into one user message |

### 2.2 Image Handling

```
OpenAI: {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
                                    ↓
Bedrock: {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}}
```

URL-based images are fetched, base64-encoded, and converted to the Bedrock inline format.

### 2.3 Tool Call Conversion

```
OpenAI tool_calls:                          Bedrock content parts:
┌─────────────────────────┐                ┌───────────────────────────┐
│ id: "call_abc"          │                │ type: "tool_use"          │
│ type: "function"        │  ──────────▶   │ id: "call_abc"            │
│ function:               │                │ name: "get_weather"       │
│   name: "get_weather"   │                │ input: {"city": "London"} │
│   arguments: "{...}"    │                └───────────────────────────┘
└─────────────────────────┘
```

```
OpenAI tool message:                        Bedrock content part:
┌─────────────────────────┐                ┌─────────────────────────────┐
│ role: "tool"            │                │ type: "tool_result"         │
│ tool_call_id: "call_abc"│  ──────────▶   │ tool_use_id: "call_abc"     │
│ content: "Sunny, 22°C"  │                │ content: "Sunny, 22°C"      │
└─────────────────────────┘                └─────────────────────────────┘
```

### 2.4 Scalar Parameter Mapping

| OpenAI | BedrockRequest | Behavior |
|---|---|---|
| `temperature` | `temperature` | Direct mapping (0.0 - 1.0) |
| `top_p` | `top_p` | **Only if `temperature` is not set** (mutually exclusive on Bedrock) |
| `max_tokens` | `max_tokens` | Default 4096 if not set |
| `stop` (string or array) | `stop_sequences` (array) | String wrapped in array |
| `tools` | `tools` | `parameters` → `input_schema` |
| `tool_choice: "auto"` | `{"type": "auto"}` | |
| `tool_choice: "required"` | `{"type": "any"}` | OpenAI "required" = Anthropic "any" |
| `tool_choice: "none"` | `{"type": "none"}` | |
| `tool_choice: {function: {name}}` | `{"type": "tool", "name": ...}` | |
| `n` | Ignored | Warning logged if n ≠ 1 |
| `presence_penalty` | Ignored | Warning logged if ≠ 0 |
| `frequency_penalty` | Ignored | Warning logged if ≠ 0 |

### 2.5 Bedrock Extension Fields (Pass-through)

These fields from the OpenAI request body are passed directly to `BedrockRequest`:

| OpenAI Request Field | BedrockRequest Field |
|---|---|
| `bedrock_guardrail_config` | `guardrail_config` |
| `bedrock_additional_model_request_fields` | `additional_model_request_fields` |
| `bedrock_trace` | `trace` |
| `bedrock_performance_config` | `performance_config` |
| `bedrock_prompt_caching` | `prompt_caching` |
| `bedrock_prompt_variables` | `prompt_variables` |
| `bedrock_additional_model_response_field_paths` | `additional_model_response_field_paths` |
| `bedrock_request_metadata` | `request_metadata` |

These can also be set via `X-Bedrock-*` HTTP headers (headers override body):

| Header | Maps to |
|---|---|
| `X-Bedrock-Guardrail-Id` + `X-Bedrock-Guardrail-Version` | `bedrock_guardrail_config` |
| `X-Bedrock-Additional-Fields` (JSON) | `bedrock_additional_model_request_fields` |
| `X-Bedrock-Trace` | `bedrock_trace` |
| `X-Bedrock-Performance-Config` (JSON) | `bedrock_performance_config` |
| `X-Bedrock-Prompt-Caching` (JSON) | `bedrock_prompt_caching` |

---

## 3. Phase 2: BedrockRequest → Anthropic Messages API Body

**File**: `backend/app/services/bedrock.py` — `_build_anthropic_body()` + `_build_invoke_kwargs()`

This phase converts the internal `BedrockRequest` into the exact JSON body that Bedrock's `invoke_model` API expects (Anthropic Messages API format).

### 3.1 Body Construction

```python
# Final JSON body sent to invoke_model:
{
    "anthropic_version": "bedrock-2023-05-31",
    "max_tokens": 4096,
    "messages": [...],          # BedrockContentPart.model_dump(exclude_none=True)

    # Optional — included only if set:
    "system": "You are...",
    "temperature": 0.7,
    "top_p": 0.9,
    "stop_sequences": ["END"],
    "tools": [...],
    "tool_choice": {"type": "auto"},

    # From additional_model_request_fields (merged via body.update()):
    "thinking": {"type": "enabled", "budget_tokens": 5000},

    # Auto-transformed from "effort" (see Section 8):
    "anthropic_beta": ["effort-2025-11-24"],
    "output_config": {"effort": "medium"},

    # From prompt_caching (merged via body.update()):
    "prompt_caching": {...}
}
```

### 3.2 invoke_model Top-level Parameters

```python
# Keyword arguments for invoke_model() (everything except body):
{
    "modelId": "global.anthropic.claude-opus-4-6-v1",
    "contentType": "application/json",
    "accept": "application/json",

    # Optional — from guardrail_config:
    "guardrailIdentifier": "abc123",
    "guardrailVersion": "1",

    # Optional:
    "trace": "ENABLED",
    "performanceConfig": {...}
}
```

### 3.3 Why InvokeModel for Anthropic

The Converse API uses AWS-specific formats (camelCase fields, nested `inferenceConfig`). With `invoke_model`, the body is **native Anthropic Messages API format** — no field renaming needed. This enables direct pass-through of Anthropic-native parameters like `thinking` and `effort`.

| Aspect | Converse API | InvokeModel API |
|---|---|---|
| Body format | AWS-specific (camelCase) | Anthropic Messages API (snake_case) |
| `thinking` support | Via `additionalModelRequestFields` (limited) | Direct body field |
| `effort` support | Not supported | Supported via `output_config` + beta flag |
| Response format | `inputTokens`, `stopReason` | `input_tokens`, `stop_reason` |
| Tool use | `toolUse` / `toolResult` (camelCase) | `tool_use` / `tool_result` (snake_case) |
| Stream events | `contentBlockStart`, `contentBlockDelta` | `content_block_start`, `content_block_delta` |

---

## 4. Phase 2b: BedrockRequest → Converse API (Non-Anthropic Models)

**File**: `backend/app/services/bedrock.py` — `_build_converse_params()`

Non-Anthropic models (Amazon Nova, DeepSeek, Mistral, Llama, etc.) use the Bedrock Converse API, which is model-agnostic and handles format conversion automatically. The `BedrockClient.is_anthropic_model()` method detects the model type based on the `anthropic.` prefix (with optional geo-prefix like `us.`, `eu.`, etc.).

### 4.1 Converse API Parameter Mapping

```python
# Parameters sent to converse() / converse_stream():
{
    "modelId": "us.amazon.nova-pro-v1:0",
    "messages": [
        {"role": "user", "content": [{"text": "Hello!"}]}
    ],

    # Optional:
    "system": [{"text": "You are..."}],
    "inferenceConfig": {
        "maxTokens": 4096,
        "temperature": 0.7,
        "topP": 0.9,
        "stopSequences": ["END"]
    },
    "toolConfig": {
        "tools": [{"toolSpec": {"name": "...", "description": "...", "inputSchema": {"json": {...}}}}],
        "toolChoice": {"auto": {}}
    },

    # Optional — from guardrail_config:
    "guardrailConfig": {"guardrailIdentifier": "abc123", "guardrailVersion": "1"},

    # Optional — from additional_model_request_fields:
    "additionalModelRequestFields": {...},

    # Optional — from performance_config:
    "performanceConfig": {...}
}
```

### 4.2 Content Block Format Differences

| Content Type | Anthropic (InvokeModel) | Converse API |
|---|---|---|
| Text | `{"type": "text", "text": "..."}` | `{"text": "..."}` |
| Image | `{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}}` | `{"image": {"format": "png", "source": {"bytes": <raw_bytes>}}}` |
| Tool use | `{"type": "tool_use", "id": "...", "name": "...", "input": {...}}` | `{"toolUse": {"toolUseId": "...", "name": "...", "input": {...}}}` |
| Tool result | `{"type": "tool_result", "tool_use_id": "...", "content": "..."}` | `{"toolResult": {"toolUseId": "...", "content": [{"text": "..."}]}}` |

### 4.3 Converse API Response Mapping

```
Converse API response                     BedrockResponse
──────────────────────                    ───────────────
{                                         BedrockResponse(
  "output": {                               id=<RequestId>,
    "message": {                            content=[
      "content": [                            BedrockContentBlock(type="text", text="Hi"),
        {"text": "Hi"},                       BedrockContentBlock(type="tool_use", ...),
        {"toolUse": {"toolUseId":...}}      ],
      ]                                     stop_reason="end_turn",
    }                                       usage=BedrockUsage(
  },                                          input_tokens=100,
  "stopReason": "end_turn",                   output_tokens=50
  "usage": {                                )
    "inputTokens": 100,                   )
    "outputTokens": 50
  }
}
```

---

## 5. Phase 3: Response → BedrockResponse → OpenAI

### 5.1 Non-streaming Response Parsing

**File**: `bedrock.py` — `_invoke_inner()`

```
Anthropic JSON response                   BedrockResponse
───────────────────────                   ───────────────
{                                         BedrockResponse(
  "id": "msg_...",                          id="msg_...",
  "content": [                              content=[
    {"type": "text", "text": "Hi"}            BedrockContentBlock(type="text", text="Hi"),
    {"type": "tool_use", "id": "...",         BedrockContentBlock(type="tool_use", ...),
     "name": "...", "input": {...}}           BedrockContentBlock(type="thinking"),
    {"type": "thinking", "thinking": "..."}
  ],                                        ],
  "stop_reason": "end_turn",                stop_reason="end_turn",
  "usage": {                                usage=BedrockUsage(
    "input_tokens": 100,                      input_tokens=100,
    "output_tokens": 50                       output_tokens=50
  }                                         )
}                                         )
```

### 5.2 BedrockResponse → OpenAI ChatCompletionResponse

**File**: `translator.py` — `ResponseTranslator.bedrock_to_openai()`

| Bedrock | OpenAI | Notes |
|---|---|---|
| `content[type="text"]` | `choices[0].message.content` | Concatenated if multiple text blocks |
| `content[type="tool_use"]` | `choices[0].message.tool_calls[]` | `input` → JSON string `arguments` |
| `content[type="thinking"]` | Skipped | Not part of OpenAI format |
| `stop_reason="end_turn"` | `finish_reason="stop"` | |
| `stop_reason="tool_use"` | `finish_reason="tool_calls"` | |
| `stop_reason="max_tokens"` | `finish_reason="length"` | |
| `usage.input_tokens` | `usage.prompt_tokens` | |
| `usage.output_tokens` | `usage.completion_tokens` | |

---

## 6. Streaming Event Translation

### 6.1 Anthropic SSE → BedrockStreamEvent (Anthropic Models)

**File**: `bedrock.py` — `_anthropic_event_to_bedrock()`

The `invoke_model_with_response_stream` API returns a byte stream. Each chunk is decoded as JSON and mapped:

| Anthropic Event | BedrockStreamEvent.type | Key Data |
|---|---|---|
| `message_start` | `message_start` | `usage.input_tokens` (from `message.usage`) |
| `content_block_start` | `content_block_start` | `content_block.type`: `text` / `tool_use` / `thinking` |
| `content_block_delta` (delta.type=`text_delta`) | `content_block_delta` | `delta.text` |
| `content_block_delta` (delta.type=`input_json_delta`) | `content_block_delta` | `delta.partial_json` |
| `content_block_delta` (delta.type=`thinking_delta`) | `content_block_delta` | `delta.thinking` |
| `content_block_stop` | `content_block_stop` | `index` |
| `message_delta` | `message_delta` | `usage.output_tokens`, `delta.stop_reason` |
| `message_stop` | `message_stop` | — |
| `ping` | Skipped | — |

### 6.2 Converse Stream Events → BedrockStreamEvent (Non-Anthropic Models)

**File**: `bedrock.py` — `_converse_stream_event_to_bedrock()`

The `converse_stream` API returns events as dicts with one key per event:

| Converse Event | BedrockStreamEvent.type | Key Data |
|---|---|---|
| `messageStart` | `message_start` | `role` |
| `contentBlockStart` (text) | `content_block_start` | `content_block.type: "text"` |
| `contentBlockStart` (toolUse) | `content_block_start` | `content_block: {type: "tool_use", id, name}` |
| `contentBlockDelta` (text) | `content_block_delta` | `delta.text` |
| `contentBlockDelta` (toolUse) | `content_block_delta` | `delta.partial_json` |
| `contentBlockStop` | `content_block_stop` | `index` |
| `messageStop` | `message_delta` | `delta.stop_reason` |
| `metadata` | `message_delta` | `usage.input_tokens`, `usage.output_tokens` |

### 6.3 BedrockStreamEvent → OpenAI SSE Chunks

**File**: `chat.py` — `stream_chat_completion()`

| BedrockStreamEvent | OpenAI SSE Output | Notes |
|---|---|---|
| `message_start` | (no output) | Captures `input_tokens` for usage tracking |
| `content_block_start` (text) | (no output) | — |
| `content_block_start` (tool_use) | `{"delta": {"tool_calls": [...]}}` | Sends tool call ID + name |
| `content_block_start` (thinking) | Skipped entirely | Thinking blocks filtered out |
| `content_block_delta` (text) | `{"delta": {"content": "..."}}` | Text streaming |
| `content_block_delta` (partial_json) | `{"delta": {"tool_calls": [...]}}` | Tool args streaming |
| `content_block_delta` (thinking) | Skipped entirely | — |
| `message_delta` | (no output) | Captures `output_tokens` |
| `message_stop` | `{"finish_reason": "stop"}` or `"tool_calls"` | Final chunk |
| — | `data: [DONE]\n\n` | Stream terminator |

### 6.4 Token Counting in Streaming

```
message_start  ──▶  input_tokens   (captured at stream start)
message_delta  ──▶  output_tokens  (captured near stream end)
                         │
                         ▼
              record_usage(prompt_tokens, completion_tokens)
```

---

## 7. Anthropic Messages API Path (Near-Passthrough)

**Files**: `backend/app/api/anthropic/endpoints/messages.py`, `backend/app/services/anthropic_translator.py`

When clients use the Anthropic Messages API (`POST /v1/messages` with `x-api-key` header), the translation is minimal because Bedrock's InvokeModel API for Anthropic models natively uses the Messages API format.

### 7.1 Data Flow

```mermaid
sequenceDiagram
    participant Client as Anthropic Client
    participant Msg as messages.py
    participant AT as AnthropicTranslator
    participant BC as BedrockClient
    participant AWS as AWS Bedrock

    Client->>Msg: POST /v1/messages<br/>(x-api-key: kbr_xxx)
    Msg->>AT: to_bedrock(request)
    AT-->>Msg: BedrockRequest (near 1:1)

    Msg->>BC: invoke(model, bedrock_request)
    BC->>BC: _build_anthropic_body(request)
    BC->>AWS: invoke_model(body=JSON)
    AWS-->>BC: Anthropic Messages API JSON
    BC-->>Msg: BedrockResponse

    Msg->>AT: bedrock_to_anthropic(response)
    AT-->>Msg: AnthropicMessagesResponse
    Msg-->>Client: Anthropic JSON response
```

### 7.2 Key Differences from OpenAI Path

| Aspect | OpenAI Path | Anthropic Path |
|--------|------------|----------------|
| Auth | `Authorization: Bearer` | `x-api-key` header |
| Request translation | Complex (role mapping, tool format conversion) | Near-passthrough (same format as Bedrock) |
| `thinking` blocks | Skipped in response | Preserved in response |
| `stop_reason` | Mapped to `finish_reason` (`end_turn` → `stop`) | Passed through as-is |
| Streaming format | `data: {json}\n\n` + `data: [DONE]\n\n` | `event: type\ndata: {json}\n\n` |
| Error format | `{"error": {"message": "...", "type": "..."}}` | `{"type": "error", "error": {"type": "...", "message": "..."}}` |
| `cache_control` | Via `bedrock_auto_cache` or `X-Bedrock-Auto-Cache` | Native support (passed through directly) |

### 7.3 Thinking Block Stripping in Conversation History

When using the Anthropic Messages API path with extended thinking enabled, the proxy automatically strips `thinking` and `redacted_thinking` content blocks from conversation history messages before sending to Bedrock.

**Why this is necessary:**
- Bedrock's InvokeModel API doesn't support adaptive thinking mode's signature-only thinking blocks (blocks with just `type: "thinking"` but no content)
- The model generates fresh thinking on each turn based on the current context
- Historical thinking blocks from previous turns are not needed and would cause validation errors

**What gets stripped:**
```json
// Original message in conversation history
{
  "role": "assistant",
  "content": [
    {"type": "thinking", "thinking": "Previous reasoning..."},
    {"type": "text", "text": "Here's my response"}
  ]
}

// After stripping (sent to Bedrock)
{
  "role": "assistant",
  "content": [
    {"type": "text", "text": "Here's my response"}
  ]
}
```

This stripping only applies to historical messages in the `messages` array. Current turn thinking (generated by Bedrock) is preserved in responses.

### 7.4 Adaptive Thinking Mode

The `thinking.type` parameter supports three values:

| Value | Behavior |
|-------|----------|
| `"enabled"` | Extended thinking is always used (requires `budget_tokens`) |
| `"disabled"` | No extended thinking |
| `"adaptive"` | Model decides whether to use extended thinking based on query complexity |

Example request with adaptive thinking:

```json
{
  "model": "claude-opus-4",
  "max_tokens": 4096,
  "messages": [...],
  "thinking": {
    "type": "adaptive",
    "budget_tokens": 10000
  }
}
```

In adaptive mode, the model automatically engages extended thinking for complex queries while responding directly for simpler ones. The `budget_tokens` sets the maximum allowed for thinking when the model chooses to use it.

### 7.5 Streaming Event Mapping

The Anthropic path converts `BedrockStreamEvent` back to Anthropic SSE format, which is essentially the inverse of `_anthropic_event_to_bedrock()`:

| BedrockStreamEvent | Anthropic SSE Event | Key Differences from OpenAI |
|---|---|---|
| `message_start` | `event: message_start` | Full message object (not just usage) |
| `content_block_start` | `event: content_block_start` | Includes thinking blocks |
| `content_block_delta` (text) | `event: content_block_delta` (text_delta) | Native delta format |
| `content_block_delta` (partial_json) | `event: content_block_delta` (input_json_delta) | Native format |
| `content_block_delta` (thinking) | `event: content_block_delta` (thinking_delta) | **Preserved** (OpenAI skips) |
| `content_block_stop` | `event: content_block_stop` | Direct mapping |
| `message_delta` | `event: message_delta` | `stop_reason` preserved (no mapping) |
| `message_stop` | `event: message_stop` | No `[DONE]` marker |

---

## 8. Bedrock Extension Pass-through

The full lifecycle of a `bedrock_additional_model_request_fields` value:

```
Client request body:
{
  "bedrock_additional_model_request_fields": {
    "thinking": {"type": "enabled", "budget_tokens": 5000}
  }
}

    │  (or via header: X-Bedrock-Additional-Fields: {"thinking": ...})
    ▼

chat.py: header extraction → sets request_data.bedrock_additional_model_request_fields
    │
    ▼

translator.py: openai_to_bedrock()
    → BedrockRequest.additional_model_request_fields = {"thinking": {...}}
    │
    ▼

bedrock.py: _build_anthropic_body()
    → body.update(request.additional_model_request_fields)
    → body now contains: {"thinking": {"type": "enabled", "budget_tokens": 5000}, ...}
    │
    ▼

invoke_model(body=json.dumps(body))
    → Anthropic Messages API receives "thinking" as a native field
```

---

## 9. Effort Parameter Auto-transform (Anthropic Models Only)

Anthropic's `effort` parameter requires special handling on Bedrock:

1. Must be nested inside `output_config` (not top-level)
2. Requires `anthropic_beta: ["effort-2025-11-24"]` flag

The proxy auto-transforms this. Users can send:

```json
{
  "bedrock_additional_model_request_fields": {
    "thinking": {"type": "enabled", "budget_tokens": 5000},
    "effort": "medium"
  }
}
```

The `_build_anthropic_body()` method in `bedrock.py` transforms it to:

```json
{
  "thinking": {"type": "enabled", "budget_tokens": 5000},
  "anthropic_beta": ["effort-2025-11-24"],
  "output_config": {"effort": "medium"}
}
```

**Transformation steps:**

```
1. body.update(additional_model_request_fields)
   → body = {..., "effort": "medium", "thinking": {...}}

2. Detect "effort" in body
   → Pop "effort" value
   → Wrap in output_config: {"effort": "medium"}
   → Add beta flag: ["effort-2025-11-24"]

3. Final body sent to invoke_model:
   → "effort" is gone from top-level
   → "output_config": {"effort": "medium"} is present
   → "anthropic_beta": ["effort-2025-11-24"] is present
```

---

## 10. Automatic Fixes

### 9.1 max_tokens vs budget_tokens

Anthropic requires `max_tokens > thinking.budget_tokens`. If a request has `max_tokens=2000` and `budget_tokens=2000`, the proxy auto-adjusts:

```
Before: max_tokens=2000, budget_tokens=2000  (invalid: max_tokens must be > budget_tokens)
After:  max_tokens=4000, budget_tokens=2000  (auto-fixed: max_tokens = budget + original max)
```

### 9.2 temperature / top_p Mutual Exclusion

Anthropic doesn't allow both `temperature` and `top_p` in the same request. The translator enforces:

```
If temperature is set → top_p is omitted
If temperature is not set → top_p is passed through
```

---

## 11. Unsupported Parameters

These OpenAI/Bedrock parameters are **warned and ignored** when using `invoke_model` (Anthropic models):

| Parameter | Reason |
|---|---|
| `n` (if ≠ 1) | Bedrock only supports single completion |
| `presence_penalty` | Not supported by Anthropic |
| `frequency_penalty` | Not supported by Anthropic |
| `prompt_variables` | Only supported by Converse API |
| `request_metadata` | Only supported by Converse API |
| `additional_model_response_field_paths` | Only supported by Converse API |

---

## File Reference

| File | Role in Translation |
|---|---|
| `api/v1/endpoints/chat.py` | OpenAI entry point; extracts `X-Bedrock-*` headers; orchestrates stream/non-stream flow |
| `api/anthropic/endpoints/messages.py` | Anthropic entry point; `x-api-key` auth; Anthropic SSE streaming |
| `services/translator.py` | `RequestTranslator`: OpenAI → BedrockRequest; `ResponseTranslator`: BedrockResponse → OpenAI |
| `services/anthropic_translator.py` | `AnthropicRequestTranslator`: Anthropic → BedrockRequest; `AnthropicResponseTranslator`: BedrockResponse → Anthropic |
| `services/bedrock.py` | `_build_anthropic_body()`: BedrockRequest → Anthropic JSON (Anthropic models); `_build_converse_params()`: BedrockRequest → Converse API params (non-Anthropic); `_anthropic_event_to_bedrock()` / `_converse_stream_event_to_bedrock()`: stream event mapping |
| `schemas/openai.py` | OpenAI request/response Pydantic models |
| `schemas/anthropic.py` | Anthropic Messages API request/response/streaming Pydantic models |
| `schemas/bedrock.py` | Internal Bedrock Pydantic models (BedrockRequest, BedrockResponse, BedrockStreamEvent) |

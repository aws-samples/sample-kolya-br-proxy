# Fixing 403 Errors and Exploring Claude Code Internals

## Background

When using `ANTHROPIC_API_KEY` + `ANTHROPIC_BASE_URL` pointing to kolya-br-proxy, Claude Code occasionally returned 403 Forbidden, while the main request (Opus) returned 200 normally.

---

## Troubleshooting Process

### Step 1: Two Requests Per Turn

Logs showed two `POST /v1/messages` requests per conversation turn, with different source ports (normal TCP ephemeral port behavior):

```
POST /v1/messages?beta=true  →  200 OK        (model=global.anthropic.claude-opus-4-6-v1)
POST /v1/messages?beta=true  →  403 Forbidden  (model=claude-haiku-4-5-20251001)
```

The user never explicitly sent a Haiku request.

### Step 2: Identifying the Sender as Claude Code Itself

Characteristics of the Haiku request:
- `messages=1`, `input=17`, `output=381`
- Triggered every few conversation turns
- User had not configured any Haiku model

**Conclusion**: This is Claude Code's **auto-memory** feature, which uses `smallFastModel` (Haiku by default) to update `MEMORY.md` in the background.

### Step 3: Root Cause of 403

The model validation logic in `messages.py` used **exact string matching**:

```python
if request_data.model not in allowed_model_names:
    raise HTTPException(403, ...)
```

| Source | Format |
|--------|--------|
| Claude Code request | `claude-haiku-4-5-20251001` |
| DB (token permissions) | `global.anthropic.claude-haiku-4-5-20251001-v1:0` |

Different formats → match fails → 403.

### Step 4: Fix

Normalize both sides before comparison (strip geo prefix and version suffix), then replace `request_data.model` with the Bedrock ID from DB after validation passes to ensure correct routing:

```python
def _normalize_model(name: str) -> str:
    import re
    for prefix in ("global.anthropic.", "us.anthropic.", "eu.anthropic.", "ap.anthropic.", "anthropic."):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return re.sub(r"-v\d+(?::\d+)?$", "", name)

normalized_requested = _normalize_model(request_data.model)
normalized_allowed = {_normalize_model(m) for m in allowed_model_names}

if normalized_requested not in normalized_allowed:
    raise HTTPException(403, ...)

# Replace with Bedrock ID from DB for routing
matched = next((m for m in allowed_model_names if _normalize_model(m) == normalized_requested), None)
if matched and matched != request_data.model:
    request_data.model = matched
```

---

## Claude Code Internal Mechanisms

### auto-memory

Claude Code periodically uses `smallFastModel` to write conversation context into `MEMORY.md`, enabling cross-session memory.

- Storage path: `~/.claude/projects/<path-encoded>/memory/MEMORY.md` (`/` replaced with `-`)
- Trigger signature: `messages=1`, very few input tokens (~17), output is the memory content (~381 tokens)
- Disable: start with `--bare` or set `CLAUDE_CODE_SIMPLE=1`

### smallFastModel

Controls which model is used for lightweight background tasks (auto-memory, conversation compaction, etc.), configured in `~/.claude/settings.json`:

```json
{
  "smallFastModel": "global.anthropic.claude-haiku-4-5-20251001-v1:0"
}
```

Note: even when configured in Bedrock format, Claude Code sends requests to `ANTHROPIC_BASE_URL` using the Anthropic short format (`claude-haiku-4-5-20251001`). The proxy must therefore normalize model names.

### auto-compact (conversation compression)

When conversation history approaches the context limit, Claude Code uses Haiku to compress the history into a summary, replacing the raw history. Similar signature to auto-memory but with higher input token count.

---

## Startup Log Annotation

```
INFO: Waiting for application startup.
10:18:22 - Starting Kolya BR Proxy...
         - Database engine initialized, tables created/verified
         - Rate limiter: Redis distributed mode, global 8.33 req/s (500 RPM),
           burst=10, local fallback 2.78 req/s (÷3 pods)
         - BedrockClient singleton initialized
         - Profile cache refreshed: 23 inference profiles, 15 local FMs, 91 fallback FMs
         - Pricing database already contains 104 records

         [WARNING] mistral.mistral-small-2402-v1:0 not found in cache, trying local region
         [WARNING] qwen.qwen3-coder-next not found in cache, trying local region
         - Back-fill: 142 locally-available models missing pricing,
           checking reference regions ['us-east-1', 'us-west-2']
         - HTTP GET AWS pricing JSON → 200 OK

         ... [many models unavailable in us-west-1, auto-routed to us-west-2
              with pricing back-filled from us-east-1; includes models from
              meta / mistral / qwen / deepseek / nvidia / google / zai /
              moonshot / minimax / openai / amazon — 43 models total] ...

         - Back-filled 43 pricing records on startup

         - Gemini pricing tier-1 (Google official): 17 models
         - Gemini pricing tier-2 (LiteLLM supplement): 17 new models
         - Gemini pricing tier-3 (static legacy): 3 models
         - Gemini pricing saved: 37 models total

         - Scheduled jobs registered:
             Refresh Bedrock inference profile cache (01:50 UTC)
             Update model pricing from AWS (02:00 UTC)
             Update Gemini model pricing from Google (02:30 UTC)
         - Pricing update scheduler started
         - Kolya BR Proxy started successfully

INFO: Application startup complete.
INFO: Uvicorn running on http://0.0.0.0:8000

--- [20 minutes later — first requests] ---

10:38:12 - [Haiku] Request: model=claude-haiku-4-5-20251001, 1 message, streaming
         - Normalized and routed to global.anthropic.claude-haiku-4-5-20251001-v1:0
         → 200 OK ✅
         - Redis connected (lazy connect — established on first use)
         - Prompt cache: 1bp (system, 5min TTL)

10:38:12 - [Opus] Request: model=global.anthropic.claude-opus-4-6-v1, 15 messages, streaming
10:38:13 - Bedrock streaming started
10:38:17 - Bedrock streaming completed
         - Haiku streaming successful: duration=5.061s, input=17, output=381
           (auto-memory write)
         - Prompt cache: 3bp (tools+system+msgs, 5min TTL)
         → 200 OK ✅
         - Usage recorded

10:38:22 - Bedrock streaming started (Opus actual conversation)
10:39:44 - Bedrock streaming completed
         - Opus streaming successful: duration=91.592s, input=16, output=3685,
           cache_write=41658 (first prompt cache write — reusable in subsequent requests)
         - Usage recorded
```

---

## Related Files

| File | Description |
|------|-------------|
| `backend/app/api/anthropic/endpoints/messages.py` | Model name normalization and access control |
| `backend/app/core/security.py` | `hash_token` using SHA256 |
| `~/.claude/settings.json` | `smallFastModel` configuration |
| `~/.claude/projects/.../memory/MEMORY.md` | auto-memory storage location |

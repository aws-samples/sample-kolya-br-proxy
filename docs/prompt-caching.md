# Prompt Caching

Kolya BR Proxy supports automatic prompt cache injection for Anthropic models on AWS Bedrock. This feature reduces costs and latency by caching stable prefixes (system prompts, tool definitions, conversation history) across requests.

## How It Works

When enabled, the proxy automatically injects `cache_control` breakpoints into the Anthropic Messages API request body before sending it to Bedrock. Up to 4 breakpoints are injected (Anthropic API limit), using the following priority:

| Priority | Target | Description |
|----------|--------|-------------|
| 1 | Last tool definition | Tool definitions are stable across turns |
| 2 | System prompt (last block) | System prompt rarely changes |
| 3 | Last assistant message (last non-thinking block) | Caches conversation history prefix |

Thinking and redacted_thinking blocks in assistant messages are skipped — only text and tool_use blocks receive breakpoints.

If the request already contains `cache_control` markers (e.g., set by the client), those count against the budget of 4. Pre-existing markers also have their TTL upgraded to match the server configuration.

## Control Priority

```
Per-request parameter  >  API Key config (token_metadata)  >  Server default (env var)
```

| Per-request | API Key config | Server default | Result |
|-------------|---------------|----------------|--------|
| `bedrock_auto_cache: true` | any | any | Injection enabled |
| `bedrock_auto_cache: false` | any | any | Injection disabled |
| not set | `prompt_cache_enabled: true` | any | Injection enabled |
| not set | `prompt_cache_enabled: false` | any | Injection disabled |
| not set | not set | `true` | Injection enabled |
| not set | not set | `false` | Injection disabled |

## Server Configuration

Environment variables:

```bash
KBR_PROMPT_CACHE_AUTO_INJECT=false  # default: false
KBR_PROMPT_CACHE_TTL=1h             # default: 1h (options: "5m" or "1h")
```

`KBR_PROMPT_CACHE_AUTO_INJECT` defaults to `false`. Administrators can enable it globally or configure per-API-key cache settings via the admin panel (see [Per-API-Key Configuration](#per-api-key-configuration)).

`KBR_PROMPT_CACHE_TTL` controls the cache duration. Anthropic supports two values:

| TTL | Marker | Best for |
|-----|--------|----------|
| `5m` | `{"type": "ephemeral"}` | Short interactions, cost-sensitive workloads |
| `1h` | `{"type": "ephemeral", "ttl": "1h"}` | Long agent sessions (recommended, reduces cache misses between turns) |

The default `1h` is recommended for agent loops where turns may be spaced minutes apart. With `5m`, cache misses are common when users pause between interactions.

## Per-API-Key Configuration

Each API key can have independent prompt cache settings stored in `token_metadata`. These are configured via the admin panel under **API Keys > Settings** (gear icon).

Available settings:

| Setting | Values | Description |
|---------|--------|-------------|
| `prompt_cache_enabled` | `true` / `false` | Enable or disable prompt caching for this key |
| `prompt_cache_ttl` | `"5m"` / `"1h"` | Cache TTL override for this key |

When an API key has no cache settings configured, the server defaults (`KBR_PROMPT_CACHE_AUTO_INJECT` and `KBR_PROMPT_CACHE_TTL`) apply.

Per-request parameters (body or header) always take the highest priority and override API key settings.

## Per-Request Control

### Body (OpenAI SDK `extra_body`)

```python
# Multi-turn agent loop — caching is beneficial
response = client.chat.completions.create(
    model="us.anthropic.claude-sonnet-4-20250514-v1:0",
    messages=[...],
    tools=[...],
    max_tokens=4000,
    extra_body={"bedrock_auto_cache": True}
)
```

### Header

```bash
curl -H "X-Bedrock-Auto-Cache: true" \
     -H "Authorization: Bearer kbr_xxx" \
     -d '{"model":"us.anthropic.claude-sonnet-4-20250514-v1:0","messages":[...]}' \
     https://api.example.com/v1/chat/completions
```

### Per-Request TTL Override

You can also override the cache TTL on a per-request basis using `bedrock_cache_ttl`:

```python
response = client.chat.completions.create(
    model="us.anthropic.claude-sonnet-4-20250514-v1:0",
    messages=[...],
    extra_body={"bedrock_auto_cache": True, "bedrock_cache_ttl": "5m"}
)
```

## When to Disable Caching

Disable caching for **one-shot calls** where the system prompt or input changes every request. In these scenarios, caching incurs a 25% write premium on the first call but achieves 0% hit rate — a net cost increase.

Typical one-shot scenarios:

- Single translation calls with dynamic input
- System prompts containing timestamps or per-request variables
- Batch processing where each request has unique context

### Disabling via Body

```python
# One-shot translation — disable to avoid 25% write premium
response = client.chat.completions.create(
    model="us.anthropic.claude-sonnet-4-20250514-v1:0",
    messages=[{"role": "user", "content": f"Translate: {dynamic_text}"}],
    max_tokens=2000,
    extra_body={"bedrock_auto_cache": False}
)
```

### Disabling via Header

```bash
curl -H "X-Bedrock-Auto-Cache: false" ...
```

### Disabling Server-Wide

If most of your workload is one-shot, set the server default to `false` and let multi-turn clients opt in:

```bash
KBR_PROMPT_CACHE_AUTO_INJECT=false
```

## Cost Model

Cache write pricing depends on the TTL:

| Token type | TTL | Pricing |
|-----------|-----|---------|
| `cache_creation_input_tokens` | `5m` | 1.25x base input price (25% write premium) |
| `cache_creation_input_tokens` | `1h` | 2.0x base input price (100% write premium) |
| `cache_read_input_tokens` | any | 0.1x base input price (90% discount) |
| `input_tokens` | — | 1x base input price (uncached) |

With `5m` TTL, caching breaks even at ~2 requests. With `1h` TTL, the higher write cost means ~3 requests to break even, but significantly reduces cache misses in longer sessions.

> **Note**: The cache pricing multipliers (1.25x for 5m, 2.0x for 1h, 0.1x for reads) are hardcoded in the proxy and based on Anthropic's published pricing. There is no auto-update mechanism — if Anthropic changes their cache pricing, these multipliers must be manually updated in `backend/app/services/pricing.py`.

## Verifying Cache Behavior (Logs)

The proxy logs cache metrics when they are non-zero.

**First request (cache write):**

```
INFO  Prompt cache: 2bp(tools+system,1h,pre=0)
INFO  Bedrock invocation successful: model=us.anthropic.claude-sonnet-4-20250514-v1:0, api=invoke_model, attempt=1, duration=7.7s, input=7, output=152, cache_write=2359
INFO  Chat completion successful: request_id=chatcmpl-xxx, duration=7.7s, prompt=7, completion=152, cache_write=2359
```

**Second identical request (cache hit):**

```
INFO  Prompt cache: 2bp(tools+system,1h,pre=0)
INFO  Bedrock invocation successful: model=us.anthropic.claude-sonnet-4-20250514-v1:0, api=invoke_model, attempt=1, duration=8.1s, input=7, output=178, cache_read=2359
INFO  Chat completion successful: request_id=chatcmpl-xxx, duration=8.1s, prompt=7, completion=178, cache_read=2359
```

**Streaming with partial hit (agent loop, new user message):**

```
INFO  Streaming chat completion successful: request_id=chatcmpl-xxx, duration=5.2s, prompt=105, completion=843, cache_write=1280, cache_read=3240
```

**Caching disabled (no cache fields in log):**

```
INFO  Bedrock invocation successful: model=us.anthropic.claude-sonnet-4-20250514-v1:0, api=invoke_model, attempt=1, duration=4.3s, input=1072, output=200
```

How to read the logs:

| Log pattern | Meaning |
|------------|---------|
| `cache_creation > 0`, `cache_read = 0` | Cache written (first request) |
| `cache_creation = 0`, `cache_read > 0` | Cache hit |
| `cache_creation > 0`, `cache_read > 0` | Partial hit (stable prefix cached, new content written) |
| Neither field present | Caching not active |

## Testing & Verification Guide

This section provides a step-by-step guide to verify prompt caching is working end-to-end, based on real debugging experience.

### Prerequisites

- Backend running locally with `KBR_DEBUG=true` (optional, for debug-level logs)
- A valid API token (`kbr_xxx`)
- `curl` and `jq` installed

### Step 1: Prepare a Test Payload

The most common reason caching silently fails is that the **cached content doesn't meet the minimum token threshold**.

**Bedrock minimum tokens per cache checkpoint:**

| Model | Minimum Tokens |
|-------|---------------|
| Claude Sonnet 4 / 3.5 Sonnet | 1,024 |
| Claude Haiku 3.5 | 2,048 |
| Claude Opus 4.5 / Haiku 4.5 | 4,096 |

> **Pitfall**: The proxy injects breakpoints unconditionally (no character threshold), but **actual caching** is enforced by Bedrock on token count. A short system prompt may have fewer than the minimum tokens and silently fail — Bedrock returns `cache_creation_input_tokens=0` without an error.

Create a test file `test-cache.json` with a system prompt that is **well above** the minimum (recommend 2000+ tokens, ~8000+ characters):

```bash
python3 -c "
import json

rules = []
for i in range(1, 21):
    rules.append(f'Rule {i}: This is an important architectural guideline number {i}. '
        'All implementations must follow strict coding standards including proper error handling, '
        'comprehensive input validation, secure authentication mechanisms, thorough logging, '
        'performance optimization strategies, database query optimization with proper indexing, '
        'API versioning and backward compatibility, comprehensive test coverage requirements, '
        'deployment automation with CI/CD pipelines, monitoring and alerting configuration, '
        'incident response procedures, capacity planning and auto-scaling policies, '
        'data encryption at rest and in transit, access control and authorization frameworks, '
        'code review processes and quality gates, documentation standards and maintenance.')

data = {
    'model': 'global.anthropic.claude-sonnet-4-6',
    'messages': [
        {'role': 'system', 'content': 'You are an expert architect. ' + ' '.join(rules)},
        {'role': 'user', 'content': 'Hello'}
    ]
}

with open('test-cache.json', 'w') as f:
    json.dump(data, f, ensure_ascii=False)

content = data['messages'][0]['content']
print(f'System prompt: {len(content)} chars (~{len(content)//4} tokens)')
"
```

Expected output: `System prompt: ~15000 chars (~3700 tokens)` — well above the 1024 minimum.

### Step 2: First Request (Cache Write)

```bash
curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer kbr_xxx" \
  -H "Content-Type: application/json" \
  -d @test-cache.json | jq '{input: .usage.prompt_tokens, output: .usage.completion_tokens, cache_write: .usage.prompt_tokens_details.cached_tokens}'
```

**Expected logs:**

```
INFO  Prompt cache: 1bp(system,1h,pre=0)
INFO  Bedrock invocation successful: model=global.anthropic.claude-sonnet-4-6, api=invoke_model, attempt=1, duration=7.7s, input=7, output=152, cache_write=2359
INFO  Chat completion successful: request_id=chatcmpl-xxx, duration=7.7s, prompt=7, completion=152, cache_write=2359
```

Key indicators:
- `Prompt cache: 1bp(system,1h,pre=0)` — 1 breakpoint injected on system, TTL=1h, 0 pre-existing
- `cache_write=2359` — Bedrock accepted and cached the system prompt (2359 tokens)
- `input=7` — only the user message counted as regular input

### Step 3: Second Request (Cache Read)

Send the **exact same request** within the configured TTL (default 1 hour):

```bash
curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer kbr_xxx" \
  -H "Content-Type: application/json" \
  -d @test-cache.json | jq '{input: .usage.prompt_tokens, output: .usage.completion_tokens, cache_read: .usage.prompt_tokens_details.cached_tokens}'
```

**Expected logs:**

```
INFO  Prompt cache: 1bp(system,1h,pre=0)
INFO  Bedrock invocation successful: model=global.anthropic.claude-sonnet-4-6, api=invoke_model, attempt=1, duration=8.1s, input=7, output=178, cache_read=2359
INFO  Chat completion successful: request_id=chatcmpl-xxx, duration=8.1s, prompt=7, completion=178, cache_read=2359
```

Key indicators:
- `cache_read=2359` — cache hit! Same 2359 tokens read from cache
- `cache_write` absent — no new cache write needed

### Step 4: Verify Streaming Mode

```bash
curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer kbr_xxx" \
  -H "Content-Type: application/json" \
  -d "$(jq '. + {stream: true}' test-cache.json)"
```

**Expected log:**

```
INFO  Streaming chat completion successful: request_id=chatcmpl-xxx, duration=5.2s, prompt=7, completion=200, cache_read=2359
```

### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| No `Prompt cache:` log line | `should_inject=false` — auto-cache disabled | Check `KBR_PROMPT_CACHE_AUTO_INJECT` env var, or pass `bedrock_auto_cache: true` |
| `Prompt cache:` appears but `cache_write=0` | Content below Bedrock's **token** minimum (1024 for Sonnet) | Make the system prompt longer (8000+ chars to safely exceed 1024 tokens) |
| `cache_write` on first request but no `cache_read` on second | Cache TTL expired or content changed between requests | Send second request within TTL window; ensure content is identical. Consider `KBR_PROMPT_CACHE_TTL=1h` for longer sessions |
| `cache_write` appears but `cache_read` never does | Model may not support caching, or region limitation | Verify model and region support prompt caching in AWS docs |
| Neither `cache_write` nor `cache_read` in log | Injection skipped because client sent manual `cache_control` | Check if `bedrock_prompt_caching` is set in request body |

### Debug Logging

For deeper inspection, set log level to DEBUG (modify `backend/main.py` `logging.basicConfig(level=logging.DEBUG)`). This enables an additional diagnostic log:

```
DEBUG  Prompt cache check: auto_cache=None, server_default=True, should_inject=True, has_cache_control=False, system_len=14969
```

This shows the exact decision chain: per-request override → server default → final decision → character count.

## Interaction with Manual Prompt Caching

If the client already sets `cache_control` markers via `bedrock_prompt_caching` (pass-through), the auto-injection is skipped entirely. This avoids conflicts — the client is assumed to manage caching itself.

## Scope

Auto-injection only applies to Anthropic models (routed via `invoke_model`). Non-Anthropic models using the Converse API are unaffected.

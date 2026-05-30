# Prompt Caching

Kolya BR Proxy supports automatic prompt cache injection for Anthropic models on AWS Bedrock. This feature reduces costs and latency by caching stable prefixes (system prompts, tool definitions, conversation history) across requests.

## Live Example: 2 Users × Multi-Turn Conversations

This example demonstrates how the 3-breakpoint strategy achieves both cross-user cache sharing and same-user sequential cache hits.

### Scenario

- tools = 5000 tokens (same for both users)
- system = 1000 tokens (same for both users)
- Each user message = 100 tokens
- Each assistant reply = 500 tokens
- TTL = 1h

### Timeline

#### T=0: User A Turn 1 (no history, only 2 breakpoints)

```
Request: [tools(5k)☆ | system(1k)☆ | userA1(100)]

Cache state: empty
Longest match: none
─────────────────────────────────────────
READ:   0
WRITE:  tools + system = 6000 tok × 1.25x (first write)
NORMAL: userA1 = 100 tok × 1x
─────────────────────────────────────────
Effective cost: 7600
```

**Cache pool:**

| # | Cached prefix | Tokens | TTL |
|---|---------------|--------|-----|
| 1 | `[tools]` | 5000 | 1h |
| 2 | `[tools + system]` | 6000 | 1h |

---

#### T=1: User B Turn 1 (tools + system identical to A)

```
Request: [tools(5k)☆ | system(1k)☆ | userB1(100)]

Longest match: [tools + system] = 6000 tok ✅ Cross-user hit!
─────────────────────────────────────────
READ:   6000 tok × 0.1x = 600
WRITE:  0 (no new breakpoint beyond match)
NORMAL: userB1 = 100 tok × 1x
─────────────────────────────────────────
Effective cost: 700
```

**Cache pool:** No new entries (READ refreshes TTL of existing entries)

| # | Cached prefix | Tokens | TTL |
|---|---------------|--------|-----|
| 1 | `[tools]` | 5000 | 1h (refreshed) |
| 2 | `[tools + system]` | 6000 | 1h (refreshed) |

---

#### T=2: User A Turn 2 (with history → 3 breakpoints)

```
Request: [tools(5k)☆ | system(1k)☆ | userA1(100) asstA1(500)☆ | userA2(100)]

Longest match: [tools + system] = 6000 tok ✅
─────────────────────────────────────────
READ:   6000 tok × 0.1x = 600       ← tools + system hit
WRITE:  userA1 + asstA1 = 600 tok × 1.25x = 750  ← new conversation cached
NORMAL: userA2 = 100 tok × 1x
─────────────────────────────────────────
Effective cost: 1450
```

**Cache pool:**

| # | Cached prefix | Tokens | TTL |
|---|---------------|--------|-----|
| 1 | `[tools]` | 5000 | 1h |
| 2 | `[tools + system]` | 6000 | 1h |
| 3 | `[tools + system + userA1 + asstA1]` | 6600 | 1h |

---

#### T=3: User B Turn 2 (different history from A)

```
Request: [tools(5k)☆ | system(1k)☆ | userB1(100) asstB1(500)☆ | userB2(100)]

Longest match: [tools + system] = 6000 tok ✅
              (A's #3 doesn't match — B has different conversation)
─────────────────────────────────────────
READ:   6000 tok × 0.1x = 600
WRITE:  userB1 + asstB1 = 600 tok × 1.25x = 750
NORMAL: userB2 = 100 tok × 1x
─────────────────────────────────────────
Effective cost: 1450
```

**Cache pool:**

| # | Cached prefix | Tokens | TTL |
|---|---------------|--------|-----|
| 1 | `[tools]` | 5000 | 1h |
| 2 | `[tools + system]` | 6000 | 1h |
| 3 | `[tools + system + userA1 + asstA1]` | 6600 | 1h |
| 4 | `[tools + system + userB1 + asstB1]` | 6600 | 1h |

---

#### T=4: User A Turn 3 (hits own history cache)

```
Request: [tools(5k)☆ | system(1k)☆ | userA1 asstA1 userA2 asstA2☆ | userA3(100)]

Longest match: [tools + system + userA1 + asstA1] = 6600 tok ✅ Same-user hit!
─────────────────────────────────────────
READ:   6600 tok × 0.1x = 660       ← same-user history hit
WRITE:  userA2 + asstA2 = 600 tok × 1.25x = 750
NORMAL: userA3 = 100 tok × 1x
─────────────────────────────────────────
Effective cost: 1510
```

**Cache pool:**

| # | Cached prefix | Tokens | TTL |
|---|---------------|--------|-----|
| 1 | `[tools]` | 5000 | 1h |
| 2 | `[tools + system]` | 6000 | 1h |
| 3 | `[tools + system + userA1 + asstA1]` | 6600 | 1h |
| 4 | `[tools + system + userB1 + asstB1]` | 6600 | 1h |
| 5 | `[tools + system + userA1 + asstA1 + userA2 + asstA2]` | 7200 | 1h |

---

### Match Process Detail (T=4)

Each breakpoint independently performs a 20-block lookback search:

```
Breakpoint 1 (tools[-1]):
  Prefix hash at current position → matches #1 written at T=0 → READ ✅

Breakpoint 2 (system[-1]):
  Prefix hash at current position → matches #2 written at T=0 → READ ✅

Breakpoint 3 (asstA2):
  Current position block P → look back:
    P-0: [tools+system+userA1+asstA1+userA2+asstA2] → no cache
    P-2: [tools+system+userA1+asstA1] → matches #3 written at T=2 ✅ (only 2 blocks back)

Result: READ up to #3 (6600 tok), WRITE from #3 to current breakpoint (600 tok)
```

Each conversation turn only adds 2 blocks, so the next turn's breakpoint only needs to look back 2 positions to hit the previous turn's cache — well within the 20-block window.

### Cost Summary

| Request | No cache (all 1x) | With cache (3 breakpoints) | Savings |
|---------|-------------------|---------------------------|---------|
| A-Turn1 | 6,100 | 7,600 | -25% (initial investment) |
| B-Turn1 | 6,100 | **700** | **89%** |
| A-Turn2 | 6,700 | **1,450** | **78%** |
| B-Turn2 | 6,700 | **1,450** | **78%** |
| A-Turn3 | 7,300 | **1,510** | **79%** |
| **Total** | **32,900** | **12,710** | **61%** |

### Key Takeaways

| Pattern | Explanation |
|---------|-------------|
| **tools + system are "shared infrastructure"** | All users share them; written once, every hit refreshes TTL |
| **Conversation cache is per-user** | Same user's next turn hits their own history prefix; no cross-user sharing |
| **First request has 25% write premium** | But subsequent requests immediately recoup the cost |
| **Longer conversations = higher READ ratio** | By Turn 10, READ can reach ~95%; WRITE is always just the latest 1 turn |
| **Expired TTL = cache eviction** | Entries not accessed within TTL are automatically removed |

> **Important**: Cache hits require byte-identical prefixes. If the gateway injects per-user/per-request dynamic content into the system prompt (usernames, timestamps, etc.), cross-user sharing breaks. Keep user-specific context in messages, not in the system prompt.

## How It Works

### Breakpoint Injection Strategy

When enabled, the proxy automatically injects `cache_control` breakpoints into the Anthropic Messages API request body before sending it to Bedrock. Up to 4 breakpoints are injected (Anthropic API limit), using the following priority:

| Priority | Target | Description |
|----------|--------|-------------|
| 1 | Last tool definition | Tool definitions are stable across turns |
| 2 | System prompt (last block) | System prompt rarely changes |
| 3 | Last assistant message (last non-thinking block) | Caches conversation history prefix |

As shown in T=2 of the example above, the three breakpoints cover tools, system, and the latest assistant message respectively — forming a layered caching structure.

### Cache Matching Mechanism

Each breakpoint marks a cache write position. On read, the system looks **backward from the breakpoint position block-by-block** within a **20-block lookback window** to find previously written cache entries:

1. **Write**: Compute a prefix hash at the breakpoint position, write a cache entry
2. **Read**: From the current breakpoint position, look back up to 20 blocks to find a matching existing cache entry
3. **Normal conversation**: Each turn adds 2 blocks (user + assistant), so the next turn's breakpoint only needs to look back 2 positions to hit the previous turn's cache — well within the 20-block window

As shown in the T=4 match process above, breakpoint 3 only needs to look back 2 blocks to hit the cache written at T=2.

> **Note**: If more than 20 blocks of new messages are inserted at once (e.g., importing chat history), the breakpoint lookback may exceed the window and cause a cache miss. Normal sequential conversation does not trigger this issue.

### Thinking Block Handling

Thinking and redacted_thinking blocks are skipped — the Anthropic API does not allow `cache_control` markers on thinking blocks; only text and tool_use blocks can receive breakpoints. However, thinking blocks positioned before a breakpoint are still cached as part of the prefix.

**Example**: An assistant message containing thinking + text blocks:

```
assistant.content: [
  {"type": "thinking", "thinking": "Let me think..."},   ← skipped, cannot place breakpoint
  {"type": "thinking", "thinking": "Analysis done"},     ← skipped
  {"type": "text", "text": "The answer is 42"}           ← ☆ breakpoint placed here
]
```

The proxy searches backward from the end of content for the first non-thinking block and places `cache_control` on it. Although the breakpoint is on the text block, both thinking blocks are still cached as part of the prefix.

### Pre-existing Breakpoints & Budget

If the request already contains `cache_control` markers (e.g., set by the client), those count against the budget of 4. Pre-existing markers also have their TTL upgraded to match the server configuration.

**Example**: Client pre-set 2 breakpoints, server TTL configured as `1h`:

```
On arrival:
  tools[-1]:  {"cache_control": {"type": "ephemeral"}}          ← client pre-set (5m)
  system[-1]: {"cache_control": {"type": "ephemeral"}}          ← client pre-set (5m)

After proxy processing:
  tools[-1]:  {"cache_control": {"type": "ephemeral", "ttl": "1h"}}  ← TTL upgraded
  system[-1]: {"cache_control": {"type": "ephemeral", "ttl": "1h"}}  ← TTL upgraded
  assistant:  {"cache_control": {"type": "ephemeral", "ttl": "1h"}}  ← newly injected (budget: 4-2=2)
```

Log: `Prompt cache: 1bp(msgs,1h,pre=2,upg=2)` — 1 new breakpoint injected, 2 pre-existing upgraded.

## Cost Model

Cache write pricing depends on the TTL (as demonstrated by the ×1.25 writes at T=0 and ×0.1 reads at T=1 in the example):

| Token type | TTL | Pricing |
|-----------|-----|---------|
| `cache_creation_input_tokens` | `5m` | 1.25x base input price (25% write premium) |
| `cache_creation_input_tokens` | `1h` | 2.0x base input price (100% write premium) |
| `cache_read_input_tokens` | any | 0.1x base input price (90% discount) |
| `input_tokens` | — | 1x base input price (uncached) |

With `5m` TTL, caching breaks even at ~2 requests. With `1h` TTL, the higher write cost means ~3 requests to break even, but significantly reduces cache misses in longer sessions.

> **Note**: The cache pricing multipliers (1.25x for 5m, 2.0x for 1h, 0.1x for reads) are hardcoded in the proxy and based on Anthropic's published pricing. There is no auto-update mechanism — if Anthropic changes their cache pricing, these multipliers must be manually updated in `backend/app/services/pricing.py`.

## Configuration

### Control Priority

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

### Server Configuration

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

### Per-API-Key Configuration

Each API key can have independent prompt cache settings stored in `token_metadata`. These are configured via the admin panel under **API Keys > Settings** (gear icon).

Available settings:

| Setting | Values | Description |
|---------|--------|-------------|
| `prompt_cache_enabled` | `true` / `false` | Enable or disable prompt caching for this key |
| `prompt_cache_ttl` | `"5m"` / `"1h"` | Cache TTL override for this key |

When an API key has no cache settings configured, the server defaults (`KBR_PROMPT_CACHE_AUTO_INJECT` and `KBR_PROMPT_CACHE_TTL`) apply.

Per-request parameters (body or header) always take the highest priority and override API key settings.

### Per-Request Control

#### Body (OpenAI SDK `extra_body`)

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

#### Header

```bash
curl -H "X-Bedrock-Auto-Cache: true" \
     -H "Authorization: Bearer kbr_xxx" \
     -d '{"model":"us.anthropic.claude-sonnet-4-20250514-v1:0","messages":[...]}' \
     https://api.example.com/v1/chat/completions
```

#### Per-Request TTL Override

You can override the cache TTL on a per-request basis using `bedrock_cache_ttl`:

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

## Log Verification & Testing

### Log Examples

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

### Log Interpretation

| Log pattern | Meaning |
|------------|---------|
| `cache_creation > 0`, `cache_read = 0` | Cache written (first request) |
| `cache_creation = 0`, `cache_read > 0` | Cache hit |
| `cache_creation > 0`, `cache_read > 0` | Partial hit (stable prefix cached, new content written) |
| Neither field present | Caching not active |

### End-to-End Testing Guide

This section provides a step-by-step guide to verify prompt caching is working correctly.

#### Prerequisites

- Backend running locally with `KBR_DEBUG=true` (optional, for debug-level logs)
- A valid API token (`kbr_xxx`)
- `curl` and `jq` installed

#### Step 1: Prepare a Test Payload

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

#### Step 2: First Request (Cache Write)

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

#### Step 3: Second Request (Cache Read)

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

#### Step 4: Verify Streaming Mode

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

## Appendix

### Interaction with Manual Prompt Caching

If the client already sets `cache_control` markers via `bedrock_prompt_caching` (pass-through), the auto-injection is skipped entirely. This avoids conflicts — the client is assumed to manage caching itself.

### Scope

Auto-injection only applies to Anthropic models (routed via `invoke_model`). Non-Anthropic models using the Converse API are unaffected.

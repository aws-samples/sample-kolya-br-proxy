# GPT-5.6 Sol Responses routing

GPT-5.6 Sol always uses an OpenAI Responses API upstream. It must not fall
through to boto3 Converse because Converse does not preserve the explicit
prompt-cache fields used by this gateway.

```mermaid
flowchart LR
    subgraph Clients[Client protocols]
        Chat[POST /v1/chat/completions]
        Messages[POST /v1/messages]
        Native[POST /v1/responses]
    end

    subgraph Gateway[Kolya BR Proxy]
        Auth[Quota and exact model authorization]
        Convert[Protocol conversion to Responses input]
        Cache[Cache validation and conversion<br/>cache_control → prompt_cache_breakpoint<br/>prompt_cache_options.mode = explicit]
        Route{Exact model ID}
        Adapt[Protocol-specific response adapter]
        Usage[Usage categories and pricing<br/>uncached / cache write / cache read / output]
        SafeLog[Structure-only logs<br/>backend / model / region / stream<br/>cache mode / breakpoint count / input types]
    end

    subgraph AWS[AWS Bedrock]
        Mantle[Bedrock Mantle Responses<br/>bedrock-mantle.REGION.api.aws/openai/v1/responses<br/>SigV4: bedrock]
        Runtime[Bedrock Runtime Responses<br/>bedrock-runtime.REGION.amazonaws.com/openai/v1/responses<br/>SigV4: bedrock]
        Converse[boto3 Converse]
    end

    Chat --> Auth
    Messages --> Auth
    Native --> Auth
    Auth --> Convert --> Cache --> Route
    Route -- openai.gpt-5.6-sol --> Mantle
    Route -- us.openai.gpt-5.6-sol<br/>ID preserved --> Runtime
    Route -- global.openai.gpt-5.6-sol<br/>ID preserved --> Runtime
    Mantle --> Adapt
    Runtime --> Adapt
    Adapt --> Chat
    Adapt --> Messages
    Adapt --> Native
    Mantle --> Usage
    Runtime --> Usage
    Cache --> SafeLog
    Route -. GPT-5.6 Sol never falls through .-> Converse

    classDef blocked fill:#fee2e2,stroke:#dc2626,color:#7f1d1d;
    class Converse blocked;
```

## Routing invariants (all GPT models)

Routing is automatic; there is no Mantle/Runtime switch in Settings. The single
source of truth is `backend/app/services/openai_gpt_catalog.py`, which also
drives explicit-cache validation, billing, and the admin pricing table.

| Requested model | Upstream | Model ID sent upstream |
| --- | --- | --- |
| `openai.gpt-*` (canonical) | Bedrock Mantle Responses | canonical ID |
| `us.openai.gpt-*` | Bedrock Runtime Responses | exact US profile ID |
| `global.openai.gpt-*` | Bedrock Runtime Responses | exact Global profile ID |
| Unpublished profile (e.g. `us.openai.gpt-5.5`) | rejected | — |

US and Global grants are checked exactly. A token authorized for one profile
does not gain access to the other profile. GPT requests never fall back to
Converse.

## Explicit prompt cache by model

| Model family | Mantle | US / Global Runtime | Breakpoint content |
| --- | --- | --- | --- |
| GPT-5.6 Sol / Terra / Luna | ✓ | ✓ | text, image, file |
| GPT-6 Sol / Luna / Astra, GPT-6.1 Sol | ✓ | ✓ | text, image (image live-verified) |
| GPT-5.5 / GPT-5.4 | implicit only | not offered | — |

Cache prices on a model card never imply explicit-cache support; capability is
declared per route in the catalog.

## Explicit-cache contract

- Supported content blocks may carry `cache_control: {"type": "ephemeral"}`.
- The gateway converts each marker to
  `prompt_cache_breakpoint: {"mode": "explicit"}` and adds top-level
  `prompt_cache_options: {"mode": "explicit"}`.
- Requests may contain at most four breakpoints.
- Markers on content the exact model cannot cache (or on any content for a
  model without explicit caching) are rejected with a 4xx before the upstream
  call, on Chat Completions, Anthropic Messages, and native Responses.
- Tool-definition markers are rejected; place the breakpoint on a later text
  block.
- `service_tier: "ultrafast"` (GPT-6 Astra, GPT-6.1 Sol) is billed at the
  model-card Ultrafast rates (6× Standard); canonical Ultrafast requests use
  Mantle `us-east-1`. Other models reject Ultrafast with a 400.
- Requests without markers retain the implicit-cache wire shape.

## Pricing

The gateway records uncached input, cache write, cache read, and output
separately and bills each exact ID with its model-card rates. When the total
input (uncached + cache write + cache read) exceeds 272K tokens, the long-context
band applies to the whole request. The admin pricing table shows both bands.
Historical usage rows are not changed.

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
        Mantle[Bedrock Mantle Responses<br/>bedrock-mantle.REGION.api.aws/openai/v1/responses<br/>SigV4: bedrock-mantle]
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

## Routing invariants

| Requested model | Upstream | Model ID sent upstream |
| --- | --- | --- |
| `openai.gpt-5.6-sol` | Bedrock Mantle Responses | canonical ID |
| `us.openai.gpt-5.6-sol` | Bedrock Runtime Responses | exact US profile ID |
| `global.openai.gpt-5.6-sol` | Bedrock Runtime Responses | exact Global profile ID |

US and Global grants are checked exactly. A token authorized for one profile
does not gain access to the other profile.

## Explicit-cache contract

- Text and supported image content blocks may carry
  `cache_control: {"type": "ephemeral"}`.
- The gateway converts each marker to
  `prompt_cache_breakpoint: {"mode": "explicit"}` and adds top-level
  `prompt_cache_options: {"mode": "explicit"}`.
- Requests may contain at most four breakpoints.
- Tool-definition markers are rejected with a client error instead of being
  silently discarded; place the breakpoint on a later text or image block.
- Requests without markers retain the implicit-cache wire shape.

The gateway records the upstream usage categories separately and applies
independent US and Global pricing. Historical usage rows are not changed.

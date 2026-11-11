"""Per-key prompt cache scope shared by every model path.

All API keys reach Bedrock through the gateway's one AWS account, and the
prompt cache is per account, so identical prefixes from different keys would
hit each other's cache entries. Prefixing each key's prompt with a stable,
key-specific marker keeps cached prefixes from ever matching across keys
while leaving same-key caching intact.
"""

import hashlib

from app.core.config import get_settings


def _digest(scope: str) -> str:
    return hashlib.sha256(f"kbp-cache-scope:{scope}".encode()).hexdigest()


def isolation_enabled() -> bool:
    return bool(get_settings().PROMPT_CACHE_TENANT_ISOLATION)


def marker_text(scope: str) -> str:
    return f"[cache scope {_digest(scope)[:16]}]"


def cache_key(scope: str) -> str:
    return f"kbp-{_digest(scope)[:32]}"


def scope_responses_cache(body: dict, scope: str | None) -> None:
    """Scope an OpenAI Responses request body (Mantle or Runtime) to one key.

    GPT caching is implicit: the cached prefix runs tools, instructions,
    then input, with breakpoints at the end of the latest message (and on
    GPT-5.5 and earlier also every ~2,048 tokens). The marker goes first in
    ``instructions`` and first in ``input`` so every breakpoint after the
    tools sits behind it. ``prompt_cache_key`` is always overwritten with the
    key's own value: OpenAI documents it as separating cache reuse on
    GPT-5.6+, and a client must not pick another key's partition.
    """
    if not scope or not isolation_enabled():
        return
    marker = marker_text(scope)

    instructions = body.get("instructions")
    if isinstance(instructions, str) and instructions:
        body["instructions"] = f"{marker}\n{instructions}"

    item = {"role": "developer", "content": [{"type": "input_text", "text": marker}]}
    current = body.get("input")
    if isinstance(current, str):
        body["input"] = [
            item,
            {"role": "user", "content": [{"type": "input_text", "text": current}]},
        ]
    elif isinstance(current, list):
        body["input"] = [item, *current]
    else:
        body["input"] = [item]

    body["prompt_cache_key"] = cache_key(scope)

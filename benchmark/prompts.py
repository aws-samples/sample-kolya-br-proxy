"""Fixed prompt library for reproducible benchmarks.

Three sizes (small/medium/large), each available in OpenAI, Anthropic, and
Gemini native formats.
"""

_SMALL_USER = "Explain what a hash table is in exactly two sentences."

_MEDIUM_SYSTEM = (
    "You are an expert code reviewer. Analyze the code below for bugs, "
    "performance issues, and security vulnerabilities. Be concise."
)
_MEDIUM_USER = """Review this Python function:

```python
import hashlib
import os
from typing import Optional

class TokenManager:
    def __init__(self, secret_key: str):
        self.secret_key = secret_key
        self._cache = {}

    def generate_token(self, user_id: int) -> str:
        salt = os.urandom(16).hex()
        raw = f"{user_id}:{salt}:{self.secret_key}"
        token = hashlib.sha256(raw.encode()).hexdigest()
        self._cache[token] = user_id
        return token

    def validate_token(self, token: str) -> Optional[int]:
        return self._cache.get(token)

    def revoke_token(self, token: str) -> bool:
        if token in self._cache:
            del self._cache[token]
            return True
        return False

    def cleanup_expired(self):
        # TODO: implement expiry logic
        pass
```

List the top 3 issues found."""

_LARGE_SYSTEM = (
    "You are a senior backend engineer helping with system design. "
    "Consider scalability, reliability, cost, and operational simplicity. "
    "When suggesting solutions, explain trade-offs briefly."
)
_LARGE_MESSAGES = [
    {
        "role": "user",
        "content": (
            "We have a FastAPI service proxying LLM requests to AWS Bedrock. "
            "Currently it handles ~500 RPM with 2 pods. We need to scale to "
            "5000 RPM. The main bottleneck is Bedrock rate limits per region. "
            "What architecture changes would you recommend?"
        ),
    },
    {
        "role": "assistant",
        "content": (
            "To scale from 500 to 5000 RPM, I'd recommend three changes:\n\n"
            "1. **Multi-region fan-out**: Distribute requests across 3-5 AWS regions "
            "using cross-region inference profiles. Each region has its own quota, "
            "so 5 regions x 1000 RPM = 5000 RPM total.\n\n"
            "2. **Request queuing**: Add an SQS/Redis queue between the API layer "
            "and Bedrock calls. This absorbs burst traffic and provides backpressure.\n\n"
            "3. **Horizontal pod scaling**: Scale from 2 to 10-15 pods with HPA "
            "based on custom metrics (queue depth or concurrent Bedrock calls)."
        ),
    },
    {
        "role": "user",
        "content": (
            "Good suggestions. For the multi-region approach, how do we handle "
            "prompt caching? Cache entries are region-specific in Bedrock. If we "
            "spread requests across 5 regions, cache hit rate drops to ~20%. "
            "For a system where 60% of requests benefit from cache hits, this "
            "could increase costs significantly. How would you balance cache "
            "efficiency with throughput scaling?"
        ),
    },
]


def openai_messages(size: str = "small") -> list[dict]:
    """Return messages array in OpenAI chat format."""
    if size == "small":
        return [{"role": "user", "content": _SMALL_USER}]
    if size == "medium":
        return [
            {"role": "system", "content": _MEDIUM_SYSTEM},
            {"role": "user", "content": _MEDIUM_USER},
        ]
    # large
    return [
        {"role": "system", "content": _LARGE_SYSTEM},
        *_LARGE_MESSAGES,
    ]


def anthropic_payload(
    size: str = "small",
    model: str = "",
    max_tokens: int = 256,
    thinking_budget: int = 0,
) -> dict:
    """Return full request body in Anthropic Messages format."""
    if size == "small":
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": _SMALL_USER}],
        }
    elif size == "medium":
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "system": _MEDIUM_SYSTEM,
            "messages": [{"role": "user", "content": _MEDIUM_USER}],
        }
    else:
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "system": _LARGE_SYSTEM,
            "messages": [*_LARGE_MESSAGES],
        }
    if thinking_budget > 0:
        payload["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        payload["temperature"] = 1  # thinking requires temperature=1
    return payload


def gemini_payload(
    size: str = "small", max_tokens: int = 256, temperature: float = 0.7
) -> dict:
    """Return request body in Gemini native format."""
    gen_config = {"maxOutputTokens": max_tokens, "temperature": temperature}
    if size == "small":
        return {
            "contents": [{"role": "user", "parts": [{"text": _SMALL_USER}]}],
            "generationConfig": gen_config,
        }
    if size == "medium":
        return {
            "systemInstruction": {"parts": [{"text": _MEDIUM_SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": _MEDIUM_USER}]}],
            "generationConfig": gen_config,
        }
    # large
    contents = []
    for msg in _LARGE_MESSAGES:
        role = "model" if msg["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    return {
        "systemInstruction": {"parts": [{"text": _LARGE_SYSTEM}]},
        "contents": contents,
        "generationConfig": gen_config,
    }

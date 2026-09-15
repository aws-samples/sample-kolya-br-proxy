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


_XLARGE_SYSTEM = (
    "You are a world-class operations-research and formal-reasoning engine. "
    "For every problem you must reason step by step, enumerate the relevant "
    "cases exhaustively, prove why rejected branches are infeasible, and only "
    "then state the final answer. Never skip intermediate steps. If multiple "
    "optima exist, list all of them and prove there are no others."
)

# A deliberately hard, large-input constraint-satisfaction + optimization task.
# The employee/shift table and the dense web of constraints inflate the input
# token count and force a long chain of reasoning before any answer is possible.
_XLARGE_USER = """Solve the following combined scheduling, routing, and optimization problem completely. Show all reasoning.

## Part A — Nurse shift scheduling (constraint satisfaction)

A hospital ward runs 3 shifts per day (Day D, Evening E, Night N) for 7 days (Mon..Sun). There are 8 nurses: n1..n8. Each shift on each day must be staffed by exactly 2 nurses. Assign nurses to shifts subject to ALL of the following hard constraints:

1. Each nurse works at most 5 of the 21 shifts in the week.
2. No nurse works two shifts on the same day.
3. A nurse who works a Night shift cannot work a Day shift the next day (needs rest).
4. n1 and n2 must never be scheduled on the same shift (personality conflict).
5. n3 is only available Mon, Tue, Wed. n4 is unavailable on weekends (Sat, Sun).
6. n5 must work exactly one Night shift and it must be on the weekend.
7. Every Night shift must include at least one of {n6, n7, n8} (senior nurses).
8. n8 is on mandatory training Wed and Thu (unavailable both full days).
9. Across the week, the total shifts worked by n6, n7, n8 combined must be between 9 and 12 inclusive.
10. No nurse may work more than 3 consecutive days (a day counts as worked if they have any shift that day).

Provide one complete valid assignment as a 7x3 table (rows = days, columns = D/E/N, each cell = the two nurse IDs). Then prove your assignment satisfies constraints 1, 3, 6, 7, 9, and 10 explicitly by counting.

## Part B — Delivery routing (optimization)

After the schedule, a courier must deliver supplies to 6 wards W1..W6 starting and ending at the pharmacy P. Travel times (minutes, symmetric) are:

P-W1=9, P-W2=14, P-W3=21, P-W4=7, P-W5=18, P-W6=11,
W1-W2=6, W1-W3=17, W1-W4=12, W1-W5=20, W1-W6=8,
W2-W3=10, W2-W4=15, W2-W5=9, W2-W6=13,
W3-W4=19, W3-W5=5, W3-W6=16,
W4-W5=22, W4-W6=10,
W5-W6=7.

Additional constraints:
- W3 must be visited before W5 (W3's supplies feed W5's prep).
- W2 must be visited immediately after W1 (paired handoff).
- The total route must not exceed 80 minutes.

Find the route (a permutation of W1..W6 bracketed by P) that minimizes total travel time while satisfying the ordering constraints, and prove it is optimal (or that it is the best among feasible routes) by bounding or enumerating the feasible candidates. State the total minutes.

## Part C — Reconciliation

Nurse n7 is also the only qualified courier. The delivery run takes place during a single Evening (E) shift and occupies the whole shift. Identify every day on which, given your Part A schedule, n7 is free to perform the Part B delivery during the Evening shift (i.e. n7 is NOT assigned to that day's Evening shift and performing it does not violate any Part A constraint). If your Part A schedule leaves no such day, revise Part A minimally so that at least one exists, and re-verify the affected constraints.

Give a final consolidated summary: the schedule table, the optimal route with its minute total, and the chosen delivery day for n7."""


def openai_messages(size: str = "small") -> list[dict]:
    """Return messages array in OpenAI chat format."""
    if size == "small":
        return [{"role": "user", "content": _SMALL_USER}]
    if size == "medium":
        return [
            {"role": "system", "content": _MEDIUM_SYSTEM},
            {"role": "user", "content": _MEDIUM_USER},
        ]
    if size == "xlarge":
        return [
            {"role": "system", "content": _XLARGE_SYSTEM},
            {"role": "user", "content": _XLARGE_USER},
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

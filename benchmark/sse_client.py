"""SSE stream parser with TTFT measurement for Locust.

Handles three SSE formats:
- OpenAI: `data: {"choices":[{"delta":{"content":"..."}}]}`
- Anthropic: `event: content_block_delta` + `data: {"delta":{"text":"..."}}`
- Gemini: `data: {"candidates":[{"content":{"parts":[{"text":"..."}]}}]}`
"""

import json
import time

from locust import events


def _is_openai_content(obj: dict) -> bool:
    """Check if a parsed OpenAI SSE chunk contains a content delta."""
    for choice in obj.get("choices", []):
        if choice.get("delta", {}).get("content"):
            return True
    return False


def _is_anthropic_content(obj: dict, prev_event: str) -> bool:
    """Check if a parsed Anthropic SSE chunk contains a text delta."""
    if prev_event != "content_block_delta":
        return False
    delta = obj.get("delta", {})
    return delta.get("type") == "text_delta" and bool(delta.get("text"))


def _is_anthropic_thinking(obj: dict, prev_event: str) -> bool:
    """Check if a parsed Anthropic SSE chunk contains a thinking delta."""
    if prev_event != "content_block_delta":
        return False
    delta = obj.get("delta", {})
    return delta.get("type") == "thinking_delta" and bool(delta.get("thinking"))


def _is_gemini_content(obj: dict) -> bool:
    """Check if a parsed Gemini SSE chunk contains generated text."""
    for candidate in obj.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if part.get("text"):
                return True
    return False


def _extract_openai_usage(obj: dict) -> dict | None:
    """Extract usage from a parsed OpenAI SSE chunk."""
    usage = obj.get("usage")
    if usage and usage.get("total_tokens"):
        return usage
    return None


def _extract_anthropic_usage(obj: dict, prev_event: str) -> dict | None:
    """Extract usage from a parsed Anthropic message_delta chunk."""
    if prev_event != "message_delta":
        return None
    usage = obj.get("usage", {})
    if usage.get("output_tokens"):
        return usage
    return None


def _extract_gemini_usage(obj: dict) -> dict | None:
    """Extract usage from parsed Gemini usageMetadata."""
    meta = obj.get("usageMetadata", {})
    if meta.get("totalTokenCount"):
        return {
            "prompt_tokens": meta.get("promptTokenCount", 0),
            "completion_tokens": meta.get("candidatesTokenCount", 0),
            "cached_tokens": meta.get("cachedContentTokenCount", 0),
        }
    return None


def stream_and_measure(response, api_format: str) -> dict:
    """Parse an SSE response, measure TTFT, and extract usage.

    Args:
        response: An open requests/urllib3 streaming response with iter_lines().
        api_format: "openai", "anthropic", or "gemini".

    Returns:
        dict with keys: ttft_s, total_s, usage, error
    """
    start = time.monotonic()
    ttft = None
    ttft_thinking = None
    usage = None
    prev_event = ""

    try:
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            line = (
                raw_line
                if isinstance(raw_line, str)
                else raw_line.decode("utf-8", errors="replace")
            )

            if line.startswith(":"):
                continue

            if line.startswith("event: "):
                prev_event = line[7:].strip()
                continue

            if not line.startswith("data: ") or line == "data: [DONE]":
                continue

            if ttft is not None and usage is not None:
                continue

            try:
                obj = json.loads(line[6:])
            except (json.JSONDecodeError, TypeError):
                continue

            if (
                ttft_thinking is None
                and api_format == "anthropic"
                and _is_anthropic_thinking(obj, prev_event)
            ):
                ttft_thinking = time.monotonic() - start

            if ttft is None:
                is_content = False
                if api_format == "openai":
                    is_content = _is_openai_content(obj)
                elif api_format == "anthropic":
                    is_content = _is_anthropic_content(obj, prev_event)
                elif api_format == "gemini":
                    is_content = _is_gemini_content(obj)
                if is_content:
                    ttft = time.monotonic() - start

            if api_format == "openai":
                u = _extract_openai_usage(obj)
            elif api_format == "anthropic":
                u = _extract_anthropic_usage(obj, prev_event)
            elif api_format == "gemini":
                u = _extract_gemini_usage(obj)
            else:
                u = None
            if u:
                usage = u

    except Exception as exc:
        total = time.monotonic() - start
        return {
            "ttft_s": ttft,
            "ttft_thinking_s": ttft_thinking,
            "total_s": total,
            "usage": usage,
            "error": str(exc),
        }

    total = time.monotonic() - start
    return {
        "ttft_s": ttft,
        "ttft_thinking_s": ttft_thinking,
        "total_s": total,
        "usage": usage,
        "error": None,
    }


def fire_ttft_event(name: str, ttft_ms: float, env=None) -> None:
    """Report TTFT as a custom Locust metric."""
    target = env.events if env else events
    target.request.fire(
        request_type="TTFT",
        name=name,
        response_time=ttft_ms,
        response_length=0,
        exception=None,
        context={},
    )

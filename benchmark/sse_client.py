"""SSE stream parser with TTFT measurement for Locust.

Handles three SSE formats:
- OpenAI: `data: {"choices":[{"delta":{"content":"..."}}]}`
- Anthropic: `event: content_block_delta` + `data: {"delta":{"text":"..."}}`
- Gemini: `data: {"candidates":[{"content":{"parts":[{"text":"..."}]}}]}`
"""

import json
import time

from locust import events


def _is_openai_content(line: str) -> bool:
    """Check if an OpenAI SSE data line contains a content delta."""
    if not line.startswith("data: ") or line == "data: [DONE]":
        return False
    try:
        obj = json.loads(line[6:])
        for choice in obj.get("choices", []):
            delta = choice.get("delta", {})
            if delta.get("content"):
                return True
    except (json.JSONDecodeError, TypeError):
        pass
    return False


def _is_anthropic_content(line: str, prev_event: str) -> bool:
    """Check if an Anthropic SSE data line contains a text delta."""
    if prev_event != "content_block_delta":
        return False
    if not line.startswith("data: "):
        return False
    try:
        obj = json.loads(line[6:])
        delta = obj.get("delta", {})
        return delta.get("type") == "text_delta" and bool(delta.get("text"))
    except (json.JSONDecodeError, TypeError):
        return False


def _is_gemini_content(line: str) -> bool:
    """Check if a Gemini SSE data line contains generated text."""
    if not line.startswith("data: "):
        return False
    try:
        obj = json.loads(line[6:])
        for candidate in obj.get("candidates", []):
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                if part.get("text"):
                    return True
    except (json.JSONDecodeError, TypeError):
        pass
    return False


def _extract_openai_usage(line: str) -> dict | None:
    """Extract usage from an OpenAI SSE chunk (sent near end of stream)."""
    if not line.startswith("data: ") or line == "data: [DONE]":
        return None
    try:
        obj = json.loads(line[6:])
        usage = obj.get("usage")
        if usage and usage.get("total_tokens"):
            return usage
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _extract_anthropic_usage(line: str, prev_event: str) -> dict | None:
    """Extract usage from Anthropic message_delta event."""
    if prev_event != "message_delta" or not line.startswith("data: "):
        return None
    try:
        obj = json.loads(line[6:])
        usage = obj.get("usage", {})
        if usage.get("output_tokens"):
            return usage
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _extract_gemini_usage(line: str) -> dict | None:
    """Extract usage from Gemini usageMetadata."""
    if not line.startswith("data: "):
        return None
    try:
        obj = json.loads(line[6:])
        meta = obj.get("usageMetadata", {})
        if meta.get("totalTokenCount"):
            return {
                "prompt_tokens": meta.get("promptTokenCount", 0),
                "completion_tokens": meta.get("candidatesTokenCount", 0),
                "cached_tokens": meta.get("cachedContentTokenCount", 0),
            }
    except (json.JSONDecodeError, TypeError):
        pass
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
    usage = None
    prev_event = ""
    total_output_bytes = 0

    try:
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            line = (
                raw_line
                if isinstance(raw_line, str)
                else raw_line.decode("utf-8", errors="replace")
            )

            # Skip heartbeat comments
            if line.startswith(":"):
                continue

            # Track Anthropic event types
            if line.startswith("event: "):
                prev_event = line[7:].strip()
                continue

            # TTFT detection
            if ttft is None:
                is_content = False
                if api_format == "openai":
                    is_content = _is_openai_content(line)
                elif api_format == "anthropic":
                    is_content = _is_anthropic_content(line, prev_event)
                elif api_format == "gemini":
                    is_content = _is_gemini_content(line)
                if is_content:
                    ttft = time.monotonic() - start

            # Usage extraction (keep last seen)
            if api_format == "openai":
                u = _extract_openai_usage(line)
                if u:
                    usage = u
            elif api_format == "anthropic":
                u = _extract_anthropic_usage(line, prev_event)
                if u:
                    usage = u
            elif api_format == "gemini":
                u = _extract_gemini_usage(line)
                if u:
                    usage = u

            if line.startswith("data: "):
                total_output_bytes += len(line)

    except Exception as exc:
        total = time.monotonic() - start
        return {"ttft_s": ttft, "total_s": total, "usage": usage, "error": str(exc)}

    total = time.monotonic() - start
    return {"ttft_s": ttft, "total_s": total, "usage": usage, "error": None}


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

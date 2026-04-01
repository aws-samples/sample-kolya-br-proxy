"""
Google Gemini API client service.

Uses the native Gemini generateContent / streamGenerateContent API.
Converts OpenAI-format requests to Gemini native format and responses back,
so the rest of the pipeline (chat.py, usage recording) remains unchanged.
"""

import json
import logging
import re
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# Google Gemini API base URL (v1beta)
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Gemini finishReason → OpenAI finish_reason
_FINISH_REASON_MAP: Dict[str, str] = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "BLOCKLIST": "content_filter",
    "PROHIBITED_CONTENT": "content_filter",
    "SPII": "content_filter",
    "MALFORMED_FUNCTION_CALL": "stop",
    "OTHER": "stop",
}


def is_gemini_model(model: str) -> bool:
    """Return True if model should be routed to Google Gemini API."""
    return model.startswith("gemini-") or model.startswith("models/gemini-")


def _make_friendly_name(model_id: str, display_name: str) -> str:
    """Build a clean friendly name from Google's displayName."""
    if display_name:
        return display_name
    parts = model_id.replace("gemini-", "").split("-")
    return "Gemini " + " ".join(p.capitalize() for p in parts)


# ---------------------------------------------------------------------------
# Request conversion: OpenAI format → Gemini native
# ---------------------------------------------------------------------------


def _content_part_to_gemini(part: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a single OpenAI ContentPart dict to a Gemini Part dict."""
    ptype = part.get("type")
    if ptype == "text":
        return {"text": part.get("text", "")}
    if ptype == "image_url":
        url = (part.get("image_url") or {}).get("url", "")
        if url.startswith("data:"):
            # data:<mimeType>;base64,<data>
            header, _, b64 = url.partition(",")
            mime = header[5:].split(";")[0]  # strip "data:" and ";base64"
            return {"inlineData": {"mimeType": mime, "data": b64}}
        # Regular URL → fileData (infer MIME from extension)
        mime = "image/jpeg"
        for ext, m in [
            (".png", "image/png"),
            (".webp", "image/webp"),
            (".gif", "image/gif"),
            (".bmp", "image/bmp"),
        ]:
            if url.lower().endswith(ext):
                mime = m
                break
        return {"fileData": {"mimeType": mime, "fileUri": url}}
    # Unknown type — best-effort text fallback
    return {"text": str(part.get("text", ""))}


def _msg_content_to_parts(content: Any) -> List[Dict[str, Any]]:
    """Convert an OpenAI message content value (str or list) to Gemini parts."""
    if content is None:
        return []
    if isinstance(content, str):
        return [{"text": content}] if content else []
    if isinstance(content, list):
        return [_content_part_to_gemini(p) for p in content if isinstance(p, dict)]
    return [{"text": str(content)}]


def _openai_messages_to_gemini(
    messages: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Convert OpenAI messages array to Gemini (systemInstruction, contents).

    Roles:
      system     → systemInstruction.parts
      user       → contents entry with role "user"
      assistant  → contents entry with role "model"
                   (tool_calls → functionCall parts)
      tool       → contents entry with role "user" and functionResponse parts
                   (consecutive tool messages are merged into one user turn)
    """
    # Pre-build tool_call_id → function_name map from assistant messages
    tc_id_to_name: Dict[str, str] = {}
    for msg in messages:
        for tc in msg.get("tool_calls") or []:
            fn_name = (tc.get("function") or {}).get("name", "")
            tc_id_to_name[tc.get("id", "")] = fn_name

    system_parts: List[Dict[str, Any]] = []
    contents: List[Dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")
        tool_calls = msg.get("tool_calls")

        # ── system ──────────────────────────────────────────────────────────
        if role == "system":
            system_parts.extend(_msg_content_to_parts(content))
            continue

        # ── tool result ─────────────────────────────────────────────────────
        if role == "tool":
            tc_id = msg.get("tool_call_id", "")
            fn_name = tc_id_to_name.get(tc_id, tc_id)
            raw = content or ""
            try:
                result = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                result = {"output": raw}
            if not isinstance(result, dict):
                result = {"output": result}

            fn_resp_part = {
                "functionResponse": {"name": fn_name, "response": result}
            }
            # Merge consecutive tool results into a single user turn
            if (
                contents
                and contents[-1].get("role") == "user"
                and contents[-1].get("parts")
                and "functionResponse" in contents[-1]["parts"][0]
            ):
                contents[-1]["parts"].append(fn_resp_part)
            else:
                contents.append({"role": "user", "parts": [fn_resp_part]})
            continue

        # ── user / assistant ─────────────────────────────────────────────────
        gemini_role = "model" if role == "assistant" else "user"
        parts: List[Dict[str, Any]] = _msg_content_to_parts(content)

        # Assistant tool calls → functionCall parts
        for tc in tool_calls or []:
            fn = tc.get("function") or {}
            args_raw = fn.get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except (json.JSONDecodeError, TypeError):
                args = {}
            parts.append(
                {"functionCall": {"name": fn.get("name", ""), "args": args}}
            )

        if not parts:
            parts = [{"text": ""}]

        contents.append({"role": gemini_role, "parts": parts})

    system_instruction = {"parts": system_parts} if system_parts else None
    return system_instruction, contents


def _openai_tools_to_gemini(
    tools: Optional[List[Dict[str, Any]]],
) -> Optional[List[Dict[str, Any]]]:
    """Convert OpenAI tools list to Gemini functionDeclarations format."""
    if not tools:
        return None
    declarations = []
    for tool in tools:
        if tool.get("type") == "function":
            fn = tool.get("function") or {}
            decl: Dict[str, Any] = {"name": fn.get("name", "")}
            if fn.get("description"):
                decl["description"] = fn["description"]
            if fn.get("parameters"):
                decl["parameters"] = fn["parameters"]
            declarations.append(decl)
    return [{"functionDeclarations": declarations}] if declarations else None


def _openai_tool_choice_to_gemini(
    tool_choice: Any,
) -> Optional[Dict[str, Any]]:
    """Convert OpenAI tool_choice to Gemini toolConfig."""
    if tool_choice is None:
        return None
    if tool_choice == "none":
        return {"functionCallingConfig": {"mode": "NONE"}}
    if tool_choice == "auto":
        return {"functionCallingConfig": {"mode": "AUTO"}}
    if tool_choice == "required":
        return {"functionCallingConfig": {"mode": "ANY"}}
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        fn_name = (tool_choice.get("function") or {}).get("name")
        cfg: Dict[str, Any] = {"mode": "ANY"}
        if fn_name:
            cfg["allowedFunctionNames"] = [fn_name]
        return {"functionCallingConfig": cfg}
    return None


def _openai_to_gemini_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a full OpenAI chat completion payload dict to Gemini request body.

    Supported mappings:
      messages            → contents + systemInstruction
      max_tokens          → generationConfig.maxOutputTokens
      temperature         → generationConfig.temperature
      top_p               → generationConfig.topP
      stop                → generationConfig.stopSequences
      tools               → tools[].functionDeclarations
      tool_choice         → toolConfig.functionCallingConfig

    OpenAI-only fields (frequency_penalty, n, presence_penalty, etc.)
    are silently ignored — no filtering needed in the caller.
    """
    messages = payload.get("messages") or []
    system_instruction, contents = _openai_messages_to_gemini(messages)

    body: Dict[str, Any] = {"contents": contents}

    if system_instruction:
        body["systemInstruction"] = system_instruction

    # generationConfig
    gen: Dict[str, Any] = {}
    if payload.get("max_tokens") is not None:
        gen["maxOutputTokens"] = payload["max_tokens"]
    if payload.get("temperature") is not None:
        gen["temperature"] = payload["temperature"]
    if payload.get("top_p") is not None:
        gen["topP"] = payload["top_p"]
    stop = payload.get("stop")
    if stop:
        gen["stopSequences"] = [stop] if isinstance(stop, str) else list(stop)
    if gen:
        body["generationConfig"] = gen

    # Tools
    gemini_tools = _openai_tools_to_gemini(payload.get("tools"))
    if gemini_tools:
        body["tools"] = gemini_tools

    tool_config = _openai_tool_choice_to_gemini(payload.get("tool_choice"))
    if tool_config:
        body["toolConfig"] = tool_config

    return body


# ---------------------------------------------------------------------------
# Response conversion: Gemini native → OpenAI format
# ---------------------------------------------------------------------------


def _map_finish_reason(reason: Optional[str]) -> Optional[str]:
    """Map a Gemini finishReason string to an OpenAI finish_reason string."""
    if not reason:
        return None
    return _FINISH_REASON_MAP.get(reason, "stop")


def _gemini_parts_to_openai(
    parts: List[Dict[str, Any]],
) -> Tuple[
    Optional[str],          # concatenated text (None if empty)
    Optional[List[Dict]],   # tool_calls list (None if absent)
    Optional[List[Dict]],   # image content parts (None if absent)
]:
    """
    Parse Gemini response parts into OpenAI-style (text, tool_calls, image_parts).

    - thought parts (internal reasoning) are skipped.
    - text parts are concatenated.
    - functionCall parts become OpenAI tool_calls.
    - inlineData parts become image_url content parts.
    """
    texts: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    image_parts: List[Dict[str, Any]] = []

    for part in parts:
        if part.get("thought"):
            continue  # skip internal reasoning tokens
        if "text" in part:
            texts.append(part["text"])
        elif "functionCall" in part:
            fc = part["functionCall"]
            tool_calls.append(
                {
                    "id": f"call_{uuid.uuid4().hex[:16]}",
                    "type": "function",
                    "function": {
                        "name": fc.get("name", ""),
                        "arguments": json.dumps(fc.get("args") or {}),
                    },
                }
            )
        elif "inlineData" in part:
            d = part["inlineData"]
            mime = d.get("mimeType", "image/png")
            data = d.get("data", "")
            image_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{data}"},
                }
            )

    return (
        "".join(texts) if texts else None,
        tool_calls or None,
        image_parts or None,
    )


def _build_usage(usage_meta: Dict[str, Any]) -> Dict[str, Any]:
    """Build an OpenAI usage dict from a Gemini usageMetadata object."""
    prompt = usage_meta.get("promptTokenCount", 0)
    completion = usage_meta.get("candidatesTokenCount", 0)
    total = usage_meta.get("totalTokenCount", prompt + completion)
    cached = usage_meta.get("cachedContentTokenCount", 0)
    usage: Dict[str, Any] = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }
    if cached:
        usage["prompt_tokens_details"] = {"cached_tokens": cached}
    return usage


def _gemini_response_to_openai(
    native_resp: Dict[str, Any],
    model: str,
    request_id: str,
) -> Dict[str, Any]:
    """Convert a full Gemini GenerateContentResponse to OpenAI format."""
    candidates = native_resp.get("candidates") or []
    usage_meta = native_resp.get("usageMetadata") or {}

    choices = []
    for i, candidate in enumerate(candidates):
        parts = (candidate.get("content") or {}).get("parts") or []
        finish_reason_raw = candidate.get("finishReason")

        text, tool_calls, image_parts = _gemini_parts_to_openai(parts)

        # Build message content
        if image_parts:
            # Mixed: text + images as content array
            msg_content: Any = []
            if text:
                msg_content.append({"type": "text", "text": text})
            msg_content.extend(image_parts)
        elif tool_calls:
            msg_content = None  # OpenAI spec: null content when tool_calls present
        else:
            msg_content = text if text is not None else ""

        # Override finish_reason for tool calls
        if tool_calls and finish_reason_raw == "STOP":
            finish_reason = "tool_calls"
        else:
            finish_reason = _map_finish_reason(finish_reason_raw)

        message: Dict[str, Any] = {"role": "assistant", "content": msg_content}
        if tool_calls:
            message["tool_calls"] = tool_calls

        choices.append(
            {"index": i, "message": message, "finish_reason": finish_reason}
        )

    return {
        "id": request_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": choices,
        "usage": _build_usage(usage_meta),
    }


def _gemini_chunk_to_sse(
    chunk_data: Dict[str, Any],
    model: str,
    chunk_id: str,
    created: int,
) -> str:
    """
    Convert one parsed Gemini SSE chunk to OpenAI SSE line(s).
    Returns an empty string if there is nothing to emit.
    """
    candidates = chunk_data.get("candidates") or []
    usage_meta = chunk_data.get("usageMetadata") or {}
    out: List[str] = []

    for i, candidate in enumerate(candidates):
        parts = (candidate.get("content") or {}).get("parts") or []
        finish_reason_raw = candidate.get("finishReason") or None

        text, tool_calls, image_parts = _gemini_parts_to_openai(parts)

        delta: Dict[str, Any] = {}
        if image_parts:
            content_list: List[Any] = []
            if text:
                content_list.append({"type": "text", "text": text})
            content_list.extend(image_parts)
            delta["content"] = content_list
        elif tool_calls:
            delta["tool_calls"] = [
                {
                    "index": j,
                    "id": tc["id"],
                    "type": "function",
                    "function": tc["function"],
                }
                for j, tc in enumerate(tool_calls)
            ]
        elif text is not None:
            delta["content"] = text

        if tool_calls and finish_reason_raw == "STOP":
            finish_reason: Optional[str] = "tool_calls"
        else:
            finish_reason = _map_finish_reason(finish_reason_raw)

        chunk_obj: Dict[str, Any] = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {"index": i, "delta": delta, "finish_reason": finish_reason}
            ],
        }

        # Include usage on the final chunk (when totalTokenCount is available)
        if usage_meta.get("totalTokenCount"):
            chunk_obj["usage"] = _build_usage(usage_meta)

        out.append(f"data: {json.dumps(chunk_obj)}\n\n")

    return "".join(out)


# ---------------------------------------------------------------------------
# Cached-token helpers
# (operate on already-converted OpenAI-format dicts, unchanged by callers)
# ---------------------------------------------------------------------------


def extract_cached_tokens(response: dict) -> int:
    """
    Extract cached token count from an OpenAI-format response dict.

    Looks for usage.prompt_tokens_details.cached_tokens
    (set by _build_usage when cachedContentTokenCount > 0).
    """
    usage = response.get("usage", {})
    details = usage.get("prompt_tokens_details")
    if not details:
        return 0
    if isinstance(details, list):
        for item in details:
            if isinstance(item, dict) and "cached_tokens" in item:
                return int(item["cached_tokens"])
    elif isinstance(details, dict):
        return int(details.get("cached_tokens", 0))
    return 0


def extract_cached_tokens_from_chunk(data: dict) -> Optional[int]:
    """
    Extract cached token count from a streaming chunk's usage field.
    Returns None if no usage data is present in this chunk.
    """
    usage = data.get("usage")
    if not usage:
        return None
    return extract_cached_tokens({"usage": usage})


# ---------------------------------------------------------------------------
# GeminiClient
# ---------------------------------------------------------------------------


class GeminiClient:
    """Client for Google Gemini native generateContent API."""

    @classmethod
    async def list_models(cls, api_key: str) -> List[Dict]:
        """
        Fetch available Gemini models from Google API.

        Filters to Gemini 2+ models that support generateContent.
        Returns list in same format as Bedrock models for UI compatibility.
        """
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models"
            f"?key={api_key}&pageSize=100"
        )
        models = []

        async with httpx.AsyncClient(timeout=30) as client:
            while url:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()

                for model in data.get("models", []):
                    name = model.get("name", "")  # e.g. "models/gemini-2.5-pro"

                    m = re.match(r"models/gemini-([0-9]+)", name)
                    if not m or int(m.group(1)) < 2:
                        continue

                    supported_methods = model.get("supportedGenerationMethods", [])
                    if "generateContent" not in supported_methods:
                        continue

                    model_id = name[len("models/"):]
                    if any(kw in model_id for kw in ("embed", "aqa", "retrieval")):
                        continue

                    display_name = model.get("displayName", "")
                    friendly_name = _make_friendly_name(model_id, display_name)
                    models.append(
                        {
                            "model_id": model_id,
                            "model_name": friendly_name,
                            "friendly_name": friendly_name,
                            "provider": "google",
                            "is_cross_region": False,
                            "cross_region_type": None,
                            "streaming_supported": True,
                        }
                    )

                next_token = data.get("nextPageToken")
                url = (
                    f"https://generativelanguage.googleapis.com/v1beta/models"
                    f"?key={api_key}&pageSize=100&pageToken={next_token}"
                    if next_token
                    else None
                )

        models.sort(key=lambda m: m["model_id"])
        logger.info(f"Fetched {len(models)} Gemini models from Google API")
        return models

    @classmethod
    async def invoke(
        cls,
        payload: dict,
        api_key: str,
    ) -> dict:
        """
        Non-streaming request to Gemini native :generateContent endpoint.

        Converts OpenAI-format payload → Gemini GenerateContentRequest,
        calls the API, converts the response back to OpenAI format,
        and returns it as a plain dict.
        """
        model = payload.get("model", "")
        model_id = model.removeprefix("models/")
        url = f"{GEMINI_BASE_URL}/{model_id}:generateContent?key={api_key}"

        gemini_body = _openai_to_gemini_payload(payload)
        request_id = f"chatcmpl-{uuid.uuid4().hex}"

        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                url,
                headers={"Content-Type": "application/json"},
                json=gemini_body,
            )

        if resp.status_code != 200:
            logger.error(
                f"Gemini API error: status={resp.status_code}, body={resp.text[:500]}"
            )
            raise httpx.HTTPStatusError(
                f"Gemini API returned {resp.status_code}: {resp.text[:200]}",
                request=resp.request,
                response=resp,
            )

        return _gemini_response_to_openai(resp.json(), model, request_id)

    @classmethod
    async def invoke_stream(
        cls,
        payload: dict,
        api_key: str,
    ) -> AsyncGenerator[str, None]:
        """
        Streaming request to Gemini native :streamGenerateContent endpoint.

        Converts OpenAI-format payload → Gemini GenerateContentRequest,
        streams via :streamGenerateContent?alt=sse, converts each chunk to
        OpenAI SSE format, and yields raw SSE text (including final [DONE]).
        """
        model = payload.get("model", "")
        model_id = model.removeprefix("models/")
        url = (
            f"{GEMINI_BASE_URL}/{model_id}:streamGenerateContent"
            f"?alt=sse&key={api_key}"
        )

        gemini_body = _openai_to_gemini_payload(payload)
        chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())

        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST",
                url,
                headers={"Content-Type": "application/json"},
                json=gemini_body,
            ) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    raise httpx.HTTPStatusError(
                        f"Gemini stream error {resp.status_code}: "
                        f"{error_body[:200].decode(errors='replace')}",
                        request=resp.request,
                        response=resp,
                    )

                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    json_str = line[6:]
                    try:
                        chunk_data = json.loads(json_str)
                    except json.JSONDecodeError:
                        continue
                    sse = _gemini_chunk_to_sse(chunk_data, model, chunk_id, created)
                    if sse:
                        yield sse

        yield "data: [DONE]\n\n"

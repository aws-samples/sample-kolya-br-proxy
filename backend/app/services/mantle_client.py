"""
OpenAI-on-Bedrock (mantle) API client service.

GPT-5.5 / GPT-5.4 are served by AWS's "mantle" inference engine through the
**OpenAI Responses API** (``https://bedrock-mantle.{region}.api.aws/openai/v1``
→ ``/responses``), not through the boto3 ``converse`` / ``invoke_model`` paths.

This client mirrors ``gemini_client.py``: it converts OpenAI ChatCompletions
requests to the Responses API format and the responses back, so the rest of the
pipeline (chat.py, usage recording, pricing) stays unchanged.

Auth is SigV4 over the existing AWS credential chain (reused from BedrockClient's
aioboto3 session — IRSA/STS on EKS, static keys / profile locally), so no new
secret or bearer token is introduced.
"""

import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

from app.core.config import get_settings
from app.services.mantle_models import MANTLE_BASE_URL, resolve_mantle_region

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SigV4 signing
# ---------------------------------------------------------------------------


async def _signed_headers(
    method: str, url: str, body_bytes: bytes, region: str
) -> Dict[str, str]:
    """Return SigV4-signed headers for a mantle request.

    Credentials come from the shared BedrockClient aioboto3 session (reuses the
    EKS Pod IRSA/STS chain, including a SessionToken → ``X-Amz-Security-Token``).
    In aiobotocore both ``get_credentials`` and ``get_frozen_credentials`` are
    coroutines and must be awaited (unlike sync botocore).

    The signature is computed over the EXACT *body_bytes* that will be sent.
    """
    from app.services.bedrock import BedrockClient

    session = BedrockClient.get_instance().session
    creds = await session.get_credentials()
    if creds is None:
        raise RuntimeError("No AWS credentials available to sign mantle request")
    frozen = await creds.get_frozen_credentials()

    service = get_settings().MANTLE_SIGV4_SERVICE
    aws_req = AWSRequest(
        method=method,
        url=url,
        data=body_bytes,
        headers={"Content-Type": "application/json"},
    )
    SigV4Auth(frozen, service, region).add_auth(aws_req)
    return dict(aws_req.headers)


# ---------------------------------------------------------------------------
# Request conversion: OpenAI ChatCompletions → OpenAI Responses
# ---------------------------------------------------------------------------


def _content_part_to_responses(part: Dict[str, Any]) -> Dict[str, Any]:
    """Convert one OpenAI ContentPart dict to a Responses API input part."""
    ptype = part.get("type")
    if ptype == "text":
        return {"type": "input_text", "text": part.get("text", "")}
    if ptype == "image_url":
        url = (part.get("image_url") or {}).get("url", "")
        # Responses API takes the data-URL / URL directly on input_image.
        return {"type": "input_image", "image_url": url}
    # Unknown type — best-effort text fallback
    return {"type": "input_text", "text": str(part.get("text", ""))}


def _msg_content_to_input_parts(content: Any, output: bool) -> List[Dict[str, Any]]:
    """Convert an OpenAI message content value (str or list) to Responses parts.

    *output* selects the text part type: assistant turns use ``output_text``,
    everything else uses ``input_text``.
    """
    text_type = "output_text" if output else "input_text"
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": text_type, "text": content}] if content else []
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict):
                # Assistant text parts must use output_text in the Responses API.
                if output and p.get("type") == "text":
                    parts.append({"type": "output_text", "text": p.get("text", "")})
                else:
                    parts.append(_content_part_to_responses(p))
        return parts
    return [{"type": text_type, "text": str(content)}]


def _openai_messages_to_input(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Convert an OpenAI messages array to a Responses API ``input`` list.

    Roles:
      system     → message with role "developer"
      user       → message with role "user"
      assistant  → message with role "assistant" (tool_calls → function_call items)
      tool       → function_call_output item (keyed by call_id)
    """
    input_items: List[Dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")
        tool_calls = msg.get("tool_calls")

        # ── tool result ─────────────────────────────────────────────────────
        if role == "tool":
            raw = content or ""
            output_str = raw if isinstance(raw, str) else json.dumps(raw)
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": msg.get("tool_call_id", ""),
                    "output": output_str,
                }
            )
            continue

        # ── system → developer ──────────────────────────────────────────────
        if role == "system":
            parts = _msg_content_to_input_parts(content, output=False)
            if parts:
                input_items.append({"role": "developer", "content": parts})
            continue

        # ── user / assistant ─────────────────────────────────────────────────
        is_assistant = role == "assistant"
        parts = _msg_content_to_input_parts(content, output=is_assistant)
        if parts:
            input_items.append(
                {"role": "assistant" if is_assistant else "user", "content": parts}
            )

        # Assistant tool calls → function_call items
        for tc in tool_calls or []:
            fn = tc.get("function") or {}
            input_items.append(
                {
                    "type": "function_call",
                    "call_id": tc.get("id", ""),
                    "name": fn.get("name", ""),
                    "arguments": fn.get("arguments", "{}"),
                }
            )

    return input_items


def _openai_tools_to_responses(
    tools: Optional[List[Dict[str, Any]]],
) -> Optional[List[Dict[str, Any]]]:
    """Convert OpenAI ChatCompletions tools to Responses API tools.

    Responses flattens the function spec (name/description/parameters live at the
    top level of the tool, not nested under a ``function`` key).
    """
    if not tools:
        return None
    out = []
    for tool in tools:
        if tool.get("type") == "function":
            fn = tool.get("function") or {}
            decl: Dict[str, Any] = {"type": "function", "name": fn.get("name", "")}
            if fn.get("description"):
                decl["description"] = fn["description"]
            if fn.get("parameters"):
                decl["parameters"] = fn["parameters"]
            out.append(decl)
    return out or None


def _openai_response_format_to_text_format(
    response_format: Any,
) -> Optional[Dict[str, Any]]:
    """Convert OpenAI ``response_format`` to a Responses API ``text.format`` value.

    OpenAI ChatCompletions nests the JSON schema under ``json_schema`` with the
    spec inside; the Responses API flattens ``name``/``schema``/``strict`` to the
    top level of ``text.format``.

      {"type": "text"}                       → {"type": "text"}
      {"type": "json_object"}                → {"type": "json_object"}
      {"type": "json_schema",
       "json_schema": {"name", "schema", "strict"}}
                                             → {"type": "json_schema",
                                                "name", "schema", "strict"}
    """
    if not isinstance(response_format, dict):
        return None
    rf_type = response_format.get("type")
    if rf_type in ("text", "json_object"):
        return {"type": rf_type}
    if rf_type == "json_schema":
        js = response_format.get("json_schema") or {}
        fmt: Dict[str, Any] = {"type": "json_schema"}
        if js.get("name"):
            fmt["name"] = js["name"]
        if js.get("schema") is not None:
            fmt["schema"] = js["schema"]
        if js.get("description"):
            fmt["description"] = js["description"]
        if js.get("strict") is not None:
            fmt["strict"] = js["strict"]
        return fmt
    return None


def _openai_tool_choice_to_responses(tool_choice: Any) -> Optional[Any]:
    """Convert OpenAI tool_choice to a Responses API tool_choice value."""
    if tool_choice is None:
        return None
    if tool_choice in ("none", "auto", "required"):
        return tool_choice
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        fn_name = (tool_choice.get("function") or {}).get("name")
        if fn_name:
            return {"type": "function", "name": fn_name}
    return None


_REASONING_MODEL_PATTERNS = ("gpt-5.6", "gpt-5.5", "o1", "o3", "o4")


def _is_reasoning_model(model: str) -> bool:
    return any(pat in model for pat in _REASONING_MODEL_PATTERNS)


def _openai_to_responses(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a full OpenAI chat completion payload to a Responses request body.

    Mappings:
      model               → model
      messages            → input  (system → developer role)
      max_tokens          → max_output_tokens
      temperature         → temperature
      top_p               → top_p
      tools               → tools  (flattened function spec)
      tool_choice         → tool_choice
      reasoning.effort    ← bedrock_additional_model_request_fields.reasoning.effort
                            (no new schema field; reuse the existing passthrough)

    OpenAI-only fields (frequency_penalty, n, presence_penalty, etc.) are
    silently ignored.
    """
    messages = payload.get("messages") or []
    body: Dict[str, Any] = {
        "model": payload.get("model", ""),
        "input": _openai_messages_to_input(messages),
    }

    if payload.get("max_tokens") is not None:
        body["max_output_tokens"] = payload["max_tokens"]
    is_reasoning = _is_reasoning_model(body["model"])
    if not is_reasoning and payload.get("temperature") is not None:
        body["temperature"] = payload["temperature"]
    if not is_reasoning and payload.get("top_p") is not None:
        body["top_p"] = payload["top_p"]

    tools = _openai_tools_to_responses(payload.get("tools"))
    if tools:
        body["tools"] = tools
    tool_choice = _openai_tool_choice_to_responses(payload.get("tool_choice"))
    if tool_choice is not None:
        body["tool_choice"] = tool_choice

    # response_format → text.format (structured / JSON output)
    text_format = _openai_response_format_to_text_format(payload.get("response_format"))
    if text_format is not None:
        body["text"] = {"format": text_format}

    # reasoning_effort: standard OpenAI field, or via bedrock_additional_model_request_fields
    effort = payload.get("reasoning_effort")
    if not effort:
        extra = payload.get("bedrock_additional_model_request_fields") or {}
        reasoning = extra.get("reasoning")
        if isinstance(reasoning, dict):
            effort = reasoning.get("effort")
    if effort:
        body["reasoning"] = {"effort": effort}

    return body


# ---------------------------------------------------------------------------
# Response conversion: OpenAI Responses → OpenAI ChatCompletions
# ---------------------------------------------------------------------------


def _build_usage(usage: Dict[str, Any]) -> Dict[str, Any]:
    """Build an OpenAI ChatCompletions usage dict from a Responses usage object."""
    prompt = usage.get("input_tokens", 0)
    completion = usage.get("output_tokens", 0)
    total = usage.get("total_tokens", prompt + completion)
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
    out: Dict[str, Any] = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }
    if cached:
        out["prompt_tokens_details"] = {"cached_tokens": cached}
    return out


def _output_to_message(
    output: List[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[List[Dict]]]:
    """Parse a Responses ``output`` array into (text, tool_calls).

    ``reasoning`` items are skipped; ``message`` items contribute output_text;
    ``function_call`` items become OpenAI tool_calls.
    """
    texts: List[str] = []
    tool_calls: List[Dict[str, Any]] = []

    for item in output:
        itype = item.get("type")
        if itype == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text":
                    texts.append(part.get("text", ""))
        elif itype == "function_call":
            tool_calls.append(
                {
                    "id": item.get("call_id") or f"call_{uuid.uuid4().hex[:16]}",
                    "type": "function",
                    "function": {
                        "name": item.get("name", ""),
                        "arguments": item.get("arguments", "{}"),
                    },
                }
            )
        # reasoning / other item types are intentionally ignored

    return ("".join(texts) if texts else None, tool_calls or None)


def _responses_to_openai(
    resp: Dict[str, Any], model: str, request_id: str
) -> Dict[str, Any]:
    """Convert a full Responses API response to OpenAI ChatCompletions format."""
    output = resp.get("output") or []
    text, tool_calls = _output_to_message(output)

    if tool_calls:
        msg_content: Any = None  # OpenAI spec: null content when tool_calls present
        finish_reason = "tool_calls"
    else:
        msg_content = text if text is not None else ""
        finish_reason = "length" if resp.get("status") == "incomplete" else "stop"

    message: Dict[str, Any] = {"role": "assistant", "content": msg_content}
    if tool_calls:
        message["tool_calls"] = tool_calls

    return {
        "id": request_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": _build_usage(resp.get("usage") or {}),
    }


# ---------------------------------------------------------------------------
# Cached-token helpers (operate on already-converted OpenAI-format dicts)
# ---------------------------------------------------------------------------


def extract_cached_tokens(response: dict) -> int:
    """Extract cached token count from an OpenAI-format response dict."""
    usage = response.get("usage", {})
    details = usage.get("prompt_tokens_details")
    if not details:
        return 0
    if isinstance(details, dict):
        return int(details.get("cached_tokens", 0))
    if isinstance(details, list):
        for item in details:
            if isinstance(item, dict) and "cached_tokens" in item:
                return int(item["cached_tokens"])
    return 0


def extract_cached_tokens_from_chunk(data: dict) -> Optional[int]:
    """Extract cached token count from a streaming chunk's usage field."""
    usage = data.get("usage")
    if not usage:
        return None
    return extract_cached_tokens({"usage": usage})


# ---------------------------------------------------------------------------
# MantleClient
# ---------------------------------------------------------------------------


class MantleClient:
    """Client for the OpenAI Responses API served by AWS mantle (GPT-5.5/5.4)."""

    @staticmethod
    def _endpoint(model: str) -> Tuple[str, str]:
        """Return (url, region) for the /responses endpoint of *model*."""
        region = resolve_mantle_region(model)
        base = MANTLE_BASE_URL.format(region=region)
        return f"{base}/responses", region

    # ------------------------------------------------------------------
    # Native Responses API passthrough (no protocol conversion)
    #
    # These methods forward a native OpenAI Responses request body to mantle
    # verbatim and return the native response. Unlike invoke()/invoke_stream(),
    # which translate to/from ChatCompletions, the passthrough preserves every
    # Responses-only feature (built-in tools, multimodal output, etc.) so the
    # /v1/responses endpoint exposes mantle's full capability surface.
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_unsupported_params(body: dict) -> dict:
        """Remove parameters not supported by reasoning models."""
        model = body.get("model", "")
        if _is_reasoning_model(model):
            for key in (
                "temperature",
                "top_p",
                "frequency_penalty",
                "presence_penalty",
            ):
                body.pop(key, None)
        return body

    @classmethod
    async def responses_passthrough(cls, body: dict) -> dict:
        """Non-streaming native Responses request — body forwarded verbatim."""
        model = body.get("model", "")
        url, region = cls._endpoint(model)
        send_body = dict(body)
        send_body["stream"] = False
        cls._strip_unsupported_params(send_body)
        body_bytes = json.dumps(send_body).encode("utf-8")
        headers = await _signed_headers("POST", url, body_bytes, region)

        async with httpx.AsyncClient(timeout=3600) as client:
            resp = await client.post(url, headers=headers, content=body_bytes)

        if resp.status_code != 200:
            logger.error(
                f"mantle Responses error: status={resp.status_code}, "
                f"region={region}, body={resp.text[:500]}"
            )
            raise httpx.HTTPStatusError(
                f"mantle API returned {resp.status_code}: {resp.text[:200]}",
                request=resp.request,
                response=resp,
            )

        return resp.json()

    @classmethod
    async def responses_passthrough_stream(
        cls, body: dict
    ) -> AsyncGenerator[bytes, None]:
        """Streaming native Responses request — raw SSE bytes forwarded verbatim.

        Yields the upstream SSE stream unchanged so the client receives mantle's
        native Responses events. Usage for billing is extracted by the caller
        from the ``response.completed`` / ``response.incomplete`` events.
        """
        model = body.get("model", "")
        url, region = cls._endpoint(model)
        send_body = dict(body)
        send_body["stream"] = True
        cls._strip_unsupported_params(send_body)
        body_bytes = json.dumps(send_body).encode("utf-8")
        headers = await _signed_headers("POST", url, body_bytes, region)
        headers["Accept"] = "text/event-stream"

        async with httpx.AsyncClient(timeout=3600) as client:
            async with client.stream(
                "POST", url, headers=headers, content=body_bytes
            ) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    raise httpx.HTTPStatusError(
                        f"mantle stream error {resp.status_code}: "
                        f"{error_body[:200].decode(errors='replace')}",
                        request=resp.request,
                        response=resp,
                    )
                async for raw in resp.aiter_raw():
                    if raw:
                        yield raw

    @classmethod
    async def invoke(cls, payload: dict) -> dict:
        """Non-streaming request to the mantle /responses endpoint."""
        model = payload.get("model", "")
        url, region = cls._endpoint(model)
        body = _openai_to_responses(payload)
        body["stream"] = False
        body_bytes = json.dumps(body).encode("utf-8")
        headers = await _signed_headers("POST", url, body_bytes, region)
        request_id = f"chatcmpl-{uuid.uuid4().hex}"

        async with httpx.AsyncClient(timeout=3600) as client:
            resp = await client.post(url, headers=headers, content=body_bytes)

        if resp.status_code != 200:
            logger.error(
                f"mantle API error: status={resp.status_code}, "
                f"region={region}, body={resp.text[:500]}"
            )
            raise httpx.HTTPStatusError(
                f"mantle API returned {resp.status_code}: {resp.text[:200]}",
                request=resp.request,
                response=resp,
            )

        return _responses_to_openai(resp.json(), model, request_id)

    @classmethod
    async def invoke_stream(cls, payload: dict) -> AsyncGenerator[str, None]:
        """Streaming request to the mantle /responses endpoint.

        The Responses API streams *named* SSE events. We translate:
          response.output_text.delta            → content delta
          response.function_call_arguments.delta → tool_call argument delta
          response.output_item.added (func call) → tool_call opener (id + name)
          response.completed                     → usage + final stop
        into OpenAI chat.completion.chunk SSE lines.
        """
        model = payload.get("model", "")
        url, region = cls._endpoint(model)
        body = _openai_to_responses(payload)
        body["stream"] = True
        body_bytes = json.dumps(body).encode("utf-8")
        headers = await _signed_headers("POST", url, body_bytes, region)
        headers["Accept"] = "text/event-stream"

        chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        # Map Responses output_index → OpenAI tool_call index (function calls only)
        tool_call_index: Dict[int, int] = {}

        def _chunk(delta: Dict[str, Any], finish: Optional[str], usage=None) -> str:
            obj: Dict[str, Any] = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            if usage is not None:
                obj["usage"] = usage
            return f"data: {json.dumps(obj)}\n\n"

        async with httpx.AsyncClient(timeout=3600) as client:
            async with client.stream(
                "POST", url, headers=headers, content=body_bytes
            ) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    raise httpx.HTTPStatusError(
                        f"mantle stream error {resp.status_code}: "
                        f"{error_body[:200].decode(errors='replace')}",
                        request=resp.request,
                        response=resp,
                    )

                event_name: Optional[str] = None
                async for line in resp.aiter_lines():
                    if not line:
                        event_name = None
                        continue
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    etype = event.get("type") or event_name

                    if etype == "response.output_text.delta":
                        delta_text = event.get("delta", "")
                        if delta_text:
                            yield _chunk({"content": delta_text}, None)

                    elif etype == "response.output_item.added":
                        item = event.get("item") or {}
                        if item.get("type") == "function_call":
                            oidx = event.get("output_index", 0)
                            tc_idx = len(tool_call_index)
                            tool_call_index[oidx] = tc_idx
                            yield _chunk(
                                {
                                    "tool_calls": [
                                        {
                                            "index": tc_idx,
                                            "id": item.get("call_id")
                                            or f"call_{uuid.uuid4().hex[:16]}",
                                            "type": "function",
                                            "function": {
                                                "name": item.get("name", ""),
                                                "arguments": "",
                                            },
                                        }
                                    ]
                                },
                                None,
                            )

                    elif etype == "response.function_call_arguments.delta":
                        oidx = event.get("output_index", 0)
                        tc_idx = tool_call_index.get(oidx, 0)
                        yield _chunk(
                            {
                                "tool_calls": [
                                    {
                                        "index": tc_idx,
                                        "function": {
                                            "arguments": event.get("delta", "")
                                        },
                                    }
                                ]
                            },
                            None,
                        )

                    elif etype in ("response.completed", "response.incomplete"):
                        resp_obj = event.get("response") or {}
                        usage = _build_usage(resp_obj.get("usage") or {})
                        finish = (
                            "tool_calls"
                            if tool_call_index
                            else (
                                "length" if etype == "response.incomplete" else "stop"
                            )
                        )
                        yield _chunk({}, finish, usage=usage)

                    elif etype == "response.failed" or etype == "error":
                        resp_obj = event.get("response") or {}
                        err = resp_obj.get("error") or event.get("error") or {}
                        logger.error(f"mantle stream failed: {err}")
                        yield _chunk({}, "stop")

        yield "data: [DONE]\n\n"

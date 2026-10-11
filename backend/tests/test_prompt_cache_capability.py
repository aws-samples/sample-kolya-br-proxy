"""Explicit cache markers are validated against the exact model's capability.

A marker the model cannot honour must fail with a clear client error instead of
being silently dropped or sent upstream as an unsupported breakpoint.
"""

import pytest

from app.services.mantle_client import (
    _openai_to_responses,
    validate_native_responses_cache,
    validate_responses_cache_markers,
)

MARKER = {"type": "ephemeral"}


def _chat_payload(model, *parts):
    return {"model": model, "messages": [{"role": "user", "content": list(parts)}]}


def _text(marked=True):
    part = {"type": "text", "text": "shared prefix"}
    if marked:
        part["cache_control"] = MARKER
    return part


def _image(marked=True):
    part = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}
    if marked:
        part["cache_control"] = MARKER
    return part


@pytest.mark.parametrize(
    "model",
    [
        "openai.gpt-5.6-sol",
        "global.openai.gpt-5.6-terra",
        "openai.gpt-6-sol",
        "us.openai.gpt-6-luna",
        "global.openai.gpt-6.1-sol",
    ],
)
def test_text_breakpoints_are_preserved_for_explicit_cache_models(model):
    body = _openai_to_responses(_chat_payload(model, _text()))

    assert body["prompt_cache_options"] == {"mode": "explicit"}
    assert body["input"][0]["content"][0]["prompt_cache_breakpoint"] == {
        "mode": "explicit"
    }


def test_image_breakpoint_is_allowed_where_the_model_supports_it():
    body = _openai_to_responses(_chat_payload("us.openai.gpt-5.6-sol", _image()))

    assert body["input"][0]["content"][0]["type"] == "input_image"
    assert "prompt_cache_breakpoint" in body["input"][0]["content"][0]


@pytest.mark.parametrize(
    "model",
    [
        "openai.gpt-6-sol",
        "global.openai.gpt-6.1-sol",
        "us.openai.gpt-6-luna",
        "global.openai.gpt-6-astra",
    ],
)
def test_image_breakpoint_is_allowed_for_gpt6_models(model):
    body = _openai_to_responses(_chat_payload(model, _image()))

    assert body["input"][0]["content"][0]["type"] == "input_image"
    assert body["prompt_cache_options"] == {"mode": "explicit"}


@pytest.mark.parametrize("model", ["openai.gpt-5.4", "openai.gpt-5.5"])
def test_any_breakpoint_is_rejected_for_models_without_explicit_cache(model):
    with pytest.raises(ValueError, match="does not support explicit prompt caching"):
        validate_responses_cache_markers(_chat_payload(model, _text()))


def test_unmarked_requests_remain_valid_everywhere():
    for model in ("openai.gpt-5.4", "us.openai.gpt-6-astra", "openai.gpt-6-sol"):
        validate_responses_cache_markers(
            _chat_payload(model, _text(marked=False), _image(marked=False))
        )


def _native_body(model, *parts, mode=None):
    body = {
        "model": model,
        "input": [{"type": "message", "role": "user", "content": list(parts)}],
    }
    if mode:
        body["prompt_cache_options"] = {"mode": mode}
    return body


BREAKPOINT = {"mode": "explicit"}


def test_native_responses_text_breakpoint_is_accepted():
    validate_native_responses_cache(
        _native_body(
            "global.openai.gpt-6-sol",
            {"type": "input_text", "text": "p", "prompt_cache_breakpoint": BREAKPOINT},
            mode="explicit",
        )
    )


def test_native_responses_rejects_unsupported_breakpoint_type():
    with pytest.raises(ValueError, match="input_file"):
        validate_native_responses_cache(
            _native_body(
                "us.openai.gpt-6.1-sol",
                {
                    "type": "input_file",
                    "file_id": "file-1",
                    "prompt_cache_breakpoint": BREAKPOINT,
                },
            )
        )


def test_native_responses_rejects_explicit_mode_without_capability():
    with pytest.raises(ValueError, match="does not support explicit prompt caching"):
        validate_native_responses_cache(
            _native_body(
                "openai.gpt-5.5", {"type": "input_text", "text": "p"}, mode="explicit"
            )
        )


def test_native_responses_rejects_more_than_four_breakpoints():
    parts = [
        {"type": "input_text", "text": str(i), "prompt_cache_breakpoint": BREAKPOINT}
        for i in range(5)
    ]
    with pytest.raises(ValueError, match="At most 4"):
        validate_native_responses_cache(_native_body("openai.gpt-6-sol", *parts))


def test_breakpoints_inside_tool_results_are_rejected():
    payload = {
        "model": "openai.gpt-6-sol",
        "messages": [
            {"role": "tool", "tool_call_id": "c1", "content": [_text()]},
        ],
    }
    with pytest.raises(ValueError, match="tool results"):
        validate_responses_cache_markers(payload)


def test_native_responses_checks_function_call_output_and_empty_markers():
    body = {
        "model": "openai.gpt-6-sol",
        "input": [
            {
                "type": "function_call_output",
                "call_id": "c1",
                "output": [
                    {
                        "type": "input_file",
                        "file_id": "file-1",
                        "prompt_cache_breakpoint": {},
                    }
                ],
            }
        ],
    }
    with pytest.raises(ValueError, match="input_file"):
        validate_native_responses_cache(body)


def test_validation_errors_are_client_safe_type():
    from app.services.mantle_client import PromptCacheValidationError

    with pytest.raises(PromptCacheValidationError):
        validate_responses_cache_markers(_chat_payload("openai.gpt-5.4", _text()))

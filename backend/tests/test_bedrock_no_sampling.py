"""Regression tests for sampling-param stripping in the Bedrock layer.

Some Bedrock models reject the ``temperature``/``top_p`` fields and return a
``ValidationException`` ("This model doesn't support the temperature field").
This covers both the Anthropic invoke_model whitelist and the non-Anthropic
Converse denylist (xAI Grok), so a request built for those models never carries
the offending params.
"""

import pytest

from app.schemas.bedrock import BedrockMessage, BedrockRequest
from app.services.bedrock import BedrockClient


def _request(temperature=0.7, top_p=0.9):
    return BedrockRequest(
        max_tokens=256,
        messages=[BedrockMessage(role="user", content="hi")],
        temperature=temperature,
        top_p=top_p,
    )


@pytest.mark.parametrize(
    ("model_id", "no_sampling"),
    [
        ("global.xai.grok-4.6", True),
        ("us.xai.grok-3", True),
        # Non-reasoning Converse models keep sampling support.
        ("us.amazon.nova-pro-v1:0", False),
        ("us.deepseek.r1-v1:0", False),
        # Anthropic whitelist behaviour is unchanged: 4.6 and earlier keep
        # sampling; post-4.6 models are stripped.
        ("us.anthropic.claude-3-5-sonnet-20241022-v2:0", False),
        ("global.anthropic.claude-opus-4-6", False),
        ("global.anthropic.claude-opus-4-8", True),
    ],
)
def test_is_no_sampling_model_classification(model_id, no_sampling):
    assert BedrockClient._is_no_sampling_model(model_id) is no_sampling


def test_converse_params_strip_temperature_and_top_p_for_grok():
    params = BedrockClient._build_converse_params(_request(), "global.xai.grok-4.6")
    inference = params["inferenceConfig"]
    assert "temperature" not in inference
    assert "topP" not in inference
    assert inference["maxTokens"] == 256


def test_converse_params_keep_sampling_for_regular_model():
    params = BedrockClient._build_converse_params(
        _request(), "us.amazon.nova-pro-v1:0"
    )
    inference = params["inferenceConfig"]
    assert inference["temperature"] == 0.7
    assert inference["topP"] == 0.9

"""Runtime-mutable OpenAI GPT backend override.

The override lives as process-local state seeded from system_configs at
startup; the getter falls back to the env default until set. These tests pin
the getter/setter contract and the pub/sub apply path used for cross-pod sync.
"""

import pytest

from app.core import runtime_config


@pytest.fixture(autouse=True)
def _reset_override():
    """Isolate the module-level override between tests."""
    runtime_config._openai_gpt_backend = None
    yield
    runtime_config._openai_gpt_backend = None


def test_getter_falls_back_to_env_default():
    # No override set → env default (mantle in the test env).
    assert runtime_config.get_openai_gpt_backend() == "mantle"


def test_set_and_get_override():
    assert runtime_config.set_openai_gpt_backend("runtime") == "runtime"
    assert runtime_config.get_openai_gpt_backend() == "runtime"


def test_set_normalizes_case():
    assert runtime_config.set_openai_gpt_backend("RUNTIME") == "runtime"
    assert runtime_config.get_openai_gpt_backend() == "runtime"


def test_set_rejects_invalid_value():
    with pytest.raises(ValueError):
        runtime_config.set_openai_gpt_backend("bedrock")
    # Override untouched after a rejected set.
    assert runtime_config.get_openai_gpt_backend() == "mantle"


def test_config_sync_applies_backend_from_peer():
    from app.core.config_sync import _apply_config

    _apply_config({"openai_gpt_backend": "runtime"})
    assert runtime_config.get_openai_gpt_backend() == "runtime"


def test_config_sync_ignores_bad_backend_from_peer():
    from app.core.config_sync import _apply_config

    runtime_config.set_openai_gpt_backend("runtime")
    _apply_config({"openai_gpt_backend": "nonsense"})
    # Bad peer value ignored — previous override preserved.
    assert runtime_config.get_openai_gpt_backend() == "runtime"

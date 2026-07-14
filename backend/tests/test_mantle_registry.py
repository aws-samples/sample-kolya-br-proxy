"""Tests for the mantle (OpenAI-on-Bedrock) model registry and discovery."""

import pytest

from app.services import mantle_models as mm


@pytest.fixture(autouse=True)
def _reset_discovered_layer():
    """Each test starts from the static seed only."""
    mm.set_discovered_mantle_models(None)
    yield
    mm.set_discovered_mantle_models(None)


class TestRegistryMerge:
    def test_static_seed_without_discovery(self):
        regions = mm.get_mantle_model_regions()
        assert regions == mm.MANTLE_MODEL_REGIONS

    def test_discovered_overrides_static_per_model(self):
        mm.set_discovered_mantle_models({"openai.gpt-5.6-sol": ["us-west-2"]})
        regions = mm.get_mantle_model_regions()
        assert regions["openai.gpt-5.6-sol"] == ["us-west-2"]
        # Static models absent from discovery are preserved
        assert regions["openai.gpt-5.5"] == mm.MANTLE_MODEL_REGIONS["openai.gpt-5.5"]

    def test_discovered_new_model_is_routable(self):
        mm.set_discovered_mantle_models({"openai.gpt-5.7": ["us-east-2"]})
        assert mm.is_openai_mantle_model("openai.gpt-5.7")
        assert mm.resolve_mantle_region("openai.gpt-5.7") == "us-east-2"

    def test_gpt_oss_never_matches(self):
        assert not mm.is_openai_mantle_model("openai.gpt-oss-120b")


class TestDisplayNames:
    @pytest.mark.parametrize(
        "model_id,expected",
        [
            ("openai.gpt-5.6-sol", "GPT-5.6 Sol"),
            ("openai.gpt-5.6-terra", "GPT-5.6 Terra"),
            ("openai.gpt-5.5", "GPT-5.5"),
            ("openai.gpt-5.4", "GPT-5.4"),
        ],
    )
    def test_display_name(self, model_id, expected):
        assert mm.mantle_display_name(model_id) == expected

    @pytest.mark.parametrize(
        "display_name,expected",
        [
            ("GPT-5.6 Sol", "openai.gpt-5.6-sol"),
            ("GPT-5.6 Luna", "openai.gpt-5.6-luna"),
            ("GPT-5.5", "openai.gpt-5.5"),
            ("GPT-9 Unknown", None),
        ],
    )
    def test_pricing_name_to_id(self, display_name, expected):
        assert mm.mantle_pricing_name_to_id(display_name) == expected

    def test_round_trip_for_all_registry_models(self):
        for model_id in mm.get_mantle_model_regions():
            name = mm.mantle_display_name(model_id)
            assert mm.mantle_pricing_name_to_id(name) == model_id


class TestRefreshRegistry:
    @pytest.mark.asyncio
    async def test_empty_discovery_keeps_previous_registry(self, monkeypatch):
        async def _no_models():
            return {}

        monkeypatch.setattr(mm, "discover_mantle_models", _no_models)
        registry = await mm.refresh_mantle_registry()
        assert registry == mm.MANTLE_MODEL_REGIONS

    @pytest.mark.asyncio
    async def test_discovery_result_is_applied(self, monkeypatch):
        async def _models():
            return {"openai.gpt-5.7": ["us-east-1", "us-east-2"]}

        monkeypatch.setattr(mm, "discover_mantle_models", _models)
        registry = await mm.refresh_mantle_registry()
        assert registry["openai.gpt-5.7"] == ["us-east-1", "us-east-2"]
        # Static seed still present
        assert "openai.gpt-5.5" in registry

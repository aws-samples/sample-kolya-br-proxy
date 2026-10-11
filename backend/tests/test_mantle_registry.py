"""Tests for the mantle (OpenAI-on-Bedrock) model registry and discovery."""

import pytest

from app.services import mantle_models as mm


@pytest.fixture(autouse=True)
def _reset_registry():
    """Each test starts from the static seed only."""
    mm._model_regions = mm.MANTLE_MODEL_REGIONS
    yield
    mm._model_regions = mm.MANTLE_MODEL_REGIONS


async def _refresh_with(monkeypatch, discovered):
    async def _fake_discover():
        return discovered

    monkeypatch.setattr(mm, "discover_mantle_models", _fake_discover)
    return await mm.refresh_mantle_registry()


class TestRegistryMerge:
    def test_static_seed_without_discovery(self):
        assert mm.get_mantle_model_regions() == mm.MANTLE_MODEL_REGIONS

    @pytest.mark.asyncio
    async def test_discovered_overrides_static_per_model(self, monkeypatch):
        registry = await _refresh_with(
            monkeypatch, {"openai.gpt-5.6-sol": ["us-west-2"]}
        )
        assert registry["openai.gpt-5.6-sol"] == ["us-west-2"]
        # Static models absent from discovery are preserved
        assert registry["openai.gpt-5.5"] == mm.MANTLE_MODEL_REGIONS["openai.gpt-5.5"]

    @pytest.mark.asyncio
    async def test_discovered_new_model_is_routable(self, monkeypatch):
        await _refresh_with(monkeypatch, {"openai.gpt-5.7": ["us-east-2"]})
        assert mm.is_openai_mantle_model("openai.gpt-5.7")
        assert mm.resolve_mantle_region("openai.gpt-5.7") == "us-east-2"

    @pytest.mark.asyncio
    async def test_empty_discovery_keeps_previous_registry(self, monkeypatch):
        registry = await _refresh_with(monkeypatch, {})
        assert registry == mm.MANTLE_MODEL_REGIONS

    def test_gpt_oss_never_matches(self):
        assert not mm.is_openai_mantle_model("openai.gpt-oss-120b")


class TestResolveModelId:
    def test_canonical_id_passes_through(self):
        assert (
            mm.resolve_mantle_model_id("openai.gpt-5.6-luna") == "openai.gpt-5.6-luna"
        )

    def test_bare_name_gets_prefixed(self):
        assert mm.resolve_mantle_model_id("gpt-5.6-luna") == "openai.gpt-5.6-luna"

    def test_unknown_model_returns_none(self):
        assert mm.resolve_mantle_model_id("gpt-4o") is None

    def test_bare_gpt_oss_not_resolved(self):
        # gpt-oss runs the converse path, not the Responses API — never mantle.
        assert mm.resolve_mantle_model_id("gpt-oss-120b") is None


class TestResolveResponsesModelId:
    @pytest.mark.parametrize(
        "model_id",
        ["us.openai.gpt-5.6-sol", "global.openai.gpt-5.6-sol"],
    )
    def test_runtime_profile_is_preserved(self, model_id):
        assert mm.resolve_responses_model_id(model_id) == model_id
        assert mm.is_openai_runtime_responses_model(model_id)
        assert not mm.is_openai_mantle_model(model_id)

    def test_canonical_and_bare_ids_still_resolve_to_mantle(self):
        assert (
            mm.resolve_responses_model_id("openai.gpt-5.6-sol") == "openai.gpt-5.6-sol"
        )
        assert mm.resolve_responses_model_id("gpt-5.6-sol") == "openai.gpt-5.6-sol"

    @pytest.mark.parametrize(
        "model_id",
        [
            "eu.openai.gpt-5.6-sol",
            "global.openai.gpt-5.5",  # GPT-5.5 is Mantle-only
            "us.openai.gpt-5.4",
            "global.openai.gpt-oss-120b",
            "global.openai.unknown",
        ],
    )
    def test_unsupported_profiles_are_not_responses_models(self, model_id):
        assert mm.resolve_responses_model_id(model_id) is None
        assert not mm.is_openai_runtime_responses_model(model_id)


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

    def test_display_name_override_wins(self, monkeypatch):
        monkeypatch.setitem(
            mm.MANTLE_DISPLAY_NAME_OVERRIDES, "openai.gpt-5.5", "Custom Name"
        )
        assert mm.mantle_display_name("openai.gpt-5.5") == "Custom Name"

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


class TestGrantScope:
    """Authorization never widens a grant's residency/price scope."""

    @pytest.mark.parametrize(
        ("target", "allowed", "expected"),
        [
            ("openai.gpt-6-sol", ["openai.gpt-6-sol"], "openai.gpt-6-sol"),
            # Canonical request + profile-only grant → served by that profile.
            (
                "openai.gpt-6-sol",
                ["global.openai.gpt-6-sol"],
                "global.openai.gpt-6-sol",
            ),
            ("openai.gpt-6-sol", ["us.openai.gpt-6-sol"], "us.openai.gpt-6-sol"),
            # Profiles require an exact grant.
            ("global.openai.gpt-6-sol", ["us.openai.gpt-6-sol"], None),
            ("us.openai.gpt-6-sol", ["openai.gpt-6-sol"], None),
            ("openai.gpt-6-sol", ["us.openai.gpt-6-luna"], None),
        ],
    )
    def test_select_granted_responses_model(self, target, allowed, expected):
        assert mm.select_granted_responses_model(target, allowed) == expected

    def test_every_catalogued_canonical_id_has_a_mantle_region(self):
        from app.services.openai_gpt_catalog import list_gpt_routes

        for route in list_gpt_routes():
            if route.endpoint_family == "mantle":
                assert route.model_id in mm.MANTLE_MODEL_REGIONS

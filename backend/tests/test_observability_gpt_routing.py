"""Settings no longer exposes a global GPT Mantle/Runtime switch."""

import json
from types import SimpleNamespace
from typing import cast

import pytest

from app.api.admin.endpoints import observability
from app.models.user import User

ADMIN = cast(User, SimpleNamespace())


@pytest.mark.asyncio
async def test_get_reports_automatic_gpt_routing():
    config = await observability.get_observability_config(current_user=ADMIN)

    assert config["openai_gpt_routing"] == "auto"
    assert "openai_gpt_backend" not in config


@pytest.mark.asyncio
async def test_put_rejects_the_removed_backend_switch():
    update = observability.ObservabilityUpdate(openai_gpt_backend="runtime")

    response = await observability.update_observability_config(
        update, current_user=ADMIN, db=SimpleNamespace()
    )

    assert response.status_code == 400
    body = json.loads(response.body)
    assert body["success"] is False
    assert "automatic" in body["error"]

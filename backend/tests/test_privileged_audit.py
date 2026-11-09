"""Privileged admin actions must leave an audit trail.

Checked statically: each handler's source must call the audit service.
Cheap, and it fails the moment someone adds a key/pricing/observability
path that skips the audit write.
"""

import inspect

import pytest

from app.api.admin.endpoints import models, observability, pricing, tokens
from app.models.audit_log import AuditAction

HANDLERS = {
    tokens.revoke_token: "API_TOKEN_REVOKED",
    tokens.get_plain_token: "API_KEY_VIEWED",
    tokens.export_keys_csv: "API_KEYS_EXPORTED",
    tokens.adjust_token_balance: "TOKEN_BALANCE_ADJUSTED",
    tokens.notify_token: "API_KEY_NOTIFIED",
    pricing.update_pricing: "PRICING_UPDATED",
    observability.update_observability_config: "OBSERVABILITY_UPDATED",
    models.add_model: "MODEL_UPDATED",
    models.delete_model: "MODEL_UPDATED",
}


@pytest.mark.parametrize("handler,action", HANDLERS.items(), ids=lambda x: getattr(x, "__name__", x))
def test_handler_writes_audit(handler, action):
    assert hasattr(AuditAction, action)
    assert f"AuditAction.{action}" in inspect.getsource(handler)


def test_migration_adds_every_new_action():
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).parent.parent
        / "alembic/versions/f3a4b5c6d7e8_add_privileged_action_audit.py"
    )
    spec = importlib.util.spec_from_file_location("mig", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    for name in mig._NEW:
        assert hasattr(AuditAction, name)

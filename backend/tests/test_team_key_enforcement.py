"""Backend enforcement for team-managed keys on the /tokens endpoints.

Team keys are provisioned and governed via the /teams dashboard. On /tokens
only prompt-cache settings (token_metadata) may be edited; money and lifecycle
operations — recharge, quota/alert/lifecycle edits, key emailing, deletion —
must be rejected server-side (not merely hidden in the UI). These tests call
the endpoint functions directly with `_is_team_key` patched.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, status

from app.api.admin.endpoints import tokens as tokens_module
from app.api.admin.endpoints.tokens import (
    AdjustBalanceRequest,
    NotifyKeyRequest,
    UpdateTokenRequest,
    adjust_token_balance,
    delete_token,
    notify_token,
    update_token,
)
from app.models.user import UserRole


def _super_admin():
    return SimpleNamespace(id=uuid.uuid4(), role=UserRole.SUPER_ADMIN, permissions=None)


def _token():
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="key",
        token_hash="hash",
        encrypted_token=None,
        token_metadata=None,
        notify_emails=[],
    )


def _token_service(token):
    svc = MagicMock()
    svc.get_token_by_id = AsyncMock(return_value=token)
    svc.delete_token = AsyncMock()
    svc.db = MagicMock()
    return svc


def _audit():
    return SimpleNamespace(log=AsyncMock())


@pytest.mark.asyncio
async def test_delete_team_key_forbidden():
    token = _token()
    svc = _token_service(token)
    with patch.object(tokens_module, "_is_team_key", AsyncMock(return_value=True)):
        with pytest.raises(HTTPException) as exc:
            await delete_token(
                token_id=str(token.id),
                current_user=_super_admin(),
                token_service=svc,
                audit_service=_audit(),
                db=MagicMock(),
            )
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    svc.delete_token.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_non_team_key_allowed():
    token = _token()
    svc = _token_service(token)
    with (
        patch.object(tokens_module, "_is_team_key", AsyncMock(return_value=False)),
        patch.object(tokens_module, "_invalidate_token_cache", AsyncMock()),
    ):
        result = await delete_token(
            token_id=str(token.id),
            current_user=_super_admin(),
            token_service=svc,
            audit_service=_audit(),
            db=MagicMock(),
        )
    assert result is None
    svc.delete_token.assert_awaited_once()


@pytest.mark.asyncio
async def test_adjust_team_key_forbidden():
    token = _token()
    svc = _token_service(token)
    with patch.object(tokens_module, "_is_team_key", AsyncMock(return_value=True)):
        with pytest.raises(HTTPException) as exc:
            await adjust_token_balance(
                token_id=str(token.id),
                request=AdjustBalanceRequest(amount="5.00"),
                current_user=_super_admin(),
                token_service=svc,
                db=MagicMock(),
            )
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_update_team_key_money_field_forbidden():
    token = _token()
    svc = _token_service(token)
    with patch.object(tokens_module, "_is_team_key", AsyncMock(return_value=True)):
        with pytest.raises(HTTPException) as exc:
            await update_token(
                token_id=str(token.id),
                request=UpdateTokenRequest(quota_usd="10.00"),
                current_user=_super_admin(),
                token_service=svc,
                audit_service=_audit(),
                db=MagicMock(),
            )
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_update_team_key_metadata_only_allowed():
    """A team key may still edit prompt-cache settings (token_metadata)."""
    token = _token()
    svc = _token_service(token)
    db = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    with (
        patch.object(tokens_module, "_is_team_key", AsyncMock(return_value=True)),
        patch.object(tokens_module, "validate_token_metadata"),
        patch.object(tokens_module, "_invalidate_token_cache", AsyncMock()),
        patch.object(
            tokens_module,
            "calculate_token_usage",
            AsyncMock(return_value=tokens_module.TokenUsageSummary(total="0.00")),
        ),
        patch.object(tokens_module, "build_token_response", return_value="ok"),
    ):
        result = await update_token(
            token_id=str(token.id),
            request=UpdateTokenRequest(token_metadata={"bedrock_auto_cache": True}),
            current_user=_super_admin(),
            token_service=svc,
            audit_service=_audit(),
            db=db,
        )
    assert result == "ok"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_notify_team_key_forbidden():
    token = _token()
    svc = _token_service(token)
    with patch.object(tokens_module, "_is_team_key", AsyncMock(return_value=True)):
        with pytest.raises(HTTPException) as exc:
            await notify_token(
                token_id=str(token.id),
                request=NotifyKeyRequest(emails=["a@example.com"]),
                current_user=_super_admin(),
                token_service=svc,
                audit_service=_audit(),
                db=MagicMock(),
            )
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN

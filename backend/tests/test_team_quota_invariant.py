"""Team membership must have exactly one quota source: allocated_usd."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.api.admin.endpoints.teams import BatchCreateMembersRequest
from app.services.data_management import DataManagementService
from app.services.team import TeamService


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_add_member_clears_all_standalone_quotas():
    db = AsyncMock()
    service = TeamService(db)
    team_id = uuid4()
    user_id = uuid4()
    token = SimpleNamespace(
        id=uuid4(),
        quota_usd=Decimal("50.00"),
        monthly_quota_usd=Decimal("20.00"),
        monthly_reset_policy="reset",
        monthly_quota_start=None,
    )
    team = SimpleNamespace(
        user_id=user_id,
        monthly_budget_usd=Decimal("100.00"),
    )

    with patch.object(
        service,
        "_lock_team_and_members",
        AsyncMock(return_value=(team, [], Decimal("0.00"))),
    ):
        db.execute.side_effect = [
            _scalar_result(token),
            _scalar_result(None),
        ]
        await service.add_member(
            team_id=team_id,
            token_id=token.id,
            allocated_usd=Decimal("10.00"),
            user_id=user_id,
        )

    assert token.quota_usd is None
    assert token.monthly_quota_usd is None
    assert token.monthly_reset_policy is None
    assert token.monthly_quota_start is None


@pytest.mark.asyncio
async def test_batch_create_members_never_creates_lifetime_quota():
    db = AsyncMock()
    service = TeamService(db)
    team_id = uuid4()
    user_id = uuid4()
    token = SimpleNamespace(id=uuid4(), quota_usd=Decimal("50.00"))
    team = SimpleNamespace(
        user_id=user_id,
        monthly_budget_usd=Decimal("100.00"),
    )
    refreshed = MagicMock()
    refreshed.scalars.return_value.all.return_value = [token]
    db.execute.return_value = refreshed

    token_service = MagicMock()
    token_service.create_tokens_batch = AsyncMock(return_value=[(token, "secret")])

    with (
        patch.object(
            service,
            "_lock_team_and_members",
            AsyncMock(return_value=(team, [], Decimal("0.00"))),
        ),
        patch("app.services.token.TokenService", return_value=token_service),
    ):
        await service.batch_create_members(
            team_id=team_id,
            user_id=user_id,
            names=["member"],
            per_member_allocation=Decimal("10.00"),
            quota_usd=Decimal("50.00"),
        )

    assert token_service.create_tokens_batch.await_args.kwargs["quota_usd"] is None
    assert token.quota_usd is None
    assert token.monthly_quota_usd is None
    assert token.monthly_reset_policy is None
    assert token.monthly_quota_start is None


@pytest.mark.asyncio
async def test_token_only_import_cannot_restore_quota_on_existing_team_key():
    db = AsyncMock()
    service = DataManagementService(db)
    user = SimpleNamespace(id=uuid4())
    token = SimpleNamespace(
        id=uuid4(),
        quota_usd=None,
        monthly_quota_usd=None,
        monthly_reset_policy=None,
        monthly_quota_start=None,
    )
    db.execute.side_effect = [
        _scalar_result(token),
        _scalar_result(uuid4()),
    ]

    with patch.object(
        service,
        "_resolve_user_by_email",
        AsyncMock(return_value=user),
    ):
        await service._import_tokens(
            [
                {
                    "name": "member",
                    "user_email": "member@example.com",
                    "quota_usd": "50.00",
                    "monthly_quota_usd": "20.00",
                    "monthly_reset_policy": "reset",
                }
            ],
            "overwrite",
        )

    assert token.quota_usd is None
    assert token.monthly_quota_usd is None
    assert token.monthly_reset_policy is None
    assert token.monthly_quota_start is None


@pytest.mark.asyncio
async def test_import_team_member_clears_restored_standalone_quotas():
    db = AsyncMock()
    service = DataManagementService(db)
    team = SimpleNamespace(id=uuid4())
    user = SimpleNamespace(id=uuid4())
    token = SimpleNamespace(
        id=uuid4(),
        quota_usd=Decimal("50.00"),
        monthly_quota_usd=Decimal("20.00"),
        monthly_reset_policy="reset",
        monthly_quota_start=object(),
    )
    db.execute.side_effect = [
        _scalar_result(team),
        _scalar_result(token),
        _scalar_result(None),
    ]

    with patch.object(
        service,
        "_resolve_user_by_email",
        AsyncMock(return_value=user),
    ):
        await service._import_team_members(
            [
                {
                    "team_name": "team",
                    "token_name": "member",
                    "token_user_email": "member@example.com",
                    "allocated_usd": "10.00",
                }
            ],
            "overwrite",
        )

    assert token.quota_usd is None
    assert token.monthly_quota_usd is None
    assert token.monthly_reset_policy is None
    assert token.monthly_quota_start is None


def test_team_batch_request_does_not_expose_lifetime_quota():
    assert "quota_usd" not in BatchCreateMembersRequest.model_fields

"""add audit actions for key views, exports, balance, pricing, observability

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-11-09 00:00:00.000000
"""

from alembic import op

revision = "f3a4b5c6d7e8"  # pragma: allowlist secret
down_revision = "e2f3a4b5c6d7"  # pragma: allowlist secret
branch_labels = None
depends_on = None

_NEW = (
    "API_KEY_VIEWED",
    "API_KEYS_EXPORTED",
    "TOKEN_BALANCE_ADJUSTED",
    "PRICING_UPDATED",
    "OBSERVABILITY_UPDATED",
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for value in _NEW:
            op.execute(f"ALTER TYPE auditaction ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres can't drop enum values; unused labels are harmless.
    pass

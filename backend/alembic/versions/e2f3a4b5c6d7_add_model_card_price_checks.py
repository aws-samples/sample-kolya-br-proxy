"""add model_card_price_checks

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "e2f3a4b5c6d7"  # pragma: allowlist secret
down_revision = "d1e2f3a4b5c6"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_card_price_checks",
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("model_id"),
    )


def downgrade() -> None:
    op.drop_table("model_card_price_checks")

"""add_cache_token_columns_to_usage_records

Revision ID: a1b2c3d4e5f6
Revises: 7ce867a32c84
Create Date: 2026-03-11 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"  # pragma: allowlist secret
down_revision = "7ce867a32c84"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usage_records",
        sa.Column(
            "cache_creation_input_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "usage_records",
        sa.Column(
            "cache_read_input_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("usage_records", "cache_read_input_tokens")
    op.drop_column("usage_records", "cache_creation_input_tokens")

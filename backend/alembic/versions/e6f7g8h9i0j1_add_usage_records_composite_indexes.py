"""add_usage_records_composite_indexes

Revision ID: e6f7g8h9i0j1
Revises: d5e6f7g8h9i0
Create Date: 2026-04-10 10:00:00.000000

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "e6f7g8h9i0j1"  # pragma: allowlist secret
down_revision = "d5e6f7g8h9i0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_usage_records_user_id_created_at",
        "usage_records",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_usage_records_token_id_created_at",
        "usage_records",
        ["token_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_usage_records_token_id_created_at", table_name="usage_records")
    op.drop_index("ix_usage_records_user_id_created_at", table_name="usage_records")

"""add performance indexes for usage_records

Revision ID: w4x5y6z7a8b9
Revises: v3w4x5y6z7a8
Create Date: 2026-07-04

"""

from alembic import op

revision = "w4x5y6z7a8b9"
down_revision = "v3w4x5y6z7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use CONCURRENTLY to avoid locking the table during index creation.
    # Requires autocommit — disable the migration transaction wrapper.
    op.execute("COMMIT")
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_usage_records_record_type_created_at "
        "ON usage_records (record_type, created_at)"
    )
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_usage_records_model_created_at "
        "ON usage_records (model, created_at)"
    )
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_usage_records_token_model_created_at "
        "ON usage_records (token_id, model, created_at)"
    )


def downgrade() -> None:
    op.drop_index("ix_usage_records_token_model_created_at", "usage_records")
    op.drop_index("ix_usage_records_model_created_at", "usage_records")
    op.drop_index("ix_usage_records_record_type_created_at", "usage_records")

"""add stored_responses (owner of each stored upstream response)

Revision ID: 113bc43112d7
Revises: f3a4b5c6d7e8
Create Date: 2026-11-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "113bc43112d7"  # pragma: allowlist secret
down_revision = "f3a4b5c6d7e8"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stored_responses",
        sa.Column("response_id", sa.String(length=128), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["token_id"], ["api_tokens.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("response_id"),
    )
    op.create_index("ix_stored_responses_token_id", "stored_responses", ["token_id"])
    op.create_index(
        "ix_stored_responses_created_at", "stored_responses", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_stored_responses_created_at", table_name="stored_responses")
    op.drop_index("ix_stored_responses_token_id", table_name="stored_responses")
    op.drop_table("stored_responses")

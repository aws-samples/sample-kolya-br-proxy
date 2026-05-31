"""add notify_emails to api_tokens

Revision ID: v3w4x5y6z7a8
Revises: u2v3w4x5y6z7
Create Date: 2026-05-31

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "v3w4x5y6z7a8"
down_revision = "u2v3w4x5y6z7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_tokens",
        sa.Column("notify_emails", postgresql.ARRAY(sa.String()), nullable=True),
    )
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'API_KEY_NOTIFIED'")


def downgrade() -> None:
    op.drop_column("api_tokens", "notify_emails")

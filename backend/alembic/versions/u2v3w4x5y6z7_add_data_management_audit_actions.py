"""add data management audit actions to auditaction enum

Revision ID: u2v3w4x5y6z7
Revises: t1u2v3w4x5y6
Create Date: 2026-05-31 00:00:00.000000
"""

from alembic import op

revision = "u2v3w4x5y6z7"
down_revision = "t1u2v3w4x5y6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLAlchemy stores enum NAMES (uppercase) in the auditaction PG enum.
    # The data export/import endpoints write these actions, so the values must
    # exist in the DB or the INSERT fails on existing deployments.
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'DATA_EXPORTED'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'DATA_IMPORTED'")


def downgrade() -> None:
    pass

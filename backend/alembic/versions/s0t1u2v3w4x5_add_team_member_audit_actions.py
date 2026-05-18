"""add team member audit actions to auditaction enum

Revision ID: s0t1u2v3w4x5
Revises: r9s0t1u2v3w4
Create Date: 2026-05-18 00:00:00.000000
"""

from alembic import op

revision = "s0t1u2v3w4x5"
down_revision = "r9s0t1u2v3w4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'TEAM_MEMBER_ADDED'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'TEAM_MEMBER_REMOVED'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'TEAM_MEMBER_UPDATED'")


def downgrade() -> None:
    pass

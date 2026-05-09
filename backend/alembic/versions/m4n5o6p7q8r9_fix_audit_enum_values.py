"""fix auditaction enum - add uppercase values matching SQLAlchemy names

Revision ID: m4n5o6p7q8r9
Revises: l3m4n5o6p7q8
Create Date: 2026-05-09
"""

from alembic import op

revision = "m4n5o6p7q8r9"
down_revision = "l3m4n5o6p7q8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The initial migration created auditaction enum with uppercase names (LOGIN_SUCCESS etc).
    # The RBAC migration incorrectly added lowercase values. SQLAlchemy uses enum NAMES
    # (uppercase) by default, so we need uppercase values in the DB.
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'ADMIN_CREATED'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'ADMIN_UPDATED'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'ADMIN_DELETED'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'TOKEN_CREATED'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'TOKEN_UPDATED'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'TOKEN_DELETED'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'TEAM_CREATED'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'TEAM_UPDATED'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'TEAM_DELETED'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'MODEL_UPDATED'")


def downgrade() -> None:
    pass

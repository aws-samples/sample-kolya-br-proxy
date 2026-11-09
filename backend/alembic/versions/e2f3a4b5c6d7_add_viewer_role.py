"""add read-only viewer role to userrole enum

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-11-09
"""

from alembic import op

revision = "e2f3a4b5c6d7"  # pragma: allowlist secret
down_revision = "d1e2f3a4b5c6"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD VALUE can't run inside a transaction block on older PostgreSQL.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'viewer'")


def downgrade() -> None:
    # PostgreSQL can't drop an enum value, so it stays in the type. Viewers
    # are deactivated rather than demoted: an admin with no permissions has
    # full access, which would silently escalate them.
    op.execute(
        "UPDATE users SET role = 'admin', is_admin = false, is_active = false "
        "WHERE role = 'viewer'"
    )

"""set kolya@amazon.com as super_admin

Revision ID: l3m4n5o6p7q8
Revises: k2l3m4n5o6p7
Create Date: 2026-05-09
"""

from alembic import op

revision = "l3m4n5o6p7q8"
down_revision = "k2l3m4n5o6p7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure the earliest user is super_admin (idempotent)
    op.execute("""
        UPDATE users SET role = 'super_admin', is_admin = true
        WHERE id = (
            SELECT id FROM users ORDER BY created_at ASC LIMIT 1
        )
        AND NOT EXISTS (SELECT 1 FROM users WHERE role = 'super_admin')
    """)


def downgrade() -> None:
    pass

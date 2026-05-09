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
    op.execute(
        "UPDATE users SET role = 'super_admin', is_admin = true WHERE email = 'kolya@amazon.com'"
    )


def downgrade() -> None:
    pass

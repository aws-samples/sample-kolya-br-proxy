"""fix deleted tokens still having is_active=true

Revision ID: n5o6p7q8r9s0
Revises: m4n5o6p7q8r9
Create Date: 2026-05-13 12:00:00.000000

"""

from alembic import op

revision = "n5o6p7q8r9s0"
down_revision = "m4n5o6p7q8r9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE api_tokens SET is_active = false WHERE is_deleted = true AND is_active = true"
    )


def downgrade() -> None:
    pass

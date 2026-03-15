"""add_pkce_code_verifier_to_oauth_states

Revision ID: c3d4e5f6g7h8
Revises: a1b2c3d4e5f6
Create Date: 2026-03-15 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c3d4e5f6g7h8"  # pragma: allowlist secret
down_revision = "a1b2c3d4e5f6"  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "oauth_states",
        sa.Column("code_verifier", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("oauth_states", "code_verifier")

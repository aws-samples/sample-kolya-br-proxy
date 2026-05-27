"""Add entra_group_mappings table.

Revision ID: t1u2v3w4x5y6
Revises: s0t1u2v3w4x5
Create Date: 2026-05-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "t1u2v3w4x5y6"
down_revision = "s0t1u2v3w4x5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entra_group_mappings",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("entra_group_id", sa.String(255), nullable=False),
        sa.Column("group_name", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.String(50),
            nullable=False,
            server_default="admin",
        ),
        sa.Column("permissions", sa.JSON(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_entra_group_mappings_entra_group_id",
        "entra_group_mappings",
        ["entra_group_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_entra_group_mappings_entra_group_id", "entra_group_mappings")
    op.drop_table("entra_group_mappings")

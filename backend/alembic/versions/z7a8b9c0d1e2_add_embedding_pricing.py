"""add per-modality embedding pricing

Revision ID: z7a8b9c0d1e2
Revises: y6z7a8b9c0d1
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op

revision = "z7a8b9c0d1e2"
down_revision = "y6z7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "embedding_pricing",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("region", sa.String(length=50), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("price_per_unit", sa.Numeric(precision=24, scale=14), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("last_updated", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_id",
            "region",
            "unit",
            name="uq_embedding_pricing_model_region_unit",
        ),
    )
    op.create_index(
        "ix_embedding_pricing_id", "embedding_pricing", ["id"], unique=False
    )
    op.create_index(
        "ix_embedding_pricing_model_id",
        "embedding_pricing",
        ["model_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_embedding_pricing_model_id", table_name="embedding_pricing")
    op.drop_index("ix_embedding_pricing_id", table_name="embedding_pricing")
    op.drop_table("embedding_pricing")

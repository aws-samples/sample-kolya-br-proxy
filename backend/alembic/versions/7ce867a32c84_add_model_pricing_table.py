"""add_model_pricing_table

Revision ID: 7ce867a32c84
Revises: 0f4f689d9e69
Create Date: 2026-02-20 08:49:03.690775

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7ce867a32c84"  # pragma: allowlist secret
down_revision = "0f4f689d9e69"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create table
    op.create_table(
        "model_pricing",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("region", sa.String(length=50), nullable=False),
        sa.Column(
            "input_price_per_token", sa.Numeric(precision=20, scale=10), nullable=False
        ),
        sa.Column(
            "output_price_per_token", sa.Numeric(precision=20, scale=10), nullable=False
        ),
        sa.Column(
            "currency", sa.String(length=10), nullable=False, server_default="USD"
        ),
        sa.Column("source", sa.String(length=50), nullable=False),  # 'api' or 'scraper'
        sa.Column("last_updated", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_id", "region", name="uq_model_region"),
    )
    op.create_index("ix_model_pricing_model_id", "model_pricing", ["model_id"])
    op.create_index("ix_model_pricing_region", "model_pricing", ["region"])

    # Note: No default data inserted here
    # Run `python init_pricing.py` after migration to fetch and populate initial pricing data


def downgrade() -> None:
    op.drop_index("ix_model_pricing_region", table_name="model_pricing")
    op.drop_index("ix_model_pricing_model_id", table_name="model_pricing")
    op.drop_table("model_pricing")

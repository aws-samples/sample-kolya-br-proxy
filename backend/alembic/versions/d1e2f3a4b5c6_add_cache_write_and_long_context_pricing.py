"""add cache-write and long-context pricing to model_pricing

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "d1e2f3a4b5c6"
down_revision = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None

_PRICE = sa.Numeric(precision=20, scale=10)


def upgrade() -> None:
    op.add_column(
        "model_pricing", sa.Column("cache_write_price_per_token", _PRICE, nullable=True)
    )
    op.add_column(
        "model_pricing",
        sa.Column("long_context_threshold", sa.Integer(), nullable=True),
    )
    op.add_column(
        "model_pricing", sa.Column("long_input_price_per_token", _PRICE, nullable=True)
    )
    op.add_column(
        "model_pricing", sa.Column("long_output_price_per_token", _PRICE, nullable=True)
    )
    op.add_column(
        "model_pricing",
        sa.Column("long_cached_input_price_per_token", _PRICE, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_pricing", "long_cached_input_price_per_token")
    op.drop_column("model_pricing", "long_output_price_per_token")
    op.drop_column("model_pricing", "long_input_price_per_token")
    op.drop_column("model_pricing", "long_context_threshold")
    op.drop_column("model_pricing", "cache_write_price_per_token")

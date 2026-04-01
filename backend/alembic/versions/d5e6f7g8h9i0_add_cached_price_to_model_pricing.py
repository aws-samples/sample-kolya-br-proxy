"""add_cached_price_to_model_pricing

Revision ID: d5e6f7g8h9i0
Revises: c3d4e5f6g7h8
Create Date: 2026-04-01 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d5e6f7g8h9i0"  # pragma: allowlist secret
down_revision = "c3d4e5f6g7h8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add cached_input_price_per_token column for Gemini implicit cache pricing
    # Nullable because existing Bedrock models don't have a separate cached price
    op.add_column(
        "model_pricing",
        sa.Column(
            "cached_input_price_per_token",
            sa.Numeric(precision=20, scale=10),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("model_pricing", "cached_input_price_per_token")

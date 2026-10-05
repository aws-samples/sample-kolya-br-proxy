"""widen usage_records.cost_usd to numeric(20, 10)

numeric(10, 4) rounded sub-cent costs: a short Nova embedding (~$0.0000014)
was stored as 0.0000 and a single standard image ($0.00006) as 0.0001.
Scale 10 matches model_pricing per-token prices.

Operational note: increasing the scale of a PostgreSQL numeric column
rewrites the table under an ACCESS EXCLUSIVE lock. On a large
usage_records table, run this migration in a maintenance window.

Downgrade rounds existing values back to four decimal places (lossy).

Revision ID: a8b9c0d1e2f3
Revises: z7a8b9c0d1e2
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op

revision = "a8b9c0d1e2f3"
down_revision = "z7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "usage_records",
        "cost_usd",
        existing_type=sa.Numeric(precision=10, scale=4),
        type_=sa.Numeric(precision=20, scale=10),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "usage_records",
        "cost_usd",
        existing_type=sa.Numeric(precision=20, scale=10),
        type_=sa.Numeric(precision=10, scale=4),
        existing_nullable=False,
    )

"""add spend limits and monthly quota to api_tokens

Revision ID: f7g8h9i0j1k2
Revises: e6f7g8h9i0j1
Create Date: 2026-04-21 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f7g8h9i0j1k2"  # pragma: allowlist secret
down_revision = "e6f7g8h9i0j1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_tokens",
        sa.Column("monthly_quota_usd", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "api_tokens",
        sa.Column(
            "monthly_quota_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "api_tokens",
        sa.Column("last_quota_reset_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "api_tokens",
        sa.Column("daily_spend_limit_usd", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "api_tokens",
        sa.Column("hourly_spend_limit_usd", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "api_tokens",
        sa.Column(
            "rate_limit_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("api_tokens", "rate_limit_enabled")
    op.drop_column("api_tokens", "hourly_spend_limit_usd")
    op.drop_column("api_tokens", "daily_spend_limit_usd")
    op.drop_column("api_tokens", "last_quota_reset_at")
    op.drop_column("api_tokens", "monthly_quota_enabled")
    op.drop_column("api_tokens", "monthly_quota_usd")

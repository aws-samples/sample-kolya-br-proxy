"""Add teams and team_members tables.

Revision ID: h9i0j1k2l3m4
Revises: g8h9i0j1k2l3
Create Date: 2026-05-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "h9i0j1k2l3m4"
down_revision = "g8h9i0j1k2l3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("monthly_budget_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "monthly_reset_policy",
            sa.String(20),
            nullable=False,
            server_default="reset",
        ),
        sa.Column("monthly_budget_start", sa.DateTime(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_teams_user_id", "teams", ["user_id"])

    op.create_table(
        "team_members",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("team_id", UUID(as_uuid=True), nullable=False),
        sa.Column("token_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "allocated_usd", sa.Numeric(10, 2), nullable=False, server_default="0.00"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["token_id"], ["api_tokens.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_team_members_team_id", "team_members", ["team_id"])
    op.create_index(
        "ix_team_members_token_id", "team_members", ["token_id"], unique=True
    )
    op.execute(
        "ALTER TABLE team_members "
        "ADD CONSTRAINT ck_allocated_non_negative CHECK (allocated_usd >= 0)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE team_members DROP CONSTRAINT IF EXISTS ck_allocated_non_negative"
    )
    op.drop_index("ix_team_members_token_id", "team_members")
    op.drop_index("ix_team_members_team_id", "team_members")
    op.drop_table("team_members")
    op.drop_index("ix_teams_user_id", "teams")
    op.drop_table("teams")

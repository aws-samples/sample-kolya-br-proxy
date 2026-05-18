"""add alert tables

Revision ID: p7q8r9s0t1u2
Revises: n5o6p7q8r9s0
Create Date: 2026-05-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "p7q8r9s0t1u2"
down_revision = "n5o6p7q8r9s0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("alert_type", sa.String(20), nullable=False),
        sa.Column("rule_key", sa.String(50), nullable=False),
        sa.Column("threshold_value", sa.Numeric(12, 4), nullable=False),
        sa.Column("cooldown_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("notify_email", sa.Text(), nullable=True),
        sa.Column("notify_phone", sa.Text(), nullable=True),
        sa.Column(
            "notify_in_app",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["token_id"], ["api_tokens.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.CheckConstraint(
            "NOT (token_id IS NOT NULL AND team_id IS NOT NULL)",
            name="ck_alert_rules_scope_exclusive",
        ),
    )
    op.create_index("ix_alert_rules_user_id", "alert_rules", ["user_id"])
    op.create_index("ix_alert_rules_token_id", "alert_rules", ["token_id"])
    op.create_index("ix_alert_rules_team_id", "alert_rules", ["team_id"])

    op.create_table(
        "alert_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alert_rule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rule_key", sa.String(50), nullable=False),
        sa.Column("alert_type", sa.String(20), nullable=False),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope_name", sa.String(255), nullable=True),
        sa.Column("current_value", sa.Numeric(12, 4), nullable=False),
        sa.Column("threshold_value", sa.Numeric(12, 4), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("channels_used", sa.String(100), nullable=True),
        sa.Column(
            "is_read",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["alert_rule_id"], ["alert_rules.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_alert_notifications_user_created",
        "alert_notifications",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_alert_notifications_user_read",
        "alert_notifications",
        ["user_id", "is_read"],
    )


def downgrade() -> None:
    op.drop_table("alert_notifications")
    op.drop_table("alert_rules")

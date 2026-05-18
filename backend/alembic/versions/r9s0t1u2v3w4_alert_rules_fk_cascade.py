"""alert rules FK ondelete CASCADE for team_id and token_id

Revision ID: r9s0t1u2v3w4
Revises: q8r9s0t1u2v3
Create Date: 2026-05-18 00:00:00.000000
"""

from alembic import op

revision = "r9s0t1u2v3w4"
down_revision = "q8r9s0t1u2v3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("alert_rules_team_id_fkey", "alert_rules", type_="foreignkey")
    op.create_foreign_key(
        "alert_rules_team_id_fkey",
        "alert_rules",
        "teams",
        ["team_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("alert_rules_token_id_fkey", "alert_rules", type_="foreignkey")
    op.create_foreign_key(
        "alert_rules_token_id_fkey",
        "alert_rules",
        "api_tokens",
        ["token_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("alert_rules_token_id_fkey", "alert_rules", type_="foreignkey")
    op.create_foreign_key(
        "alert_rules_token_id_fkey",
        "alert_rules",
        "api_tokens",
        ["token_id"],
        ["id"],
    )

    op.drop_constraint("alert_rules_team_id_fkey", "alert_rules", type_="foreignkey")
    op.create_foreign_key(
        "alert_rules_team_id_fkey",
        "alert_rules",
        "teams",
        ["team_id"],
        ["id"],
    )

"""add rbac role and permissions to users

Revision ID: k2l3m4n5o6p7
Revises: j1k2l3m4n5o6
Create Date: 2026-05-09
"""

from alembic import op
import sqlalchemy as sa

revision = "k2l3m4n5o6p7"
down_revision = "j1k2l3m4n5o6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum type
    userrole = sa.Enum("super_admin", "admin", name="userrole")
    userrole.create(op.get_bind(), checkfirst=True)

    # Add role column with default 'admin'
    op.add_column(
        "users",
        sa.Column("role", userrole, nullable=False, server_default="admin"),
    )
    op.create_index("ix_users_role", "users", ["role"])

    # Add permissions JSON column
    op.add_column(
        "users",
        sa.Column("permissions", sa.JSON(), nullable=True),
    )

    # Promote the earliest created user to super_admin
    op.execute("""
        UPDATE users SET role = 'super_admin', is_admin = true
        WHERE id = (
            SELECT id FROM users ORDER BY created_at ASC LIMIT 1
        )
    """)

    # Add new audit action enum values
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'admin_created'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'admin_updated'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'admin_deleted'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'token_created'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'token_updated'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'token_deleted'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'team_created'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'team_updated'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'team_deleted'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'model_updated'")


def downgrade() -> None:
    op.drop_index("ix_users_role", table_name="users")
    op.drop_column("users", "permissions")
    op.drop_column("users", "role")
    sa.Enum(name="userrole").drop(op.get_bind(), checkfirst=True)
